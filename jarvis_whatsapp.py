"""Read and prepare replies in WhatsApp Desktop through Windows UI Automation.

This module never presses Send. It can list unread chats, open a chat, and type
a reply into the message box so the user only has to review and press Send.

WhatsApp's accessibility tree exposes the chat list and the message box, but not
individual message bubbles. Conversation text is therefore read with a
screenshot plus Gemini vision (see ``jarvis_screen``).
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

from jarvis_pc import ActionError

BASE = Path(__file__).resolve().parent
WINDOW_NAME = "WhatsApp"
CHAT_LIST_NAME = "Chat list"
SEARCH_BOX_NAME = "Search or start a new chat"
MESSAGE_BOX_PREFIX = "Type a message to "

_TIME_TOKEN_RE = re.compile(
    r"\b(?:yesterday|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b\d{1,2}:\d{2}\s*(?:am|pm)?\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.IGNORECASE,
)
_UNREAD_RE = re.compile(r"(\d[\d,]*)\s+unread\s+messages?", re.IGNORECASE)
_LEADING_UNREAD_RE = re.compile(
    r"^\s*\d[\d,]*\s+unread\s+messages?\s+", re.IGNORECASE
)
_LABEL_RE = re.compile(r"\b(?:pinned chat|starred chat)\b", re.IGNORECASE)


def _uia():
    try:
        import uiautomation as auto
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Reading WhatsApp needs the uiautomation package. "
            "Run pip install -r requirements.txt and restart Jarvis."
        ) from error
    return auto


@contextmanager
def _automation():
    auto = _uia()
    try:
        auto.SetGlobalSearchTimeout(2)
    except Exception:
        pass
    context = None
    initializer = getattr(auto, "UIAutomationInitializerInThread", None)
    if initializer is not None:
        try:
            context = initializer()
            context.__enter__()
        except Exception:
            context = None
    try:
        yield auto
    finally:
        if context is not None:
            try:
                context.__exit__(None, None, None)
            except Exception:
                pass


def _windows():
    try:
        import win32api
        import win32con
        import win32gui
        import win32process

        return win32api, win32con, win32gui, win32process
    except Exception as error:  # pragma: no cover - Windows only
        raise ActionError(
            "Controlling WhatsApp needs pywin32. Run pip install -r requirements.txt."
        ) from error


def _find_window(auto):
    for window in auto.GetRootControl().GetChildren():
        try:
            if (window.Name or "").strip() == WINDOW_NAME:
                return window
        except Exception:
            continue
    return None


def _find_document(auto, window):
    documents = []

    def walk(control, depth=0):
        if depth > 10 or documents:
            return
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                if child.ControlTypeName == "DocumentControl":
                    documents.append(child)
                    return
                walk(child, depth + 1)
            except Exception:
                continue

    walk(window)
    if not documents:
        raise ActionError(
            "WhatsApp is open, but I can't read its window yet. "
            "Bring WhatsApp to the front and try again."
        )
    return documents[0]


CHAT_GRID_NAMES = (CHAT_LIST_NAME, "Search results.", "Search results")


def _try_chat_list(auto, document, timeout: float = 1.0):
    for name in CHAT_GRID_NAMES:
        grid = auto.DataGridControl(
            searchFromControl=document, Name=name, searchDepth=12
        )
        try:
            if grid.Exists(timeout):
                return grid
        except Exception:
            continue
    return None


def _is_search_grid(grid) -> bool:
    try:
        return "search" in str(grid.Name or "").lower()
    except Exception:
        return False


def _chat_list(auto, document):
    grid = _try_chat_list(auto, document, timeout=2.0)
    if grid is None:
        raise ActionError(
            "I couldn't find the WhatsApp chat list. Open WhatsApp and try again."
        )
    return grid


def _wait_for_chat_list(auto, document, timeout: float):
    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        grid = _try_chat_list(auto, document, timeout=1.0)
        if grid is not None:
            return grid
        time.sleep(0.7)
    return None


def _reconnect(auto, window, hwnd: int) -> bool:
    """Recover WhatsApp's "unexpected error" screen by clicking Reconnect."""
    button = auto.ButtonControl(
        searchFromControl=window, Name="Reconnect", searchDepth=20
    )
    try:
        if button.Exists(1):
            button.Click()
            return True
    except Exception:
        pass

    # The error card is rendered inside the web view, so UIA sometimes exposes
    # no controls at all. Let Gemini locate the Reconnect button on a screenshot.
    try:
        import jarvis_screen

        _win32api, _win32con, win32gui, _win32process = _windows()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right - left < 300 or bottom - top < 300:
            return False
        jarvis_screen.enable_dpi_awareness()
        screenshot = jarvis_screen.capture_screen(
            region=(left, top, right, bottom)
        )
        raw = jarvis_screen.analyze_image(
            screenshot,
            "If this image shows a WhatsApp error screen with a Reconnect "
            "button, return ONLY JSON with its location as "
            '{"reconnect":true,"x":512,"y":522} where x and y are 0..1000 '
            "relative to the image. Otherwise return {\"reconnect\":false}.",
        )
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return False
        data = json.loads(match.group(0))
        if not data.get("reconnect"):
            return False
        x = max(0, min(1000, float(data.get("x", 500))))
        y = max(0, min(1000, float(data.get("y", 500))))
        import pyautogui

        pyautogui.click(
            left + round(x / 1000 * (right - left)),
            top + round(y / 1000 * (bottom - top)),
        )
        return True
    except Exception:
        return False


def _focus_window(auto, window):
    return _focus_hwnd(int(window.NativeWindowHandle))


def _focus_hwnd(hwnd: int):
    win32api, win32con, win32gui, win32process = _windows()
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    if win32gui.GetForegroundWindow() != hwnd:
        foreground = win32gui.GetForegroundWindow()
        foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        current_thread = win32api.GetCurrentThreadId()
        attached = False
        try:
            win32process.AttachThreadInput(current_thread, foreground_thread, True)
            attached = True
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(
                        current_thread, foreground_thread, False
                    )
                except Exception:
                    pass
    time.sleep(0.25)
    return hwnd


def _ensure_whatsapp(auto, focus=True, timeout=12.0):
    window = _find_window(auto)
    if window is None:
        starter = getattr(os, "startfile", None)
        if starter is not None:
            try:
                starter("whatsapp:")
            except OSError:
                pass
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline and window is None:
            time.sleep(0.6)
            window = _find_window(auto)
    if window is None:
        raise ActionError(
            "I couldn't find WhatsApp Desktop. Install it from the Microsoft "
            "Store, sign in, and leave it running."
        )
    hwnd = _focus_window(auto, window) if focus else int(window.NativeWindowHandle)
    try:
        document = _find_document(auto, window)
    except ActionError:
        document = None

    grid = None
    if document is not None:
        grid = _wait_for_chat_list(auto, document, 6.0 if focus else 1.5)
    if grid is None and _reconnect(auto, window, hwnd):
        time.sleep(2.0)
        try:
            document = _find_document(auto, window)
        except ActionError:
            document = None
        if document is not None:
            grid = _wait_for_chat_list(auto, document, 20.0)
    if grid is None and document is not None:
        grid = _wait_for_chat_list(auto, document, 10.0)
    if grid is None:
        raise ActionError(
            "WhatsApp is showing an error or is still loading. Open WhatsApp, "
            "click Reconnect if it is visible, and try again."
        )
    return window, document, hwnd


def _item_name(item) -> str:
    try:
        return str(item.Name or "").strip()
    except Exception:
        return ""


def _chat_items(auto, document):
    grid = _chat_list(auto, document)
    items = []
    seen = set()
    try:
        children = grid.GetChildren()
    except Exception as error:
        raise ActionError(f"I couldn't read the WhatsApp chat list: {error}") from error
    for item in children:
        name = _item_name(item)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _shorten(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def parse_chat_item(raw: str) -> dict:
    """Turn WhatsApp's concatenated accessibility name into chat details."""
    text = " ".join(str(raw or "").split())
    unread_match = _UNREAD_RE.search(text)
    unread = int(unread_match.group(1).replace(",", "")) if unread_match else 0

    time_match = _TIME_TOKEN_RE.search(text)
    if time_match:
        name_part = text[: time_match.start()]
        preview_part = text[time_match.end() :]
        timestamp = time_match.group(0)
    else:
        name_part = text
        preview_part = ""
        timestamp = ""

    name_part = _LEADING_UNREAD_RE.sub("", name_part)
    name_part = _UNREAD_RE.sub("", name_part)
    name_part = _LABEL_RE.sub("", name_part)
    name = " ".join(name_part.split()).strip(" -–—:|\u00a0")

    preview = _UNREAD_RE.sub("", preview_part, count=1)
    preview = _LABEL_RE.sub("", preview)
    preview = " ".join(preview.split()).strip(" -–—:|\u00a0")

    if not name and unread_match:
        remainder = _UNREAD_RE.sub("", text, count=1).strip()
        name = _TIME_TOKEN_RE.split(remainder, maxsplit=1)[0].strip(
            " -–—:|\u00a0"
        )

    return {
        "name": name,
        "unread": unread,
        "preview": preview,
        "time": timestamp,
        "pinned": bool(re.search(r"\bpinned chat\b", text, re.I)),
        "starred": bool(re.search(r"\bstarred chat\b", text, re.I)),
    }


def format_unread_chats(outcome: dict) -> str:
    chats = list((outcome or {}).get("chats") or [])
    count = int((outcome or {}).get("count") or len(chats))
    unread_total = int((outcome or {}).get("unread_total") or 0)
    if not chats:
        return "You have no unread WhatsApp messages in the currently visible chats."
    total_text = f" ({unread_total} messages)" if unread_total else ""
    lines = [
        f"You have unread WhatsApp messages in {count} "
        f"chat{'s' if count != 1 else ''}{total_text}:"
    ]
    for chat in chats:
        preview = _shorten(chat.get("preview", ""), 150)
        line = f"- {chat.get('name', 'Unknown')}: {chat.get('unread', 0)} unread"
        if preview:
            line += f" — {preview}"
        lines.append(line)
    hidden = count - len(chats)
    if hidden > 0:
        lines.append(f"…and {hidden} more chat{'s' if hidden != 1 else ''}.")
    lines.append("Which one would you like me to open, or should I draft a reply?")
    return "\n".join(lines)


def _ensure_full_chat_list(auto, window, document):
    grid = _try_chat_list(auto, document, 1.0)
    if grid is not None and _is_search_grid(grid):
        _clear_search(auto, document)
        time.sleep(0.7)
        try:
            document = _find_document(auto, window)
        except ActionError:
            return document
        _wait_for_chat_list(auto, document, 6.0)
    return document


def list_unread_chats(limit: int = 8) -> dict:
    """Return unread chats currently visible in WhatsApp Desktop."""
    limit = max(1, min(25, int(limit or 8)))
    with _automation() as auto:
        window, document, _hwnd = _ensure_whatsapp(auto, focus=True)
        document = _ensure_full_chat_list(auto, window, document)
        chats = []
        for item in _chat_items(auto, document):
            parsed = parse_chat_item(_item_name(item))
            if parsed["unread"] > 0 and parsed["name"]:
                chats.append(parsed)
    return {
        "chats": chats[:limit],
        "count": len(chats),
        "unread_total": sum(chat["unread"] for chat in chats),
    }


def _best_item(auto, document, name: str):
    wanted = str(name or "").strip().casefold()
    if not wanted:
        raise ActionError("Which WhatsApp chat should I open?")
    candidates = []
    for index, item in enumerate(_chat_items(auto, document)):
        parsed = parse_chat_item(_item_name(item))
        chat_name = parsed["name"].casefold()
        if not chat_name:
            continue
        if chat_name == wanted:
            score = 0
        elif chat_name.startswith(wanted):
            score = 1
        elif wanted in chat_name or chat_name in wanted:
            score = 2
        else:
            continue
        # Keep WhatsApp's own result order as the tie-breaker.
        candidates.append((score, index, item, parsed["name"]))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (entry[0], entry[1]))
    return candidates[0][2], candidates[0][3]


def _search_box(auto, document):
    # With text in it, WhatsApp clears the edit control's accessible name but
    # keeps this automation id. Fall back to its position at the top-left.
    for kwargs in ({"Name": SEARCH_BOX_NAME}, {"AutomationId": "_r_e_"}):
        search = auto.EditControl(
            searchFromControl=document, searchDepth=16, **kwargs
        )
        try:
            if search.Exists(0.6):
                return search
        except Exception:
            continue

    candidates = []

    def walk(control, depth=0):
        if depth > 18:
            return
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                if child.ControlTypeName == "EditControl":
                    candidates.append(child)
                walk(child, depth + 1)
            except Exception:
                continue

    walk(document)
    try:
        document_rect = document.BoundingRectangle
    except Exception:
        return None
    for candidate in candidates:
        try:
            rect = candidate.BoundingRectangle
            if (
                rect.top < document_rect.top + 220
                and rect.left < document_rect.left + 500
                and rect.width > 20
            ):
                return candidate
        except Exception:
            continue
    return None


def _clear_search(auto, document) -> None:
    try:
        import pyautogui

        search = _search_box(auto, document)
        if search is not None:
            search.Click()
            time.sleep(0.15)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("delete")
            pyautogui.press("escape")
            time.sleep(0.5)
    except Exception:
        pass


def _search_and_open(auto, document, name: str, hwnd: int):
    search = _search_box(auto, document)
    if search is None:
        return None
    try:
        import pyautogui
        import pyperclip
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Searching WhatsApp needs pyautogui and pyperclip. "
            "Run pip install -r requirements.txt."
        ) from error
    _focus_hwnd(hwnd)
    search.Click()
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("delete")
    pyperclip.copy(str(name))
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.4)
    found = _best_item(auto, document, name)
    if not found:
        _clear_search(auto, document)
        return None
    item, chat_name = found
    _focus_hwnd(hwnd)
    item.Click()
    time.sleep(1.1)
    _clear_search(auto, document)
    return chat_name


def _open_chat(auto, document, name: str, hwnd: int) -> str:
    found = _best_item(auto, document, name)
    if found is not None:
        item, chat_name = found
        _focus_hwnd(hwnd)
        item.Click()
        time.sleep(1.1)
        return chat_name
    chat_name = _search_and_open(auto, document, name, hwnd)
    if chat_name is None:
        raise ActionError(f"I couldn't find a WhatsApp chat called {name}.")
    return chat_name


def open_chat(name: str) -> str:
    """Open a WhatsApp chat by contact or group name."""
    with _automation() as auto:
        _window, document, hwnd = _ensure_whatsapp(auto, focus=True)
        chat_name = _open_chat(auto, document, name, hwnd)
    return chat_name


def _message_box(auto, document, chat_name: str):
    box = auto.EditControl(
        searchFromControl=document,
        Name=MESSAGE_BOX_PREFIX + chat_name,
        searchDepth=16,
    )
    if box.Exists(1):
        return box
    # Fall back to any message box, in case the accessible chat name differs.
    found = []

    def walk(control, depth=0):
        if depth > 16 or found:
            return
        try:
            children = control.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                if child.ControlTypeName == "EditControl":
                    name_text = str(child.Name or "")
                    if name_text.startswith(MESSAGE_BOX_PREFIX):
                        found.append(child)
                        return
                walk(child, depth + 1)
            except Exception:
                continue

    walk(document)
    return found[0] if found else None


def prefill_message(chat: str, message: str) -> str:
    """Open a chat and type a reply, leaving Send to the user."""
    text = str(message or "").strip()
    if not text:
        raise ActionError("What should the WhatsApp reply say?")
    with _automation() as auto:
        _window, document, hwnd = _ensure_whatsapp(auto, focus=True)
        chat_name = _open_chat(auto, document, chat, hwnd)
        _focus_hwnd(hwnd)
        box = _message_box(auto, document, chat_name)
        if box is None:
            raise ActionError(
                f"I opened {chat_name}, but I couldn't find the message box."
            )
        try:
            import pyautogui
            import pyperclip
        except Exception as error:  # pragma: no cover - depends on the machine
            raise ActionError(
                "Typing into WhatsApp needs pyautogui and pyperclip. "
                "Run pip install -r requirements.txt."
            ) from error
        box.Click()
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("delete")
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
    return (
        f"I opened the WhatsApp chat with {chat_name} and typed the reply. "
        "Review it and press Send in WhatsApp."
    )


def read_conversation(chat: str = "", question: str = "") -> str:
    """Read a chat with Gemini vision (message bubbles are not in UIA)."""
    import jarvis_screen

    with _automation() as auto:
        _window, document, hwnd = _ensure_whatsapp(auto, focus=True)
        chat_name = _open_chat(auto, document, chat, hwnd) if chat else ""
        _focus_hwnd(hwnd)
        time.sleep(0.7)
        _win32api, _win32con, win32gui, _win32process = _windows()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)

    width = max(1, right - left)
    height = max(1, bottom - top)
    if width < 500 or height < 400:
        raise ActionError(
            "WhatsApp is too small for me to read the conversation. "
            "Maximise the WhatsApp window and try again."
        )
    chat_left = left + max(250, int(width * 0.30))
    crop = (chat_left, top + 60, right, bottom - 100)
    screenshot = jarvis_screen.capture_screen(region=crop)
    prompt = question or (
        "Transcribe the recent messages in this WhatsApp conversation from "
        "oldest to newest. Include the sender name for each message when it is "
        "visible, and keep it compact. Do not add commentary."
    )
    answer = jarvis_screen.analyze_image(screenshot, prompt)
    prefix = f"Here's what I can read in the WhatsApp chat with {chat_name}:\n"
    return prefix + answer


def whatsapp_running() -> bool:
    """Best-effort check used by the integration checker."""
    if os.name != "nt":
        return False
    try:
        with _automation() as auto:
            return _find_window(auto) is not None
    except Exception:
        return False
