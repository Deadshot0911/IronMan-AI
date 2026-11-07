"""Local Windows control for Jarvis.

All public functions raise :class:`ActionError` with a message that can be
spoken to the user.  The functions here are intentionally side-effect heavy;
the authorization gate lives in ``jarvis_core.py`` and must be called before
any of them.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

BASE = Path(__file__).resolve().parent
HOME = Path.home()

COMMON_DIRS = (
    HOME,
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    HOME / "Pictures",
    HOME / "Music",
    HOME / "Videos",
    HOME / "OneDrive",
    HOME / "OneDrive" / "Desktop",
    HOME / "OneDrive" / "Documents",
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "AppData",
    "Windows",
    "Program Files",
    "Program Files (x86)",
}

URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?(?:/.*)?$",
    re.IGNORECASE,
)
LOCALHOST_RE = re.compile(r"^localhost(?::\d+)?(?:/.*)?$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

APP_ALIASES = {
    "chrome": ["chrome.exe"],
    "google chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "microsoft edge": ["msedge.exe"],
    "firefox": ["firefox.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "windows terminal": ["wt.exe", "powershell.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "word": ["winword.exe"],
    "microsoft word": ["winword.exe"],
    "excel": ["excel.exe"],
    "microsoft excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "microsoft powerpoint": ["powerpnt.exe"],
    "outlook": ["outlook.exe"],
    "spotify": ["spotify.exe"],
    "vscode": ["code.cmd", "code.exe"],
    "visual studio code": ["code.cmd", "code.exe"],
    "whatsapp": ["WhatsApp.exe"],
    "whatsapp desktop": ["WhatsApp.exe"],
}

SHELL_URI_APPS = {
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "camera": "microsoft.windows.camera:",
    "photos": "ms-photos:",
    "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    "mail": "outlookmail:",
    "windows mail": "outlookmail:",
    "calendar": "outlookcal:",
    "windows calendar": "outlookcal:",
}

_DEFAULT_BROWSER_URL = "https://www.google.com"


class ActionError(RuntimeError):
    """A user-facing failure while performing a laptop action."""


def _require_windows():
    if os.name != "nt":
        raise ActionError("That laptop action is only available on Windows.")


def _startfile(target: str):
    starter = getattr(os, "startfile", None)
    if starter is None:
        raise ActionError("I can't open that on this system.")
    starter(target)


def looks_like_url(value: str) -> bool:
    text = str(value or "").strip()
    if not text or " " in text:
        return False
    return bool(
        URL_RE.match(text) or DOMAIN_RE.match(text) or LOCALHOST_RE.match(text)
    )


def normalize_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ActionError("I need a web address.")
    if re.match(
        r"^(?:javascript|data|file|vbscript|about|chrome|mailto|whatsapp):",
        text,
        re.IGNORECASE,
    ):
        raise ActionError("That isn't a web address I can open safely.")
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE) and not re.match(
        r"^https?://", text, re.IGNORECASE
    ):
        raise ActionError("That isn't a web address I can open safely.")
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ActionError("That isn't a web address I can open safely.")
    return text


def open_url(value: str) -> str:
    url = normalize_url(value)
    webbrowser.open(url)
    return url


def search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(str(query or "").strip())


def _duckduckgo_results(query: str) -> list[dict]:
    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        },
        timeout=12,
    )
    response.raise_for_status()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for block in soup.select(".result"):
        link = block.select_one(".result__a")
        if not link:
            continue
        href = link.get("href") or ""
        if "uddg=" in href:
            query_string = urlparse(href).query
            target = parse_qs(query_string).get("uddg", [""])[0]
            if target:
                href = target
        snippet_node = block.select_one(".result__snippet")
        results.append(
            {
                "title": " ".join(link.get_text(" ", strip=True).split()),
                "url": href,
                "snippet": " ".join(
                    (snippet_node.get_text(" ", strip=True) if snippet_node else "").split()
                ),
            }
        )
        if len(results) >= 6:
            break
    return results


def _bing_results(query: str) -> list[dict]:
    response = requests.get(
        "https://www.bing.com/search",
        params={"q": query},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        },
        timeout=12,
    )
    response.raise_for_status()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for block in soup.select("li.b_algo"):
        link = block.select_one("h2 a")
        if not link:
            continue
        snippet_node = block.select_one("p")
        results.append(
            {
                "title": " ".join(link.get_text(" ", strip=True).split()),
                "url": link.get("href") or "",
                "snippet": " ".join(
                    (snippet_node.get_text(" ", strip=True) if snippet_node else "").split()
                ),
            }
        )
        if len(results) >= 6:
            break
    return results


def web_search(query: str, open_browser: bool = True) -> dict:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        raise ActionError("What should I search for?")
    url = search_url(text)
    if open_browser:
        webbrowser.open(url)
    results: list[dict] = []
    errors = []
    for provider in (_duckduckgo_results, _bing_results):
        try:
            results = provider(text)
            if results:
                break
        except Exception as error:  # network/provider markup changes are non-fatal
            errors.append(str(error))
    if not results and errors:
        print(f"[Search provider error: {'; '.join(errors)}]")
    return {"query": text, "search_url": url, "results": results}


def format_search_results(outcome: dict) -> str:
    query = outcome.get("query", "")
    results = outcome.get("results") or []
    lines = [f"Search results for {query}:"]
    if not results:
        lines.append(
            "I couldn't read the result snippets, but I've opened the search in your browser."
        )
        return "\n".join(lines)
    for index, result in enumerate(results[:5], 1):
        lines.append(f"{index}. {result.get('title', 'Untitled')}")
        if result.get("snippet"):
            lines.append(f"   {result['snippet']}")
        if result.get("url"):
            lines.append(f"   {result['url']}")
    return "\n".join(lines)


def summarize_search_results(outcome: dict, limit: int = 650) -> str:
    query = outcome.get("query", "that")
    results = outcome.get("results") or []
    if not results:
        return (
            f"I've opened the search for {query} in your browser, "
            "but I couldn't read the results aloud."
        )
    pieces = []
    for result in results[:3]:
        title = result.get("title", "").strip()
        snippet = result.get("snippet", "").strip()
        if snippet:
            pieces.append(snippet)
        elif title:
            pieces.append(title)
    summary = " ".join(pieces)
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > limit:
        summary = summary[: limit - 1].rsplit(" ", 1)[0] + "."
    if not summary:
        return f"I've opened the results for {query} in your browser."
    return f"Here's what I found about {query}. {summary}"


def _common_dirs() -> list[Path]:
    dirs = list(COMMON_DIRS)
    extra = os.environ.get("JARVIS_SEARCH_DIRS", "")
    for chunk in re.split(r"[;|]", extra):
        chunk = chunk.strip()
        if chunk:
            dirs.append(Path(os.path.expandvars(os.path.expanduser(chunk))))
    seen = set()
    unique = []
    for directory in dirs:
        try:
            resolved = directory.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key not in seen and resolved.is_dir():
            seen.add(key)
            unique.append(resolved)
    return unique


def _walk_matches(base: Path, wanted: str, deadline: float) -> list[Path]:
    matches = []
    try:
        for root, dirs, files in os.walk(base):
            if time.monotonic() > deadline:
                break
            relative = Path(root).relative_to(base) if root != str(base) else Path()
            depth = len(relative.parts)
            if depth >= 4:
                dirs[:] = []
            dirs[:] = [
                name
                for name in dirs
                if name not in SKIP_DIRS and not name.startswith((".", "$"))
            ]
            for name in files + dirs:
                if name.casefold() == wanted:
                    matches.append(Path(root) / name)
                    if len(matches) >= 25:
                        return matches
    except (OSError, ValueError):
        pass
    return matches


def resolve_path(target: str) -> Path:
    text = str(target or "").strip().strip("\"'")
    if not text:
        raise ActionError("I need a file name or path.")
    expanded = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(expanded)

    direct_candidates = []
    if candidate.is_absolute():
        direct_candidates.append(candidate)
    else:
        direct_candidates.extend(
            [Path.cwd() / candidate, BASE / candidate, HOME / candidate]
        )
    for item in direct_candidates:
        try:
            if item.exists():
                return item.resolve()
        except OSError:
            continue

    wanted = candidate.name.casefold()
    deadline = time.monotonic() + 3.0
    matches: list[Path] = []
    for base in _common_dirs():
        matches.extend(_walk_matches(base, wanted, deadline))
        if len(matches) >= 25 or time.monotonic() > deadline:
            break
    if not matches:
        # A looser contains-match helps with partial names such as "tax report".
        needle = wanted.replace(" ", "")
        for base in _common_dirs():
            for root, dirs, files in os.walk(base):
                if time.monotonic() > deadline:
                    break
                dirs[:] = [
                    name
                    for name in dirs
                    if name not in SKIP_DIRS and not name.startswith((".", "$"))
                ]
                for name in files + dirs:
                    if needle and needle in name.casefold().replace(" ", ""):
                        matches.append(Path(root) / name)
                        if len(matches) >= 15:
                            break
                if len(matches) >= 15:
                    break
            if len(matches) >= 15 or time.monotonic() > deadline:
                break
    if not matches:
        raise ActionError(
            f"I couldn't find anything called {text}. "
            "Try giving me the folder name too, or put the file on the Desktop."
        )
    matches.sort(key=lambda item: (item.is_dir(), len(item.parts), len(item.name)))
    return matches[0].resolve()


def open_path(target: str) -> str:
    path = resolve_path(target)
    _startfile(str(path))
    return str(path)


COMMON_FOLDER_NAMES = {
    "desktop": HOME / "Desktop",
    "documents": HOME / "Documents",
    "downloads": HOME / "Downloads",
    "pictures": HOME / "Pictures",
    "music": HOME / "Music",
    "videos": HOME / "Videos",
}


def _format_size(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def resolve_write_path(target: str) -> Path:
    """Resolve a path for a new file, creating parent folders when needed."""
    text = str(target or "").strip().strip("\"'")
    if not text:
        raise ActionError("I need a file name or path.")
    expanded = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0].casefold() in COMMON_FOLDER_NAMES:
        return COMMON_FOLDER_NAMES[parts[0].casefold()].joinpath(*parts[1:])
    return BASE / candidate


def read_file(target: str, max_bytes: int = 200_000) -> str:
    path = resolve_path(target)
    if not path.is_file():
        raise ActionError(f"{path.name} is a folder, not a file.")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ActionError(f"I couldn't read {path.name}: {error}") from error
    if b"\x00" in data[:4096]:
        raise ActionError(f"{path.name} looks like a binary file, so I won't read it.")
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    header = f"{path}\n" + "-" * 40 + "\n"
    if truncated:
        header += f"(showing the first {max_bytes:,} bytes)\n\n"
    return header + text


def write_file(target: str, content: str, append: bool = False) -> str:
    path = resolve_write_path(target)
    text = str(content if content is not None else "")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except OSError as error:
        raise ActionError(f"I couldn't write {path}: {error}") from error
    action = "Added to" if append else "Wrote"
    return f"{action} {path} ({len(text.encode('utf-8')):,} bytes)."


def _resolve_directory(target: str) -> Path:
    text = str(target or "").strip().strip("\"'")
    if not text:
        return HOME
    key = text.casefold()
    if key in COMMON_FOLDER_NAMES:
        return COMMON_FOLDER_NAMES[key]
    path = resolve_path(text)
    if not path.is_dir():
        raise ActionError(f"{path.name} is a file, not a folder.")
    return path


def list_directory(target: str = "", limit: int = 80) -> str:
    path = _resolve_directory(target)
    limit = max(1, min(300, int(limit or 80)))
    try:
        entries = list(path.iterdir())
    except OSError as error:
        raise ActionError(f"I couldn't list {path}: {error}") from error
    entries.sort(key=lambda item: (not item.is_dir(), item.name.casefold()))
    lines = [f"Contents of {path}:"]
    for entry in entries[:limit]:
        try:
            if entry.is_dir():
                lines.append(f"- {entry.name}\\  (folder)")
            else:
                lines.append(f"- {entry.name}  ({_format_size(entry.stat().st_size)})")
        except OSError:
            lines.append(f"- {entry.name}")
    if len(entries) > limit:
        lines.append(f"…and {len(entries) - limit} more.")
    if not entries:
        lines.append("- (empty folder)")
    return "\n".join(lines)


def find_files(query: str, limit: int = 25) -> str:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        raise ActionError("What file name should I look for?")
    limit = max(1, min(100, int(limit or 25)))
    needle = text.casefold().replace(" ", "")
    has_wildcard = any(character in text for character in "*?")
    import fnmatch

    matches: list[Path] = []
    deadline = time.monotonic() + 4.0
    for base in _common_dirs():
        if time.monotonic() > deadline:
            break
        try:
            for root, dirs, files in os.walk(base):
                if time.monotonic() > deadline:
                    break
                relative = (
                    Path(root).relative_to(base) if root != str(base) else Path()
                )
                if len(relative.parts) >= 4:
                    dirs[:] = []
                dirs[:] = [
                    name
                    for name in dirs
                    if name not in SKIP_DIRS and not name.startswith((".", "$"))
                ]
                for name in files + dirs:
                    folded = name.casefold()
                    hit = (
                        fnmatch.fnmatch(folded, text.casefold())
                        if has_wildcard
                        else needle in folded.replace(" ", "")
                    )
                    if hit:
                        matches.append(Path(root) / name)
                        if len(matches) >= limit:
                            break
                if len(matches) >= limit:
                    break
        except (OSError, ValueError):
            continue
        if len(matches) >= limit:
            break
    if not matches:
        return f"I couldn't find any file matching {text}."
    matches.sort(key=lambda item: (item.is_dir(), len(item.parts), len(item.name)))
    lines = [f"Files matching {text}:"]
    for path in matches:
        try:
            suffix = "  (folder)" if path.is_dir() else f"  ({_format_size(path.stat().st_size)})"
        except OSError:
            suffix = ""
        lines.append(f"- {path}{suffix}")
    return "\n".join(lines)


def _start_menu_shortcuts():
    roots = [
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
        Path(os.environ.get("PROGRAMDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*.lnk"):
                yield path
        except OSError:
            continue


def launch_app(name: str) -> str:
    _require_windows()
    text = " ".join(str(name or "").split()).strip()
    if not text:
        raise ActionError("Which app should I open?")
    key = text.casefold()

    if key in ("browser", "web browser", "default browser"):
        webbrowser.open(_DEFAULT_BROWSER_URL)
        return "your browser"

    if key in SHELL_URI_APPS:
        _startfile(SHELL_URI_APPS[key])
        return text

    candidates = APP_ALIASES.get(key, [])
    if not candidates and re.fullmatch(r"[\w .-]+\.exe", text, re.IGNORECASE):
        candidates = [text]
    for exe in candidates:
        found = shutil.which(exe)
        if found:
            subprocess.Popen([found], close_fds=True)
            return text

    shortcuts = list(_start_menu_shortcuts())
    tokens = [token for token in re.split(r"\W+", key) if token]
    matches = []
    for shortcut in shortcuts:
        shortcut_name = shortcut.stem.casefold()
        if key == shortcut_name:
            matches.insert(0, shortcut)
        elif tokens and all(token in shortcut_name for token in tokens):
            matches.append(shortcut)
    if matches:
        _startfile(str(matches[0]))
        return text

    if key in APP_ALIASES:
        # Last resort for aliases that only exist as shell apps.
        for shortcut in shortcuts:
            if key in shortcut.stem.casefold():
                _startfile(str(shortcut))
                return text

    try:
        _startfile(text)
        return text
    except OSError as error:
        raise ActionError(f"I couldn't open {text}.") from error


def open_any(target: str, kind: str = "open") -> str:
    text = str(target or "").strip().strip("\"'")
    if not text:
        raise ActionError("What should I open?")
    if kind == "app":
        return launch_app(text)
    if kind == "file":
        return open_path(text)
    if looks_like_url(text):
        return open_url(text)
    try:
        return open_path(text)
    except ActionError:
        return launch_app(text)


def _visible_windows() -> list[str]:
    if os.name != "nt":
        return []
    titles = []
    EnumWindows = ctypes.windll.user32.EnumWindows
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
                if title:
                    titles.append(title)
        return True

    EnumWindows(CALLBACK(callback), 0)
    return titles


def list_windows() -> str:
    titles = _visible_windows()
    if not titles:
        raise ActionError("I couldn't see any open windows.")
    return "Open windows:\n" + "\n".join(f"- {title}" for title in titles[:25])


def activate_window(title: str) -> str:
    _require_windows()
    query = str(title or "").strip().casefold()
    if not query:
        raise ActionError("Which window should I switch to?")
    try:
        import win32gui

        matches = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd)
                if text and query in text.casefold():
                    matches.append((hwnd, text))
            return True

        win32gui.EnumWindows(callback, None)
        if not matches:
            raise ActionError(f"I couldn't find a window called {title}.")
        hwnd, text = matches[0]
        win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)
        return text
    except ImportError:
        pass

    for window_title in _visible_windows():
        if query in window_title.casefold():
            raise ActionError(
                "I found the window but couldn't bring it forward. Please click it once."
            )
    raise ActionError(f"I couldn't find a window called {title}.")


def close_app(name: str) -> str:
    _require_windows()
    key = str(name or "").strip().casefold()
    if not key:
        raise ActionError("Which app should I close?")
    exe = None
    for candidate in APP_ALIASES.get(key, []):
        if candidate.lower().endswith(".exe"):
            exe = candidate
            break
    if exe:
        result = subprocess.run(
            ["taskkill", "/IM", exe, "/F"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return name
        raise ActionError(f"I couldn't close {name}. It may not be running.")

    try:
        import win32con
        import win32gui

        matches = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd)
                if text and key in text.casefold():
                    matches.append(hwnd)
            return True

        win32gui.EnumWindows(callback, None)
        if not matches:
            raise ActionError(f"I couldn't find an open window called {name}.")
        win32gui.PostMessage(matches[0], win32con.WM_CLOSE, 0, 0)
        return name
    except ImportError:
        raise ActionError("I couldn't close that app.")


def _press_key(vk: int, times: int = 1):
    _require_windows()
    KEYEVENTF_KEYUP = 0x0002
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


def _screenshot_path() -> Path:
    directory = HOME / "Pictures" / "Jarvis Screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return directory / f"jarvis-{stamp}.png"


def system_action(action: str, target: str = "") -> str:
    _require_windows()
    name = str(action or "").strip().lower()
    target = str(target or "").strip()

    if name in ("volume_up", "volume down", "turn_volume_up"):
        _press_key(0xAF, 5)
        return "Turned the volume up."
    if name in ("volume_down", "turn_volume_down"):
        _press_key(0xAE, 5)
        return "Turned the volume down."
    if name in ("mute", "toggle_mute"):
        _press_key(0xAD)
        return "Toggled the system mute."
    if name == "lock":
        ctypes.windll.user32.LockWorkStation()
        return "Locked the laptop."
    if name == "screenshot":
        try:
            from PIL import ImageGrab

            path = _screenshot_path()
            ImageGrab.grab(all_screens=True).save(path)
            return f"Saved a screenshot to {path}."
        except Exception as error:
            raise ActionError(f"I couldn't take a screenshot: {error}") from error
    if name == "sleep":
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            check=False,
        )
        return "Putting the laptop to sleep."
    if name == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "10"], check=False)
        return "Shutting down in 10 seconds. Say cancel shutdown to stop it."
    if name == "restart":
        subprocess.run(["shutdown", "/r", "/t", "10"], check=False)
        return "Restarting in 10 seconds. Say cancel shutdown to stop it."
    if name in ("cancel_shutdown", "abort_shutdown"):
        subprocess.run(["shutdown", "/a"], check=False)
        return "Cancelled the shutdown."
    if name in ("minimize_all", "show_desktop"):
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x44, 0, 0x0002, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, 0x0002, 0)
        return "Minimised all windows."
    if name == "open_settings":
        _startfile("ms-settings:")
        return "Opened Windows Settings."
    if name == "list_windows":
        return list_windows()
    if name in ("activate", "switch_window"):
        return f"Switched to {activate_window(target)}."
    if name == "close_app":
        return f"Closed {close_app(target)}."
    raise ActionError(f"I don't know the system action {name}.")


def run_powershell(command: str, timeout: int = 60) -> dict:
    _require_windows()
    text = str(command or "").strip()
    if not text:
        raise ActionError("I need a command to run.")
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                text,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ActionError(
            f"That command took longer than {timeout} seconds, so I stopped it."
        ) from error
    return {
        "command": text,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def format_shell_result(result: dict, limit: int = 4000) -> str:
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    text = stdout or stderr or ""
    if len(text) > limit:
        text = text[: limit - 1].rsplit("\n", 1)[0] + "\n... (output truncated)"
    if not text:
        text = "Done."
    if result.get("returncode", 0) != 0:
        text = f"Command exited with code {result['returncode']}.\n{text}"
    return text
