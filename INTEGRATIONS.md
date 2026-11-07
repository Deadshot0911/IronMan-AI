# Jarvis laptop, email, WhatsApp, and calendar setup

Jarvis can now open apps and files, read and write files, search the web, read
results aloud, run PowerShell commands, control windows and system settings,
send Gmail, read unread Gmail, read and prepare WhatsApp replies, look at your
screen, act on your screen, and read or create Google Calendar events.

Every one of these actions is **admin-gated**:

- Signed in as the administrator (`Sunrit`): actions run normally.
- Signed in as any other user: Jarvis shows an **ADMIN AUTHORIZATION REQUIRED**
  dialog. The administrator PIN authorizes exactly one action. After that action
  finishes, the next one asks again.

Outbound messages are drafted first. Jarvis shows the draft in the window and
waits for **SEND EMAIL** / **OPEN WHATSAPP WITH MESSAGE** (or "send it" by voice).

Screen actions are planned first. Jarvis screenshots the screen, shows the
planned clicks and typing, and waits for **EXECUTE ON SCREEN** (or "confirm" by
voice). Nothing touches the mouse or keyboard before you approve.

## Check your setup at any time

Run this from the repository root to see what is configured and what is still
missing:

```powershell
.\.venv\Scripts\python.exe check_integrations.py
```

After filling in Gmail, verify sending and inbox reading without sending a
message or marking anything as read:

```powershell
.\.venv\Scripts\python.exe check_integrations.py --test-email
```

After adding the Google OAuth client, connect Calendar (this may open a browser):

```powershell
.\.venv\Scripts\python.exe check_integrations.py --test-calendar
```

## 1. Install the Python dependencies

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`google-auth-oauthlib` is only needed for Google Calendar. The rest of Jarvis
still works without it.

## 2. Gmail sending (SMTP)

Use a Google **App Password**, not your normal Google password.

1. Turn on 2-Step Verification for your Google account.
2. Open <https://myaccount.google.com/apppasswords>.
3. Create an app password for "Jarvis".
4. Add these lines to `.env` in the repository root:

```dotenv
JARVIS_SMTP_HOST=smtp.gmail.com
JARVIS_SMTP_PORT=587
JARVIS_SMTP_USER=you@gmail.com
JARVIS_SMTP_PASSWORD=the-16-character-app-password
JARVIS_EMAIL_FROM=you@gmail.com
```

Jarvis never stores the app password anywhere except `.env`, which is ignored by
git.

## 3. Google Calendar

1. Go to <https://console.cloud.google.com/>.
2. Create a project (or select one) and enable **Google Calendar API**.
3. Open **APIs & Services → OAuth consent screen** and add your Google account
   as a test user.
4. Open **APIs & Services → Credentials → Create credentials → OAuth client ID**.
5. Choose **Desktop app**, create it, and download the JSON.
6. Save the JSON as `jarvis_google_credentials.json` in the repository root.
7. The first calendar command opens a browser for consent. Jarvis saves the
   token as `jarvis_google_token.json`.

Both files are gitignored. You can override their locations with
`JARVIS_GOOGLE_CREDENTIALS` and `JARVIS_GOOGLE_TOKEN`.

## 4. WhatsApp

Install **WhatsApp Desktop** and sign in. Jarvis uses the `whatsapp://` link
handler to open the correct chat with your message already typed. You press
**Send** in WhatsApp; Jarvis cannot press it for you with this integration.

For contacts, copy `jarvis_contacts.example.json` to `jarvis_contacts.json` and
fill in names, emails, and phone numbers:

```json
{
  "Mom": { "email": "mom@example.com", "phone": "+919876543210" },
  "Alex": { "email": "alex@example.com", "phone": "+919876543211" }
}
```

You can also speak an email address or a phone number with its country code
("plus nine one ...") without using the contacts file.

## 5. Reading messages

### Reading WhatsApp messages

Jarvis reads the **visible WhatsApp Desktop chat list** through Windows UI
Automation. It reports unread chats, message counts, and previews, then asks
which chat you want to open or reply to. A reply is typed into the chat and
**you press Send**.

WhatsApp's message bubbles are not exposed to accessibility tools, so Jarvis
reads a conversation with a screenshot plus Gemini vision instead. This also
lets him recover from WhatsApp's "unexpected error" screen by finding and
clicking **Reconnect**.

WhatsApp must be installed from the Microsoft Store (or the desktop installer),
signed in, and left running. You do not need a phone number for a chat reply;
use the chat name Jarvis showed you.

### Reading Gmail

Jarvis reads unread Gmail over IMAP with the same Google App Password used for
sending. Reading uses `BODY.PEEK`, so your messages stay unread in Gmail.
If IMAP is off, enable it in Gmail: **Settings → Forwarding and POP/IMAP**.

## 6. Screen vision and actions

Jarvis can capture the primary screen and answer questions about it with Gemini
vision. This is local capture plus a Gemini request; no other service receives
the image.

For screen actions Jarvis asks Gemini for a short JSON plan, converts the plan's
normalised coordinates to real pixels, validates every step, and shows the plan
in the **CONFIRM SCREEN ACTION** dialog. On approval, `pyautogui` moves the
mouse and types through the clipboard (so Unicode text works).

- Screen actions are admin-gated and expire after 120 seconds.
- Only the documented action types run: click, double-click, right-click, move,
  drag, type, press, hotkey, scroll, wait.
- The plan is capped at 20 steps, and the mouse-to-corner fail-safe still works.
- Jarvis will not press Enter or click Send unless your instruction explicitly
  asks to send.

If you want a different vision model, set `JARVIS_VISION_MODEL` in `.env` to a
comma-separated list. The default tries `gemini-3.5-flash`,
`gemini-3-flash-preview`, `gemini-3.1-flash-lite`, then
`gemini-flash-lite-latest`.

## 7. Things you can say

- "Open Chrome and search today's weather, read it out."
- "Open my Downloads folder."
- "Open the file tax return 2025.pdf."
- "Read notes.txt."
- "Write 'buy milk' to my Desktop shopping list."
- "List my Downloads folder."
- "Find the file called quarterly report."
- "Open Notepad."
- "Run ipconfig."
- "Take a screenshot."
- "Lock my laptop."
- "Turn the volume up."
- "Switch to the Chrome window."
- "What's on my calendar today?"
- "Schedule a meeting with Alex tomorrow at 3pm."
- "Open my email."
- "Draft an email to Mom saying I'll be late."
- "Send me a draft of that email." (Jarvis uses `JARVIS_EMAIL_FROM` for "me".)
- "Send an email to alex@example.com about tomorrow's meeting."
- "Send a WhatsApp to Mom saying I'm on my way."
- "Do I have any new WhatsApp messages?"
- "Read my unread email."
- "Read my chat with Srija."
- "Reply to Srija saying I'll call later." → approve the draft → press Send.
- "What's on my screen?"
- "Look at my screen and tell me what this error means."
- "Click the Compose button and type hello." → review the plan → EXECUTE ON SCREEN.

## Safety notes

- `shell` runs the command you ask for through PowerShell. Destructive commands
  (disk formatting, recursive deletes, registry edits, shutdown/restart, etc.)
  require an extra **CONFIRM DANGEROUS** confirmation, even for the administrator.
- System shutdown/restart/sleep also require that extra confirmation.
- Search results are fetched from DuckDuckGo (with a Bing fallback) and read
  aloud. If the network or the result page fails, Jarvis still opens the search
  in your browser and tells you it could not read the snippets.
- Reading WhatsApp and Gmail never marks messages as read or sends anything by
  itself. WhatsApp replies are typed but not sent; Gmail is only sent after you
  approve the draft.
- Screen actions are planned first and require **EXECUTE ON SCREEN**. The plan
  and the instruction are shown in the Jarvis window before anything runs.
- A pending admin authorization, draft, screen plan, or dangerous confirmation
  expires after 120 seconds.
- Actions are performed by the logged-in Windows account. Jarvis does not
  bypass Windows permissions, UAC prompts, or app sign-ins.
