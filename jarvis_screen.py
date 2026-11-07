"""Screen vision and controlled screen actions for Jarvis.

The screen is captured locally, described by Gemini, and never uploaded to any
other service. A screen action plan is always shown in the Jarvis window and
must be confirmed before pyautogui presses a key or moves the mouse.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import tempfile
import time
from pathlib import Path

from jarvis_pc import ActionError

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
except Exception:
    pass

DEFAULT_VISION_MODELS = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
)
MAX_STEPS = 20
_DPI_READY = False

PLANNER_PROMPT = """You are controlling a Windows desktop through mouse and keyboard.
The attached image is the current screen, {width} by {height} pixels.

User instruction: {instruction}

Return ONLY one JSON object with this shape:
{{"summary":"one short sentence describing the plan","answer":"","actions":[]}}

Allowed actions:
{{"type":"click","x":500,"y":300,"button":"left","clicks":1,"description":"click the Send button"}}
{{"type":"double_click","x":500,"y":300,"description":"..."}}
{{"type":"right_click","x":500,"y":300,"description":"..."}}
{{"type":"move","x":500,"y":300,"description":"..."}}
{{"type":"drag","x":500,"y":300,"x2":700,"y2":500,"description":"..."}}
{{"type":"type","x":500,"y":300,"text":"text to type","description":"..."}}
{{"type":"press","key":"enter","description":"..."}}
{{"type":"hotkey","keys":["ctrl","s"],"description":"..."}}
{{"type":"scroll","amount":-500,"x":900,"y":500,"description":"..."}}
{{"type":"wait","seconds":0.5,"description":"..."}}

Rules:
- x and y are integers from 0 to 1000 relative to the image (0 is left/top,
  1000 is right/bottom). x2 and y2 follow the same rule.
- Use only controls that are clearly visible in the screenshot.
- Click a text field before typing into it.
- Never press Enter or click Send unless the instruction explicitly asks to send.
- Never delete data, buy something, change passwords, or alter security settings
  unless the instruction explicitly asks for it.
- Use at most 10 actions. Prefer a short, reliable plan.
- If the instruction is unclear or cannot be completed from this screenshot,
  return an empty actions list and put a short question or explanation in
  "answer".
"""


def enable_dpi_awareness() -> None:
    """Make pyautogui and screenshot coordinates agree on scaled displays."""
    global _DPI_READY
    if _DPI_READY or os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _DPI_READY = True


def _screenshot_path() -> Path:
    directory = Path.home() / "Pictures" / "Jarvis Screenshots"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(tempfile.gettempdir()) / "Jarvis Screenshots"
        directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    counter = 0
    while True:
        suffix = f"-{counter}" if counter else ""
        candidate = directory / f"jarvis-screen-{stamp}{suffix}.png"
        if not candidate.exists():
            return candidate
        counter += 1


def capture_screen(region: tuple[int, int, int, int] | None = None) -> Path:
    """Capture the primary screen (or a region) and return the PNG path."""
    enable_dpi_awareness()
    try:
        from PIL import ImageGrab
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Screen capture needs Pillow. Run pip install -r requirements.txt."
        ) from error
    path = _screenshot_path()
    try:
        if region is None:
            image = ImageGrab.grab()
        else:
            left, top, right, bottom = (int(value) for value in region)
            if right - left < 8 or bottom - top < 8:
                raise ActionError("That screen area is too small to capture.")
            image = ImageGrab.grab(bbox=(left, top, right, bottom))
        image.save(path)
    except ActionError:
        raise
    except Exception as error:
        raise ActionError(f"I couldn't capture the screen: {error}") from error
    return path


def _client():
    try:
        from google import genai
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Screen vision needs google-genai. Run pip install -r requirements.txt."
        ) from error
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ActionError(
            "I need GEMINI_API_KEY in .env before I can see your screen."
        )
    return genai.Client(api_key=api_key)


def _vision_models() -> list[str]:
    override = os.environ.get("JARVIS_VISION_MODEL", "").strip()
    if override:
        models = [part.strip() for part in override.split(",") if part.strip()]
        if models:
            return models
    return list(DEFAULT_VISION_MODELS)


def _image_size(image: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(image) as opened:
            return opened.size
    except Exception:
        return (1920, 1080)


def analyze_image(image: Path | str, question: str, model: str | None = None) -> str:
    """Ask Gemini about a local image. Tries several flash models in order."""
    path = Path(image)
    if not path.exists():
        raise ActionError("That screenshot no longer exists.")
    try:
        from google.genai import types
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Screen vision needs google-genai. Run pip install -r requirements.txt."
        ) from error

    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    client = _client()
    prompt = str(question or "").strip() or "Describe what is on this screen."
    errors = []
    models = [model] if model else _vision_models()
    for candidate in models:
        try:
            response = client.models.generate_content(
                model=candidate,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime),
                    prompt,
                ],
            )
            text = (getattr(response, "text", "") or "").strip()
            if text:
                return text
            errors.append(f"{candidate}: empty response")
        except Exception as error:
            errors.append(f"{candidate}: {str(error)[:180]}")
    raise ActionError(
        "I couldn't analyse the screen. " + " | ".join(errors[-3:])
    )


def look(question: str = "What is on my screen right now?") -> str:
    """Capture the screen and answer a question about it."""
    path = capture_screen()
    return analyze_image(path, question)


def _parse_json_object(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, list):
            return {"summary": "", "answer": "", "actions": parsed}
        if isinstance(parsed, dict):
            return parsed
    raise ActionError("I couldn't understand the screen plan. Please ask again.")


def _number(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ActionError(f"The screen plan has an invalid {label}.")
    if number != number or number in (float("inf"), float("-inf")):
        raise ActionError(f"The screen plan has an invalid {label}.")
    return number


def _scaled(value, width: int, height: int, axis: str) -> int:
    number = _number(value, f"{axis} coordinate")
    if not 0 <= number <= 1000:
        raise ActionError(
            f"The screen plan's {axis} coordinate is outside the screen."
        )
    extent = width if axis == "x" else height
    return max(0, min(extent - 1, round(number / 1000 * extent)))


def _optional_scaled(raw: dict, width: int, height: int) -> tuple[int, int] | None:
    if "x" not in raw and "y" not in raw:
        return None
    if "x" not in raw or "y" not in raw:
        raise ActionError("A screen action needs both an x and a y coordinate.")
    return _scaled(raw["x"], width, height, "x"), _scaled(
        raw["y"], width, height, "y"
    )


def normalize_plan(plan: dict, width: int = 1920, height: int = 1080) -> dict:
    """Validate a model plan and convert 0..1000 coordinates to pixels."""
    width = max(1, int(width))
    height = max(1, int(height))
    if not isinstance(plan, dict):
        raise ActionError("That screen plan isn't valid.")
    raw_actions = plan.get("actions")
    if raw_actions is None:
        raw_actions = []
    if not isinstance(raw_actions, list):
        raise ActionError("That screen plan isn't a list of actions.")
    if len(raw_actions) > MAX_STEPS:
        raise ActionError(
            f"That screen plan has too many steps (limit {MAX_STEPS})."
        )

    actions = []
    for raw in raw_actions:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).strip().lower().replace(" ", "_")
        description = str(raw.get("description", "")).strip()[:240]
        action = {"type": kind, "description": description}

        if kind in ("click", "double_click", "right_click", "move"):
            point = _optional_scaled(raw, width, height)
            if point is None:
                raise ActionError("A screen click is missing its coordinates.")
            action["x"], action["y"] = point
            if kind == "click":
                button = str(raw.get("button", "left")).lower()
                action["button"] = (
                    button if button in ("left", "right", "middle") else "left"
                )
                try:
                    clicks = int(raw.get("clicks", 1))
                except (TypeError, ValueError):
                    clicks = 1
                action["clicks"] = max(1, min(3, clicks))
        elif kind == "drag":
            start = _optional_scaled(raw, width, height)
            if start is None or "x2" not in raw or "y2" not in raw:
                raise ActionError("A screen drag needs start and end coordinates.")
            action["x"], action["y"] = start
            action["x2"] = _scaled(raw["x2"], width, height, "x")
            action["y2"] = _scaled(raw["y2"], width, height, "y")
            try:
                action["duration"] = max(
                    0.1, min(3.0, float(raw.get("duration", 0.5)))
                )
            except (TypeError, ValueError):
                action["duration"] = 0.5
        elif kind == "type":
            text = str(raw.get("text", ""))
            if not text:
                raise ActionError("A screen typing action had no text.")
            action["text"] = text[:4000]
            point = _optional_scaled(raw, width, height)
            if point is not None:
                action["x"], action["y"] = point
        elif kind == "press":
            key = str(raw.get("key", "")).strip()
            if not key:
                raise ActionError("A screen key press had no key.")
            action["key"] = key[:40]
        elif kind == "hotkey":
            keys = raw.get("keys")
            if isinstance(keys, str):
                keys = [part for part in re.split(r"\s*\+\s*", keys) if part]
            if not isinstance(keys, list) or not keys:
                raise ActionError("A screen hotkey had no keys.")
            action["keys"] = [str(key)[:40] for key in keys[:4]]
        elif kind == "scroll":
            try:
                amount = int(raw.get("amount", -500))
            except (TypeError, ValueError):
                amount = -500
            action["amount"] = max(-3000, min(3000, amount))
            point = _optional_scaled(raw, width, height)
            if point is not None:
                action["x"], action["y"] = point
        elif kind == "wait":
            try:
                seconds = float(raw.get("seconds", 0.5))
            except (TypeError, ValueError):
                seconds = 0.5
            action["seconds"] = max(0.1, min(5.0, seconds))
        else:
            raise ActionError(f"I don't support the screen action {kind!r}.")
        actions.append(action)

    return {
        "summary": str(plan.get("summary", "")).strip()[:300],
        "answer": str(plan.get("answer", "")).strip()[:1000],
        "actions": actions,
    }


def describe_plan(plan: dict) -> str:
    actions = list((plan or {}).get("actions") or [])
    lines = []
    summary = str((plan or {}).get("summary", "")).strip()
    if summary:
        lines.append(summary)
    for index, action in enumerate(actions, 1):
        description = str(action.get("description", "")).strip()
        kind = action.get("type", "action")
        if not description:
            description = kind.replace("_", " ")
        lines.append(f"{index}. {description}")
    if not lines:
        lines.append("No screen actions were planned.")
    return "\n".join(lines)


def prepare_screen_action(instruction: str) -> dict:
    """Capture the screen, ask Gemini for a plan, and validate it."""
    text = str(instruction or "").strip()
    if not text:
        raise ActionError("What should I do on the screen?")
    path = capture_screen()
    width, height = _image_size(path)
    prompt = PLANNER_PROMPT.format(
        width=width, height=height, instruction=text
    )
    raw = analyze_image(path, prompt)
    plan = normalize_plan(_parse_json_object(raw), width, height)
    if not plan["actions"]:
        raise ActionError(
            plan.get("answer")
            or "I couldn't work out a safe set of screen actions for that."
        )
    plan["screenshot"] = str(path)
    plan["instruction"] = text
    return plan


def execute_plan(plan: dict) -> str:
    """Run a previously confirmed screen plan with pyautogui."""
    actions = list((plan or {}).get("actions") or [])
    if not actions:
        raise ActionError("There are no screen actions to run.")
    try:
        import pyautogui
        import pyperclip
    except Exception as error:  # pragma: no cover - depends on the machine
        raise ActionError(
            "Controlling the screen needs pyautogui and pyperclip. "
            "Run pip install -r requirements.txt."
        ) from error

    enable_dpi_awareness()
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    try:
        for action in actions:
            kind = action.get("type")
            if kind in ("click", "double_click", "right_click", "move"):
                x, y = int(action["x"]), int(action["y"])
                if kind == "move":
                    pyautogui.moveTo(x, y, duration=0.25)
                elif kind == "double_click":
                    pyautogui.doubleClick(x, y, interval=0.08)
                elif kind == "right_click":
                    pyautogui.rightClick(x, y)
                else:
                    pyautogui.click(
                        x,
                        y,
                        clicks=int(action.get("clicks", 1)),
                        interval=0.08,
                        button=action.get("button", "left"),
                    )
            elif kind == "drag":
                pyautogui.moveTo(int(action["x"]), int(action["y"]))
                pyautogui.dragTo(
                    int(action["x2"]),
                    int(action["y2"]),
                    duration=float(action.get("duration", 0.5)),
                    button="left",
                )
            elif kind == "type":
                if "x" in action and "y" in action:
                    pyautogui.click(int(action["x"]), int(action["y"]))
                    time.sleep(0.15)
                pyperclip.copy(str(action.get("text", "")))
                pyautogui.hotkey("ctrl", "v")
            elif kind == "press":
                pyautogui.press(str(action.get("key", "")))
            elif kind == "hotkey":
                pyautogui.hotkey(*list(action.get("keys") or []))
            elif kind == "scroll":
                if "x" in action and "y" in action:
                    pyautogui.scroll(
                        int(action.get("amount", -500)),
                        x=int(action["x"]),
                        y=int(action["y"]),
                    )
                else:
                    pyautogui.scroll(int(action.get("amount", -500)))
            elif kind == "wait":
                time.sleep(float(action.get("seconds", 0.5)))
            time.sleep(0.15)
    except pyautogui.FailSafeException as error:
        raise ActionError(
            "I stopped the screen action because the mouse reached a screen corner."
        ) from error
    except ActionError:
        raise
    except Exception as error:
        raise ActionError(f"I couldn't finish the screen action: {error}") from error

    summary = str((plan or {}).get("summary", "")).strip()
    count = len(actions)
    if summary:
        return f"Done. {summary} ({count} screen action{'s' if count != 1 else ''})."
    return f"Done. I performed {count} screen action{'s' if count != 1 else ''}."
