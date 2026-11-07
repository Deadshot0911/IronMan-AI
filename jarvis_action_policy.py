"""Pure policy helpers for Jarvis laptop-control actions.

This module deliberately has no third-party dependencies so the action rules
can be unit-tested without importing the full voice assistant runtime.
"""

from __future__ import annotations

import re

# Every action in this set touches the user's laptop, accounts, or data and
# therefore needs the signed-in administrator (or a one-off admin PIN).
SENSITIVE_ACTIONS = frozenset(
    {
        "open",
        "search",
        "file",
        "app",
        "shell",
        "system",
        "email",
        "whatsapp",
        "calendar",
        "message",
        "screen",
    }
)

# Actions that create an outbound message are drafted first and only executed
# after the user explicitly approves the draft.
APPROVAL_ACTIONS = frozenset({"whatsapp"})
APPROVAL_EMAIL_MODES = frozenset({"send"})

# System actions that change power state or take the machine away.
DESTRUCTIVE_SYSTEM_ACTIONS = frozenset({"shutdown", "restart", "sleep"})

_DESTRUCTIVE_SHELL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bformat\b[^\r\n]*\b[a-z]:",
        r"\bdiskpart\b",
        r"\bbcdedit\b",
        r"\b(?:del|erase|rd|rmdir)\b[^\r\n]*(?:/s|/f|/q|\*)",
        r"\bremove-item\b[^\r\n]*-recurse\b",
        r"\b(?:rm|rmdir)\b[^\r\n]*\s-rf?\b",
        r"\breg\s+(?:delete|add)\b",
        r"\b(?:shutdown|stop-computer|restart-computer)\b",
        r"\btakeown\b",
        r"\bicacls\b[^\r\n]*\b(?:reset|grant)\b",
        r"\bcipher\b[^\r\n]*\b/w\b",
        r"\bnet\s+(?:user|localgroup)\b[^\r\n]*\b(?:add|delete)\b",
        r"\bwmic\b[^\r\n]*\bdelete\b",
        r"\bmkfs\b",
        r"\bdd\b[^\r\n]*\bof=/dev/",
        r":\(\)\s*\{\s*:\|:&\s*\};:",
    )
)

_APPROVAL_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|send|send it|send now|approve|approved|"
    r"confirm|confirmed|go ahead|do it|proceed|fire away|execute|run it|"
    r"do that)$",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"^(?:no|nope|nah|cancel|stop|abort|don'?t|do not|forget it|never ?mind|"
    r"leave it|not now)$",
    re.IGNORECASE,
)
_DANGER_RE = re.compile(
    r"^(?:confirm dangerous|yes confirm|i understand|yes i understand|"
    r"confirm the risk|do it anyway|proceed anyway)$",
    re.IGNORECASE,
)


def _text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[^\w\s']", "", str(value).casefold()).strip()


def is_sensitive(action: dict) -> bool:
    return isinstance(action, dict) and action.get("do") in SENSITIVE_ACTIONS


def requires_approval(action: dict) -> bool:
    if not isinstance(action, dict):
        return False
    name = action.get("do")
    if name in APPROVAL_ACTIONS:
        return True
    if name == "email" and str(action.get("action", "")).lower() in APPROVAL_EMAIL_MODES:
        return True
    if name == "message":
        app = str(action.get("app", "whatsapp")).lower()
        mode = str(action.get("action", "read")).lower()
        if app == "whatsapp" and mode in ("reply", "send"):
            return True
        if app in ("gmail", "email") and mode in ("reply", "send"):
            return True
    return False


def requires_screen_confirmation(action: dict) -> bool:
    """Screen actions are planned first and confirmed in the Jarvis window."""
    if not isinstance(action, dict) or action.get("do") != "screen":
        return False
    return str(action.get("action", "look")).lower() in ("act", "action", "do")


def shell_command_is_destructive(command: str) -> bool:
    text = str(command or "")
    return any(pattern.search(text) for pattern in _DESTRUCTIVE_SHELL_PATTERNS)


def is_destructive(action: dict) -> bool:
    if not isinstance(action, dict):
        return False
    name = action.get("do")
    if name == "shell":
        return shell_command_is_destructive(action.get("command", ""))
    if name == "system":
        return str(action.get("action", "")).lower() in DESTRUCTIVE_SYSTEM_ACTIONS
    return False


def describe_action(action: dict) -> str:
    if not isinstance(action, dict):
        return "do something on this laptop"
    name = action.get("do")
    if name == "open":
        return f"open {action.get('target', 'that')}"
    if name == "search":
        return f"search for {action.get('query', 'that')}"
    if name == "file":
        mode = str(action.get("action", "open")).lower()
        target = action.get("target") or action.get("path") or "you asked for"
        if mode == "read":
            return f"read the file {target}"
        if mode in ("write", "append"):
            return f"write to the file {target}"
        if mode == "list":
            return f"list the files in {target}"
        if mode == "find":
            return f"find files named {action.get('query', target)}"
        return f"open the file {target}"
    if name == "app":
        return f"open {action.get('name', 'that app')}"
    if name == "shell":
        command = str(action.get("command", "")).strip()
        return f"run the command {command[:80]}" if command else "run a shell command"
    if name == "system":
        target = str(action.get("target", "")).strip()
        return f"control the laptop ({action.get('action', 'system')}{': ' + target if target else ''})"
    if name == "email":
        mode = str(action.get("action", "send")).lower()
        if mode == "open":
            return "open your email"
        if mode == "draft":
            return f"draft an email to {action.get('to', 'someone')}"
        return f"send an email to {action.get('to', 'someone')}"
    if name == "whatsapp":
        return f"send a WhatsApp message to {action.get('to', 'someone')}"
    if name == "calendar":
        mode = str(action.get("action", "list")).lower()
        if mode == "create":
            return f"add {action.get('title', 'an event')} to your calendar"
        if mode == "open":
            return "open your calendar"
        return "read your calendar"
    if name == "message":
        app = "WhatsApp" if str(action.get("app", "whatsapp")).lower() == "whatsapp" else "Gmail"
        mode = str(action.get("action", "read")).lower()
        if mode in ("reply", "send"):
            return f"reply on {app} to {action.get('to', 'someone')}"
        if mode == "open":
            return f"open the {app} chat with {action.get('to', 'someone')}"
        if mode == "conversation":
            return f"read the {app} conversation with {action.get('to', 'someone')}"
        return f"read your unread {app} messages"
    if name == "screen":
        mode = str(action.get("action", "look")).lower()
        if mode in ("act", "action", "do"):
            return f"act on your screen: {action.get('instruction', 'a screen action')}"
        return "look at your screen"
    return "do something on this laptop"


def is_approval_text(text: str) -> bool:
    return bool(_APPROVAL_RE.fullmatch(_text(text)))


def is_cancel_text(text: str) -> bool:
    return bool(_CANCEL_RE.fullmatch(_text(text)))


def is_danger_confirmation_text(text: str) -> bool:
    return bool(_DANGER_RE.fullmatch(_text(text)))
