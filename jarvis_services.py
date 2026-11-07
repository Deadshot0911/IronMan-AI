"""Account-level services for Jarvis: Gmail, Google Calendar, and WhatsApp.

Google libraries and network clients are imported lazily so Jarvis still starts
when an optional integration is not configured yet.
"""

from __future__ import annotations

import imaplib
import json
import os
import re
import smtplib
import ssl
import webbrowser
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote

from jarvis_pc import ActionError

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    # Load the repo .env even when this module is imported before jarvis_core.
    load_dotenv(BASE / ".env")
except Exception:
    pass

CONTACTS_FILE = Path(
    os.environ.get("JARVIS_CONTACTS_FILE", str(BASE / "jarvis_contacts.json"))
)
GOOGLE_TOKEN_FILE = Path(
    os.environ.get("JARVIS_GOOGLE_TOKEN", str(BASE / "jarvis_google_token.json"))
)
GOOGLE_CREDENTIALS_FILE = Path(
    os.environ.get(
        "JARVIS_GOOGLE_CREDENTIALS", str(BASE / "jarvis_google_credentials.json")
    )
)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
def load_contacts(path: Path | str | None = None) -> dict:
    target = Path(path) if path is not None else CONTACTS_FILE
    try:
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key).casefold(): value for key, value in data.items()}


def _contact_record(name: str) -> dict:
    record = load_contacts().get(str(name or "").strip().casefold())
    if isinstance(record, str):
        return {"email": record} if "@" in record else {"phone": record}
    return record if isinstance(record, dict) else {}


def resolve_email(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ActionError("Who should I send the email to?")
    if text.casefold() in {"me", "myself", "my self"}:
        settings = smtp_settings()
        address = str(settings.get("sender") or settings.get("user") or "").strip()
        if address and EMAIL_RE.match(address):
            return address
        raise ActionError(
            "I don't know your email address yet. Set JARVIS_EMAIL_FROM in .env."
        )
    if "@" in text:
        if not EMAIL_RE.match(text):
            raise ActionError(f"{text} doesn't look like a valid email address.")
        return text
    record = _contact_record(text)
    address = str(record.get("email", "")).strip()
    if address and EMAIL_RE.match(address):
        return address
    raise ActionError(
        f"I don't have an email address for {text}. Add it to jarvis_contacts.json "
        "or give me the full address."
    )


def resolve_phone(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ActionError("Who should I send the WhatsApp message to?")
    if re.fullmatch(r"[+\d][\d\s().-]{5,}", text):
        return text
    record = _contact_record(text)
    phone = str(record.get("phone", "")).strip()
    if phone:
        return phone
    raise ActionError(
        f"I don't have a phone number for {text}. Add it to jarvis_contacts.json "
        "or give me the number with its country code."
    )


# ---------------------------------------------------------------------------
# Gmail / SMTP
# ---------------------------------------------------------------------------
def smtp_settings() -> dict:
    user = os.environ.get("JARVIS_SMTP_USER", "").strip()
    password = os.environ.get("JARVIS_SMTP_PASSWORD", "").strip()
    sender = os.environ.get("JARVIS_EMAIL_FROM", user).strip()
    host = os.environ.get("JARVIS_SMTP_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("JARVIS_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    use_ssl = os.environ.get("JARVIS_SMTP_USE_SSL", "").strip() in ("1", "true", "yes")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender or user,
        "use_ssl": use_ssl,
    }


def email_configured() -> bool:
    settings = smtp_settings()
    return bool(settings["user"] and settings["password"] and settings["sender"])


def build_email_draft(to: str, subject: str, body: str) -> dict:
    recipients = [
        resolve_email(part.strip()) for part in str(to or "").split(",") if part.strip()
    ]
    if not recipients:
        raise ActionError("Who should I send the email to?")
    text = str(body or "").strip()
    if not text:
        raise ActionError("What should the email say?")
    subject_text = str(subject or "").strip() or "Message from Jarvis"
    return {
        "kind": "email",
        "to": ", ".join(recipients),
        "display_to": str(to or "").strip(),
        "subject": subject_text,
        "body": text,
    }


def send_email(draft: dict) -> str:
    settings = smtp_settings()
    if not email_configured():
        raise ActionError(
            "Gmail isn't configured yet. Add JARVIS_SMTP_USER and "
            "JARVIS_SMTP_PASSWORD to .env. Use a Gmail App Password, not your "
            "normal Google password. See INTEGRATIONS.md."
        )
    message = EmailMessage()
    message["From"] = settings["sender"]
    message["To"] = draft["to"]
    message["Subject"] = draft["subject"]
    message.set_content(draft["body"])

    try:
        if settings["use_ssl"]:
            with smtplib.SMTP_SSL(
                settings["host"],
                settings["port"],
                timeout=25,
                context=ssl.create_default_context(),
            ) as server:
                server.login(settings["user"], settings["password"])
                server.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], settings["port"], timeout=25) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(settings["user"], settings["password"])
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as error:
        raise ActionError(
            "Gmail rejected the login. Create a Gmail App Password and put it in "
            "JARVIS_SMTP_PASSWORD, then restart Jarvis."
        ) from error
    except (OSError, smtplib.SMTPException) as error:
        raise ActionError(f"I couldn't send the email: {error}") from error
    return draft["to"]


def open_email() -> str:
    webbrowser.open("https://mail.google.com/mail/u/0/#inbox")
    return "Gmail"


def imap_settings() -> dict:
    settings = smtp_settings()
    return {
        **settings,
        "host": os.environ.get("JARVIS_IMAP_HOST", "imap.gmail.com").strip(),
        "port": int(os.environ.get("JARVIS_IMAP_PORT", "993") or 993),
    }


def _shorten(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def read_unread_email(limit: int = 5) -> list[dict]:
    """Read unread Gmail headers and snippets without marking them as read."""
    limit = max(1, min(15, int(limit or 5)))
    if not email_configured():
        raise ActionError(
            "Gmail isn't configured yet. Add JARVIS_SMTP_USER and "
            "JARVIS_SMTP_PASSWORD to .env. Use a Gmail App Password, not your "
            "normal Google password. See INTEGRATIONS.md."
        )
    settings = imap_settings()
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(
            settings["host"], int(settings["port"]), timeout=25
        )
        mail.login(settings["user"], settings["password"])
        # Read-only means searching and peeking never changes the Seen flag.
        status, _data = mail.select("INBOX", readonly=True)
        if status != "OK":
            raise ActionError("I couldn't open the Gmail inbox over IMAP.")
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            raise ActionError("I couldn't search the Gmail inbox over IMAP.")
        ids = list((data[0] or b"").split())
        emails = []
        for sequence in reversed(ids[-limit:]):
            try:
                status, fetched = mail.fetch(
                    sequence, "(BODY.PEEK[])"
                )
                if status != "OK" or not fetched:
                    continue
                raw = b""
                for part in fetched:
                    if isinstance(part, tuple) and len(part) > 1:
                        raw = part[1]
                        break
                if not raw:
                    continue
                message = BytesParser(policy=policy.default).parsebytes(raw)
                sender = str(message.get("From", "(unknown sender)"))
                subject = str(message.get("Subject", "(no subject)"))
                date = str(message.get("Date", ""))
                body = message.get_body(preferencelist=("plain",))
                snippet = ""
                if body is not None:
                    try:
                        snippet = _shorten(body.get_content(), 220)
                    except Exception:
                        snippet = ""
                emails.append(
                    {
                        "from": sender,
                        "subject": subject,
                        "date": date,
                        "snippet": snippet,
                    }
                )
            except Exception:
                continue
    except imaplib.IMAP4.error as error:
        raise ActionError(
            "Gmail rejected the IMAP login. In Gmail settings, enable IMAP "
            "(Settings → Forwarding and POP/IMAP) and use a Gmail App Password."
        ) from error
    except (OSError, ValueError) as error:
        raise ActionError(f"I couldn't read Gmail: {error}") from error
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
    return emails


def format_unread_email(emails: list[dict]) -> str:
    if not emails:
        return "You have no unread email in your Gmail inbox."
    lines = [
        f"Here are {len(emails)} unread email{'s' if len(emails) != 1 else ''} "
        "from your Gmail inbox (newest first):"
    ]
    for email in emails:
        line = f"- From {email.get('from', 'unknown')}: {email.get('subject', '(no subject)')}"
        if email.get("snippet"):
            line += f" — {_shorten(email['snippet'], 180)}"
        lines.append(line)
    lines.append("Which one should I open, read in full, or reply to?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WhatsApp Desktop
# ---------------------------------------------------------------------------
def build_whatsapp_draft(to: str, message: str) -> dict:
    phone = resolve_phone(to)
    text = str(message or "").strip()
    if not text:
        raise ActionError("What should the WhatsApp message say?")
    return {
        "kind": "whatsapp",
        "to": str(to or "").strip(),
        "phone": phone,
        "message": text,
    }


def build_whatsapp_chat_draft(chat: str, message: str) -> dict:
    """Draft a reply by WhatsApp chat name (no phone number needed)."""
    name = str(chat or "").strip()
    if not name:
        raise ActionError("Which WhatsApp chat should I reply to?")
    text = str(message or "").strip()
    if not text:
        raise ActionError("What should the WhatsApp reply say?")
    return {
        "kind": "whatsapp",
        "to": name,
        "chat": name,
        "phone": "",
        "message": text,
    }


def open_whatsapp_chat(chat: str, message: str) -> str:
    """Open a Desktop chat and type the reply without pressing Send."""
    import jarvis_whatsapp

    return jarvis_whatsapp.prefill_message(chat, message)


def open_whatsapp(to: str, message: str, phone: str | None = None) -> str:
    number = phone or resolve_phone(to)
    digits = re.sub(r"\D", "", number)
    if len(digits) < 7:
        raise ActionError("That WhatsApp number doesn't look complete.")
    text = str(message or "").strip()
    uri = f"whatsapp://send?phone={digits}&text={quote(text)}"
    try:
        starter = getattr(os, "startfile", None)
        if starter is None:
            raise OSError("WhatsApp Desktop launching is Windows-only.")
        starter(uri)
    except OSError:
        webbrowser.open(f"https://wa.me/{digits}?text={quote(text)}")
        return (
            f"I opened WhatsApp Web for {to} with the message ready. "
            "Press Send to deliver it."
        )
    return (
        f"I opened the WhatsApp chat for {to} with the message ready. "
        "Press Send in WhatsApp to deliver it."
    )


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------
def _calendar_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as error:
        raise ActionError(
            "Google Calendar support needs google-api-python-client and "
            "google-auth-oauthlib. Run pip install -r requirements.txt."
        ) from error

    credentials = None
    if GOOGLE_TOKEN_FILE.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES
            )
        except (OSError, ValueError):
            credentials = None
    if credentials and not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            credentials = None
    if credentials is None:
        if not GOOGLE_CREDENTIALS_FILE.exists():
            raise ActionError(
                "Google Calendar isn't set up. Download a Desktop OAuth client "
                "JSON from Google Cloud and save it as "
                "jarvis_google_credentials.json. See INTEGRATIONS.md."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
        )
        credentials = flow.run_local_server(
            port=0, open_browser=True, prompt="consent"
        )
        GOOGLE_TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def parse_datetime(value: str, default: datetime | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        if default is None:
            raise ActionError("I need a date and time for that.")
        return default
    text = text.replace("Z", "+00:00")

    parsed = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None

    if parsed is None:
        lowered = text.casefold()
        day = datetime.now().astimezone()
        if "tomorrow" in lowered:
            day += timedelta(days=1)
        elif "today" in lowered or "tonight" in lowered:
            pass
        else:
            raise ActionError(
                f"I couldn't understand the date {text}. Use something like "
                "2026-11-07T15:00:00."
            )
        clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
        hour = 9
        minute = 0
        if clock:
            hour = int(clock.group(1))
            minute = int(clock.group(2) or 0)
            suffix = clock.group(3)
            if suffix == "pm" and hour < 12:
                hour += 12
            if suffix == "am" and hour == 12:
                hour = 0
        parsed = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _format_event(event: dict) -> str:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    when = raw
    try:
        if "T" in raw:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime(
                "%a %d %b, %I:%M %p"
            )
        elif raw:
            when = datetime.fromisoformat(raw).strftime("%a %d %b (all day)")
    except ValueError:
        pass
    title = event.get("summary") or "(no title)"
    location = event.get("location") or ""
    suffix = f" at {location}" if location else ""
    return f"- {when}: {title}{suffix}"


def list_events(days: int = 7, max_results: int = 25) -> str:
    service = _calendar_service()
    now = datetime.now().astimezone()
    end = now + timedelta(days=max(1, int(days or 1)))
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max(1, min(50, int(max_results or 25))),
        )
        .execute()
    )
    events = result.get("items", [])
    if not events:
        return f"You have no events in the next {days} day{'s' if days != 1 else ''}."
    heading = (
        f"Here's your calendar for the next {days} day{'s' if days != 1 else ''}:"
    )
    return heading + "\n" + "\n".join(_format_event(event) for event in events)


def create_event(
    title: str,
    start: str,
    end: str = "",
    description: str = "",
    location: str = "",
) -> str:
    summary = str(title or "").strip()
    if not summary:
        raise ActionError("What should I call the event?")
    service = _calendar_service()
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end, default=start_dt + timedelta(hours=1))
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)
    body = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    if description:
        body["description"] = str(description)
    if location:
        body["location"] = str(location)
    created = service.events().insert(calendarId="primary", body=body).execute()
    when = start_dt.strftime("%a %d %b at %I:%M %p")
    link = created.get("htmlLink", "")
    message = f"Added {summary} to your calendar for {when}."
    if link:
        message += f" {link}"
    return message


def open_calendar() -> str:
    webbrowser.open("https://calendar.google.com/calendar/u/0/r")
    return "Google Calendar"
