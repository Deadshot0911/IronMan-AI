"""Check whether Jarvis integrations are configured.

Run from the repository root:

    .\\.venv\\Scripts\\python.exe check_integrations.py
    .\\.venv\\Scripts\\python.exe check_integrations.py --test-email
    .\\.venv\\Scripts\\python.exe check_integrations.py --test-calendar

This script never sends an email. ``--test-email`` only logs in to SMTP.
``--test-calendar`` may open a browser the first time so Google can grant
Calendar access.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
except Exception:
    pass

import jarvis_services  # noqa: E402  (loads .env itself as a fallback)


def mark(ok: bool) -> str:
    return "[ OK ]" if ok else "[MISS]"


def mask(value: str) -> str:
    text = str(value or "")
    if "@" in text:
        name, _, domain = text.partition("@")
        return (name[:1] + "*" * max(1, len(name) - 1)) + "@" + domain
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 4:
        return "*" * (len(digits) - 4) + digits[-4:]
    return text


def check_gmail(test: bool) -> None:
    settings = jarvis_services.smtp_settings()
    configured = jarvis_services.email_configured()
    print(f"{mark(configured)} Gmail sending")
    print(f"       host: {settings['host']}:{settings['port']}")
    print(f"       user: {settings['user'] or '(not set)'}")
    print(f"       from: {settings['sender'] or '(not set)'}")
    print(f"       app password: {'set' if settings['password'] else '(not set)'}")
    if not configured:
        print("       -> Fill JARVIS_SMTP_USER, JARVIS_SMTP_PASSWORD and")
        print("          JARVIS_EMAIL_FROM in .env. Use a Gmail App Password.")
        return
    if not test:
        print("       -> Run with --test-email to verify the login.")
        return
    print("       testing SMTP login (no message will be sent)...")
    try:
        if settings["use_ssl"]:
            with smtplib.SMTP_SSL(
                settings["host"],
                settings["port"],
                timeout=20,
                context=ssl.create_default_context(),
            ) as server:
                server.login(settings["user"], settings["password"])
        else:
            with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(settings["user"], settings["password"])
        print("       [ OK ] Gmail login succeeded")
    except smtplib.SMTPAuthenticationError:
        print("       [FAIL] Gmail rejected the login. Create a new App Password")
        print("              and paste it into JARVIS_SMTP_PASSWORD.")
        return
    except Exception as error:
        print(f"       [FAIL] {error}")
        return
    print("       testing Gmail IMAP inbox reading (does not mark mail as read)...")
    try:
        emails = jarvis_services.read_unread_email(limit=3)
        print(
            f"       [ OK ] IMAP inbox works; {len(emails)} unread email(s) sampled"
        )
    except Exception as error:
        print(f"       [FAIL] IMAP reading: {error}")
        print("              Enable IMAP in Gmail settings if it is disabled.")


def check_calendar(test: bool) -> None:
    credentials = jarvis_services.GOOGLE_CREDENTIALS_FILE
    token = jarvis_services.GOOGLE_TOKEN_FILE
    print(f"{mark(credentials.exists())} Google Calendar OAuth client")
    print(f"       credentials: {credentials}")
    print(f"       token:       {token} {'(present)' if token.exists() else '(not created yet)'}")
    if not credentials.exists():
        print("       -> Download a Desktop OAuth client JSON and save it as")
        print("          jarvis_google_credentials.json in the repo root.")
        return
    if not test:
        print("       -> Run with --test-calendar to connect (may open a browser).")
        return
    print("       connecting to Google Calendar (a browser may open)...")
    try:
        print("       " + jarvis_services.list_events(days=1).splitlines()[0])
        print("       [ OK ] Calendar access works")
    except Exception as error:
        print(f"       [FAIL] {error}")


def check_screen() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    print(f"{mark(bool(api_key))} Screen vision (Gemini)")
    print(f"       GEMINI_API_KEY: {'set' if api_key else '(not set)'}")
    if not api_key:
        print("       -> Add GEMINI_API_KEY to .env so Jarvis can see the screen.")
    packages = []
    for name in ("uiautomation", "pyautogui", "pyperclip", "PIL"):
        try:
            __import__(name)
            packages.append(name)
        except Exception:
            continue
    print(
        "       screen/WhatsApp controls: "
        + (", ".join(packages) if packages else "(missing; run pip install -r requirements.txt)")
    )


def check_contacts() -> None:
    contacts = jarvis_services.load_contacts()
    print(f"{mark(bool(contacts))} Contacts file")
    print(f"       {jarvis_services.CONTACTS_FILE}")
    if not contacts:
        if os.path.exists(jarvis_services.CONTACTS_FILE):
            print("       -> The file exists but has no contacts yet.")
            print("          Add names, emails and phone numbers to it.")
        else:
            print("       -> Copy jarvis_contacts.example.json to jarvis_contacts.json")
            print("          and add names, emails and phone numbers.")
        return
    for name, record in sorted(contacts.items()):
        if isinstance(record, str):
            record = {"email": record} if "@" in record else {"phone": record}
        parts = []
        if record.get("email"):
            parts.append("email " + mask(record["email"]))
        if record.get("phone"):
            parts.append("phone " + mask(record["phone"]))
        print(f"       - {name}: {', '.join(parts) or '(no email or phone)'}")


def _store_whatsapp_package() -> str:
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-AppxPackage *WhatsApp*).Name",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return ""
    names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return names[0] if names else ""


def check_whatsapp() -> None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "WhatsApp" / "WhatsApp.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "WhatsApp" / "WhatsApp.exe",
        Path(os.environ.get("ProgramFiles", "")) / "WhatsApp" / "WhatsApp.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "WhatsApp" / "WhatsApp.exe",
    ]
    installed = next((path for path in candidates if path.exists()), None)
    store_package = _store_whatsapp_package()
    handler = ""
    try:
        import winreg

        for root, key_path in (
            (winreg.HKEY_CURRENT_USER, r"Software\Classes\whatsapp\shell\open\command"),
            (winreg.HKEY_CLASSES_ROOT, r"whatsapp\shell\open\command"),
        ):
            try:
                with winreg.OpenKey(root, key_path) as key:
                    handler = str(winreg.QueryValueEx(key, "")[0])
                    break
            except OSError:
                continue
    except Exception:
        pass

    available = bool(installed or store_package)
    print(f"{mark(available)} WhatsApp Desktop")
    print(f"       app: {installed or store_package or '(not found)'}")
    print(
        "       whatsapp:// handler: "
        + (handler or ("Microsoft Store app registration" if store_package else "(not registered yet)"))
    )
    if not available:
        print("       -> Install WhatsApp Desktop from https://www.whatsapp.com/download")
        print("          then sign in by linking your phone.")
    elif not handler and not store_package:
        print("       -> Open WhatsApp Desktop once so Windows registers the link handler.")
    else:
        print("       -> Open WhatsApp and stay signed in for message reading and replies.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Jarvis integration setup.")
    parser.add_argument("--test-email", action="store_true", help="verify the Gmail/SMTP login")
    parser.add_argument("--test-calendar", action="store_true", help="connect to Google Calendar")
    args = parser.parse_args()

    print("Jarvis integration check")
    print("=" * 60)
    check_gmail(args.test_email)
    print()
    check_calendar(args.test_calendar)
    print()
    check_screen()
    print()
    check_contacts()
    print()
    check_whatsapp()
    print()
    print("Laptop, browser search, files, apps, PowerShell and Windows")
    print("controls need no extra setup.")


if __name__ == "__main__":
    main()
