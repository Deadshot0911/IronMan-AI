import asyncio, os, sys, time, json, threading, queue, re, io, random, collections, ctypes, subprocess, sqlite3
from ctypes import wintypes
from datetime import datetime
from jarvis_auth import (
    AuthenticationError,
    DEFAULT_ADMIN_NAME,
    LocalChatStore,
    SupabaseAuthStore,
    normalize_login_username,
    normalize_gender,
    normalize_spoken_username,
    normalize_spoken_spelling,
    username_from_spelling,
)
from jarvis_action_policy import (
    describe_action,
    is_approval_text,
    is_cancel_text,
    is_danger_confirmation_text,
    is_destructive,
    is_sensitive,
    requires_approval,
    requires_screen_confirmation,
)
import jarvis_pc
import jarvis_screen
import jarvis_services
import jarvis_whatsapp
from jarvis_pc import ActionError
try:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf
    import requests
    import websockets
    import webview
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types
    from groq import Groq
except ModuleNotFoundError as e:
    raise SystemExit(
        f"Jarvis dependency '{e.name}' is unavailable. Start the app with "
        "Start_Jarvis.bat or run .\\.venv\\Scripts\\python.exe jarvis_core.py "
        "from the repository folder."
    ) from e

try:                                   
    import webrtcvad
    _vad = webrtcvad.Vad(2)
except Exception:
    _vad = None

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ---------- CONFIG ----------
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]   
GROQ_MODEL = "openai/gpt-oss-20b"
ROUTER_MODEL = GROQ_MODEL
OLLAMA_MODEL = "llama3"
PENDING_TIMEOUT = 120
VOICE = "bm_george"
FS, FRAME, TTS_SR = 16000, 480, 24000
END_FRAMES = 17                            
MIN_VOICED_FRAMES = 8                      
BARGE_MODE = True
BARGE_MIN = 0.02
LEAD = 0.55
MEM_FILE = "jarvis_memory.json"
ACTION_LOG = "jarvis_actions.log"

try:
    work_area = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(
        0x0030, 0, ctypes.byref(work_area), 0
    ):
        WORK_X, WORK_Y = work_area.left, work_area.top
        SW, SH = work_area.right - work_area.left, work_area.bottom - work_area.top
    else:
        WORK_X = WORK_Y = 0
        SW, SH = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
except Exception:
    WORK_X = WORK_Y = 0
    SW, SH = 1920, 1080
SMALL = 200
BIG_W, BIG_H = SW, SH

kokoro_pipeline = None
kokoro_lock = threading.Lock()
kokoro_warm_started = False

PERSONA = (
    "You are J.A.R.V.I.S., talking with your user like a sharp, warm friend who happens to be a genius. "
    "Never sound like a script or a help desk. Talk the way people really talk: contractions, natural reactions "
    "('Ha', 'Hmm', 'Right', 'Oh, nice one'), and a little dry British wit now and then. "
    "Vary how you start every reply and never repeat a phrase you used recently. "
    "Match the user's mood: playful when they joke, calm and focused when they're stressed. "
    "Sometimes ask a quick follow-up or give a real opinion, but not every time. "
    "Remember what was said earlier and refer back to it naturally. "
    "Call the user 'Sir' only occasionally, when it fits. If you don't know something, say so casually. "
    "You can control yourself when asked: minimise or maximise, go offline or online, switch AI engine "
    "(Gemini, Groq, Ollama or Auto), turn long-term memory on or off, and chat by voice or text."
)
STYLE_VOICE = ("Your words are spoken aloud: default to one to three short sentences (longer only if asked to explain), "
               "no markdown, lists, emojis or symbols, and write numbers and units the way you'd say them.")
STYLE_TEXT = ("You are replying in a text chat window: write naturally and concisely; short paragraphs are fine, and use "
              "code blocks or short lists only when they genuinely help. No emojis unless the user uses them.")

def system_prompt(voice=True):
    mem = ("Long-term memory is ON: you remember this chat and earlier sessions." if memory_on else
           "Long-term memory is OFF: you only keep short context. If the user wants you to remember things, "
           "they can press the Memory button or just ask.")
    return f"{PERSONA}\n{STYLE_VOICE if voice else STYLE_TEXT}\nIt is {datetime.now().strftime('%A, %I:%M %p')}.\n{mem}"

# ---------- STATE ----------
state = "standby"
mini = False            
silent = False          
ui_mini = False         
online = True           
text_mode = False       
output_pref = "auto"    
forced_engine = "Auto"
active = {"name": "Auto", "model": ""}
main_window = None
connected_clients = set()
text_queue = queue.Queue()      
ws_loop = None
win_lock = threading.Lock()
noise, echo_g, barge_boost = 0.004, 0.6, 1.0
chat_seq = 0
chat_log = collections.OrderedDict()
message_save_times = {}
auth_store = None
private_store = None
active_user = None
active_session_id = None
active_session_store = "cloud"
private_mode = False
cloud_memory_snapshot = None
auth_setup = False
auth_mode = "login"
auth_username = None
auth_error = ""
auth_management = None
suspended_user_session = None
auth_prompt_queue = queue.Queue()
auth_lock = threading.RLock()
auth_ready = threading.Event()
ui_loaded = threading.Event()
audio_ready = False
auth_epoch = 0
turn_context = threading.local()
pending_action = None

def new_id():
    global chat_seq
    chat_seq += 1
    return chat_seq

def audit_action(action, result):
    try:
        entry = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": active_user["username"] if active_user else None,
            "role": active_user["role"] if active_user else None,
            "action": action,
            "result": str(result)[:2000],
        }
        with open(ACTION_LOG, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass

# ---------- MEMORY ----------
memory_on = False
stored, recent = [], []

def save_profile():
    global auth_error
    if not auth_store or not active_user:
        return True
    if private_mode:
        return True
    try:
        auth_store.save_profile(
            active_user["id"],
            memory_on,
            json.dumps(stored[-200:], ensure_ascii=False),
        )
    except Exception as e:
        print(f"[Memory save error: {e}]")
        auth_error = "Cloud profile save failed. Check the Supabase connection."
        auth_message()
        return False
    return True

def auth_message_dict(error=None, history=None):
    global auth_error
    with auth_lock:
        users = []
        user_events = []
        if active_user and active_user["role"] == "admin":
            try:
                users = auth_store.list_users()
                user_events = auth_store.list_user_events()
            except Exception as cloud_error:
                detail = str(cloud_error)
                auth_error = (
                    detail
                    if "Cloud user-change history is not set up." in detail
                    else "Cloud account data could not be loaded."
                )
                print(f"[Cloud account-list error: {cloud_error}]")
        return {
            "action": "auth",
            "required": active_user is None,
            "setup": auth_setup,
            "mode": auth_mode,
            "admin_name": DEFAULT_ADMIN_NAME,
            "login_username": auth_username,
            "gender_required": bool(active_user and not active_user.get("gender")),
            "user": dict(active_user) if active_user else None,
            "management": dict(auth_management) if auth_management else None,
            "users": users,
            "user_events": user_events,
            "error": error if error is not None else auth_error,
            "pending_action": pending_public(),
            "history": history,
            "active_conversation_id": (
                f"private:{active_session_id}"
                if active_session_id is not None and active_session_store == "local"
                else active_session_id
            ),
            "private_mode": private_mode,
        }

def auth_message(error=None, history=None):
    payload = auth_message_dict(error, history)
    _broadcast(json.dumps(payload))

def prepare_user_action(operation, target_id):
    global auth_management, auth_error
    if not active_user or active_user["role"] != "admin":
        raise AuthenticationError("Only the administrator can manage users.")
    if operation not in ("disable", "enable", "delete"):
        raise AuthenticationError("Choose disable, enable, or delete.")
    target = auth_store.get_user(int(target_id))
    if not target or target["role"] != "user":
        raise AuthenticationError("That user was not found.")
    if operation == "disable" and not target["active"]:
        raise AuthenticationError("That user is already disabled.")
    if operation == "enable" and target["active"]:
        raise AuthenticationError("That user is already enabled.")
    with auth_lock:
        auth_management = {
            "mode": "user_action",
            "step": "confirm",
            "operation": operation,
            "user_id": target["id"],
            "username": target["username"],
        }
        auth_error = ""
    auth_message()
    auth_prompt_queue.put(
        f"Confirm {operation} for {target['username']} in the window, or say confirm."
    )

def request_admin_pin():
    global auth_management, auth_error
    with auth_lock:
        if not auth_management or auth_management.get("step") != "confirm":
            raise AuthenticationError("There is no pending user action to confirm.")
        auth_management = {**auth_management, "step": "admin_pin"}
        auth_error = ""
        if MIC is not None:
            MIC.set_muted(True)
    auth_message()
    auth_prompt_queue.put("Please enter your administrator PIN in the window.")

def perform_user_action(data):
    global auth_management, auth_error
    if not active_user or active_user["role"] != "admin":
        raise AuthenticationError("Only the administrator can manage users.")
    if not auth_management or auth_management.get("step") != "admin_pin":
        raise AuthenticationError("Confirm the action before entering the administrator PIN.")
    auth_store.authenticate(
        active_user["username"],
        data.get("admin_pin", ""),
        require_admin=True,
    )
    target_id = int(auth_management["user_id"])
    username = auth_management["username"]
    operation = auth_management["operation"]
    if operation == "disable":
        auth_store.disable_user(active_user["id"], target_id)
        message = f"{username} was disabled. Their history was kept."
    elif operation == "enable":
        auth_store.enable_user(active_user["id"], target_id)
        message = f"{username} was enabled."
    else:
        auth_store.delete_user(active_user["id"], target_id)
        message = f"{username} and their history were permanently deleted."
    with auth_lock:
        auth_management = None
        auth_error = message
        if MIC is not None:
            MIC.set_muted(False)
    auth_message()
    auth_prompt_queue.put(message)

def set_login_username(value):
    global auth_username, auth_mode, auth_error
    username = normalize_login_username(value)
    if not username or len(username) > 60:
        raise AuthenticationError("Enter a username between 1 and 60 characters.")
    if any(ord(char) < 32 for char in username):
        raise AuthenticationError("The username contains unsupported characters.")
    with auth_lock:
        if active_user:
            raise AuthenticationError("End the current session before signing in.")
        auth_username = username
        auth_mode = "pin"
        auth_error = ""
        if MIC is not None:
            MIC.set_muted(True)
    auth_message()
    set_state("standby")

def set_add_user_username(value):
    global auth_management, auth_error
    username = normalize_spoken_username(value)
    if not username or len(username) > 60:
        raise AuthenticationError("Enter a username between 1 and 60 characters.")
    if any(ord(char) < 32 for char in username):
        raise AuthenticationError("The username contains unsupported characters.")
    with auth_lock:
        if not active_user or active_user["role"] != "admin":
            raise AuthenticationError("Only the signed-in administrator can add users.")
        if (
            not auth_management
            or auth_management.get("mode") != "add_user"
            or auth_management.get("step") != "username"
        ):
            raise AuthenticationError("There is no new-user form open.")
        auth_management = {
            "mode": "add_user",
            "step": "spelling",
            "username": username,
        }
        auth_error = ""
    auth_message()
    set_state("standby")
    auth_prompt_queue.put(
        f"Please say {username}'s spelling one letter at a time, then say done."
    )

def set_add_user_spelling(value, complete=False):
    global auth_management, auth_error
    with auth_lock:
        if not active_user or active_user["role"] != "admin":
            raise AuthenticationError("Only the signed-in administrator can add users.")
        if (
            not auth_management
            or auth_management.get("mode") != "add_user"
            or auth_management.get("step") != "spelling"
        ):
            raise AuthenticationError("There is no spelling step open.")
        if not complete:
            command = re.sub(r"[^\w\s']", "", str(value or "").casefold()).strip()
            if command in ("done", "finish", "finished", "that's all", "thats all", "confirm"):
                value = auth_management.get("spelling", "")
                if not value:
                    raise AuthenticationError("I haven't heard any letters yet. Say the spelling, then say done.")
            elif command in ("clear", "start over", "restart"):
                auth_management = {**auth_management, "spelling": ""}
                auth_error = ""
                auth_message()
                auth_prompt_queue.put("Spelling cleared. Say the first letter, then say done when finished.")
                return
            else:
                letter = normalize_spoken_spelling(value)
                if letter:
                    spelling = auth_management.get("spelling", "") + letter
                    if len(spelling) > 60:
                        raise AuthenticationError("The spelling is too long. Say clear to start over.")
                    auth_management = {**auth_management, "spelling": spelling}
                    auth_error = ""
                    auth_message()
                    auth_prompt_queue.put(
                        f"Got it, {len(spelling)} letter{'s' if len(spelling) != 1 else ''}. "
                        "Say the next letter, or say done."
                    )
                    return
        username = username_from_spelling(auth_management["username"], value)
        if len(username) > 60 or any(ord(char) < 32 for char in username):
            raise AuthenticationError("Enter a name between 1 and 60 characters.")
        auth_management = {
            "mode": "add_user",
            "step": "gender",
            "username": username,
        }
        auth_error = ""
    auth_message()
    set_state("standby")
    auth_prompt_queue.put(
        f"What gender should I use when addressing {username}? "
        "Say male, female, non-binary, or prefer not to say."
    )

def set_add_user_gender(value):
    global auth_management, auth_error
    gender = normalize_gender(value)
    with auth_lock:
        if not active_user or active_user["role"] != "admin":
            raise AuthenticationError("Only the signed-in administrator can add users.")
        if (
            not auth_management
            or auth_management.get("mode") != "add_user"
            or auth_management.get("step") != "gender"
        ):
            raise AuthenticationError("There is no new-user gender choice open.")
        auth_management = {
            **auth_management,
            "step": "pin",
            "gender": gender,
        }
        auth_error = ""
        if MIC is not None:
            MIC.set_muted(True)
    auth_message()
    set_state("standby")
    auth_prompt_queue.put(
        f"Gender saved. Enter and confirm the new PIN for {auth_management['username']} in the window."
    )

def set_active_user_gender(value):
    global active_user, auth_mode, auth_error
    if not active_user:
        raise AuthenticationError("Sign in before setting a profile.")
    auth_store.set_gender(active_user["id"], normalize_gender(value))
    active_user = auth_store.get_user(active_user["id"])
    while not auth_prompt_queue.empty():
        try:
            auth_prompt_queue.get_nowait()
        except queue.Empty:
            break
    with auth_lock:
        auth_mode = "login"
        auth_error = ""
        if MIC is not None:
            MIC.set_muted(False)
        auth_ready.set()
    auth_message()
    push_state()

def handle_gender_choice(value):
    if active_user and auth_mode == "gender_setup":
        set_active_user_gender(value)
    else:
        set_add_user_gender(value)

def request_end_session():
    global auth_management, auth_error
    if not active_user:
        raise AuthenticationError("There is no active user session to end.")
    with auth_lock:
        auth_management = {"mode": "end_session", "step": "user_pin"}
        auth_error = ""
        if MIC is not None:
            MIC.set_muted(True)
    auth_message()
    auth_prompt_queue.put("Enter your account PIN in the window to end this session.")

def confirm_end_session(data):
    global auth_error
    if (
        not active_user
        or not auth_management
        or auth_management.get("mode") != "end_session"
        or auth_management.get("step") != "user_pin"
    ):
        raise AuthenticationError("There is no pending session-end request.")
    auth_store.authenticate(active_user["username"], data.get("user_pin", ""))
    end_user_session()

def activate_user(user):
    global active_user, active_session_id, active_session_store, private_mode, memory_on, chat_seq, auth_epoch
    global auth_error, auth_management, auth_username, auth_mode, cloud_memory_snapshot, suspended_user_session
    global pending_action
    with auth_lock:
        history = []
        memory_on, saved_memory = auth_store.load_profile(user["id"])
        loaded_memory = json.loads(saved_memory)
        if not isinstance(loaded_memory, list):
            raise ValueError("Saved user memory must be a list.")
        active_user = user
        active_session_id = auth_store.start_session(user["id"])
        active_session_store = "cloud"
        private_mode = False
        cloud_memory_snapshot = None
        stored[:] = loaded_memory[-200:]
        recent.clear()
        chat_log.clear()
        auth_management = None
        suspended_user_session = None
        pending_action = None
        auth_username = None
        auth_mode = "login" if user.get("gender") else "gender_setup"
        auth_error = ""
        auth_epoch += 1
        if MIC is not None:
            MIC.set_muted(False)
        if user.get("gender"):
            auth_ready.set()
        else:
            auth_prompt_queue.put(
                "How should I greet you? Choose a gender option or prefer not to say in the window."
            )
    auth_message(history=history)
    push_conversations()
    push_state()

def begin_admin_takeover():
    global active_user, active_session_id, active_session_store, private_mode
    global cloud_memory_snapshot, auth_mode, auth_username, auth_error
    global auth_management, auth_epoch, memory_on, suspended_user_session
    if not active_user or active_user["role"] == "admin":
        raise AuthenticationError("Admin control is only available from a non-admin session.")
    if not save_profile():
        raise RuntimeError(auth_error)
    suspended_user_session = {
        "active_user": active_user,
        "active_session_id": active_session_id,
        "active_session_store": active_session_store,
        "private_mode": private_mode,
        "cloud_memory_snapshot": cloud_memory_snapshot,
        "memory_on": memory_on,
        "stored": list(stored),
        "recent": list(recent),
        "chat_log": list(chat_log.items()),
        "message_save_times": dict(message_save_times),
        "was_ready": auth_ready.is_set(),
        "mic_muted": MIC.muted if MIC is not None else False,
    }
    auth_ready.clear()
    auth_epoch += 1
    if SPK is not None:
        SPK.stop_now()
    if MIC is not None:
        MIC.set_muted(True)
    active_user = None
    active_session_id = None
    active_session_store = "cloud"
    private_mode = False
    cloud_memory_snapshot = None
    memory_on = False
    auth_management = None
    auth_mode = "admin_takeover"
    auth_username = DEFAULT_ADMIN_NAME
    auth_error = ""
    while not auth_prompt_queue.empty():
        try:
            auth_prompt_queue.get_nowait()
        except queue.Empty:
            break
    auth_prompt_queue.put("Admin control requested. Enter the administrator PIN in the window.")
    set_state("standby")
    auth_message()

def cancel_admin_takeover():
    global active_user, active_session_id, active_session_store, private_mode
    global cloud_memory_snapshot, auth_mode, auth_username, auth_error
    global auth_epoch, memory_on, suspended_user_session
    if auth_mode != "admin_takeover" or suspended_user_session is None:
        raise AuthenticationError("There is no paused user session to resume.")
    session = suspended_user_session
    suspended_user_session = None
    active_user = session["active_user"]
    active_session_id = session["active_session_id"]
    active_session_store = session["active_session_store"]
    private_mode = session["private_mode"]
    cloud_memory_snapshot = session["cloud_memory_snapshot"]
    memory_on = session["memory_on"]
    stored[:] = session["stored"]
    recent[:] = session["recent"]
    chat_log.clear()
    chat_log.update(session["chat_log"])
    message_save_times.clear()
    message_save_times.update(session["message_save_times"])
    auth_mode = "login"
    auth_username = None
    auth_error = ""
    auth_epoch += 1
    while not auth_prompt_queue.empty():
        try:
            auth_prompt_queue.get_nowait()
        except queue.Empty:
            break
    if session["was_ready"]:
        auth_ready.set()
    if MIC is not None:
        MIC.set_muted(session["mic_muted"])
    auth_message(
        history=[
            {"id": message_id, "from": sender, "text": text}
            for message_id, (sender, text) in session["chat_log"]
        ]
    )
    push_conversations()
    push_state()

def end_user_session(next_mode="login", error=""):
    global active_user, active_session_id, active_session_store, private_mode, cloud_memory_snapshot, auth_mode, auth_username, auth_error, auth_management, auth_epoch, memory_on, silent
    global pending_action
    with auth_lock:
        if cloud_memory_snapshot is not None:
            memory_on, saved_memory = cloud_memory_snapshot
            stored[:] = saved_memory
            cloud_memory_snapshot = None
            private_mode = False
        if active_user and active_session_id is not None:
            if not save_profile():
                raise RuntimeError(auth_error)
            current_store = private_store if active_session_store == "local" else auth_store
            current_store.end_session(active_session_id)
        auth_ready.clear()
        auth_epoch += 1
        if SPK is not None:
            SPK.stop_now()
        silent = False
        if MIC is not None:
            MIC.set_muted(next_mode == "admin_takeover")
        active_user = None
        active_session_id = None
        active_session_store = "cloud"
        private_mode = False
        memory_on = False
        pending_action = None
        auth_mode = next_mode
        auth_username = DEFAULT_ADMIN_NAME if next_mode == "admin_takeover" else None
        auth_error = error
        auth_management = None
        while not auth_prompt_queue.empty():
            try:
                auth_prompt_queue.get_nowait()
            except queue.Empty:
                break
        recent.clear()
        stored.clear()
        chat_log.clear()
        while not text_queue.empty():
            try:
                text_queue.get_nowait()
            except queue.Empty:
                break
        set_state("standby")
    auth_message()
    if next_mode == "login":
        auth_prompt_queue.put("Who's using Jarvis? Say your username, or type it on screen.")
    elif next_mode == "admin_takeover":
        auth_prompt_queue.put("Admin control requested. Enter the administrator PIN in the window.")

def set_memory(on):
    global memory_on
    if on == memory_on: return
    if on: stored.extend(recent)
    memory_on = on
    save_profile(); push_state()

def wipe_memory():
    stored.clear(); save_profile(); push_state()

def push_conversations():
    if not active_user:
        return
    regular, archived = conversations_for_user(active_user["id"])
    _broadcast(json.dumps({
        "action": "conversations",
        "items": regular,
        "archived_items": archived,
        "active_id": active_conversation_id(),
    }))

def conversations_for_user(user_id):
    regular = auth_store.list_conversations(user_id)
    archived = auth_store.list_conversations(user_id, archived=True)
    if private_store is not None:
        regular += private_store.list_conversations(user_id)
        archived += private_store.list_conversations(user_id, archived=True)
    regular.sort(key=lambda item: item["started_at"], reverse=True)
    archived.sort(key=lambda item: item["started_at"], reverse=True)
    return regular, archived

def active_conversation_id():
    if active_session_id is not None and active_session_store == "local":
        return f"private:{active_session_id}"
    return active_session_id

def archive_history():
    if not active_user:
        raise AuthenticationError("Sign in before archiving discussions.")
    auth_store.archive_all_conversations(active_user["id"])
    if private_store is not None:
        private_store.archive_all_conversations(active_user["id"])
    new_conversation()

def permanently_delete_history():
    global memory_on, active_session_id, active_session_store, private_mode, cloud_memory_snapshot, auth_epoch, auth_management
    if not active_user:
        raise AuthenticationError("Sign in before deleting discussions.")
    user_id = active_user["id"]
    auth_store.delete_all_conversations(user_id)
    if private_store is not None:
        private_store.delete_all_conversations(user_id)
    stored.clear()
    recent.clear()
    chat_log.clear()
    message_save_times.clear()
    memory_on = False
    active_session_store = "cloud"
    private_mode = False
    cloud_memory_snapshot = None
    active_session_id = auth_store.start_session(user_id)
    auth_epoch += 1
    auth_management = None
    auth_message(history=[])
    push_conversations()
    push_state()

def set_conversation_archived(conversation_id, archived):
    if not active_user:
        raise AuthenticationError("Sign in before changing archived discussions.")
    is_private = isinstance(conversation_id, str) and conversation_id.startswith("private:")
    session_id = (
        int(conversation_id.split(":", 1)[1])
        if is_private
        else int(conversation_id)
    )
    store = private_store if is_private else auth_store
    if store is None:
        raise RuntimeError("Local private chat storage is unavailable.")
    store.set_conversation_archived(active_user["id"], session_id, archived)

def set_private_mode(enabled):
    if not active_user:
        raise AuthenticationError("Sign in before changing privacy mode.")
    switch_private_context(bool(enabled))
    new_conversation(private=enabled)

def switch_private_context(enabled):
    global private_mode, cloud_memory_snapshot, memory_on
    if enabled == private_mode:
        return
    if enabled:
        cloud_memory_snapshot = (memory_on, list(stored))
        private_mode = True
        return
    if cloud_memory_snapshot is not None:
        memory_on, saved_memory = cloud_memory_snapshot
        stored[:] = saved_memory
        cloud_memory_snapshot = None
    private_mode = False

def new_conversation(private=None):
    global active_session_id, active_session_store, private_mode, auth_epoch
    if not active_user:
        raise AuthenticationError("Sign in before starting a discussion.")
    if SPK is not None:
        SPK.stop_now()
    if active_session_id is not None:
        current_store = private_store if active_session_store == "local" else auth_store
        current_store.end_session(active_session_id)
    if private is not None:
        private_mode = bool(private)
    active_session_store = "local" if private_mode else "cloud"
    target_store = private_store if private_mode else auth_store
    if target_store is None:
        raise RuntimeError("Local private chat storage is unavailable.")
    active_session_id = target_store.start_session(active_user["id"])
    auth_epoch += 1
    recent.clear()
    chat_log.clear()
    message_save_times.clear()
    while not text_queue.empty():
        try:
            text_queue.get_nowait()
        except queue.Empty:
            break
    auth_message(history=[])
    push_conversations()
    set_state(ready_state())

def open_conversation(conversation_id):
    global active_session_id, active_session_store, auth_epoch
    if not active_user:
        raise AuthenticationError("Sign in before opening a discussion.")
    private = isinstance(conversation_id, str) and conversation_id.startswith("private:")
    session_id = int(conversation_id.split(":", 1)[1]) if private else int(conversation_id)
    target_store = private_store if private else auth_store
    if target_store is None:
        raise RuntimeError("Local private chat storage is unavailable.")
    if SPK is not None:
        SPK.stop_now()
    target_store.activate_session(active_user["id"], session_id)
    active_session_id = session_id
    active_session_store = "local" if private else "cloud"
    switch_private_context(private)
    auth_epoch += 1
    while not text_queue.empty():
        try:
            text_queue.get_nowait()
        except queue.Empty:
            break
    history = target_store.recent_messages(
        active_user["id"], session_id=active_session_id
    )
    recent[:] = [
        {
            "role": "user" if item["from"] == "you" else "assistant",
            "content": item["text"],
        }
        for item in history[-6:]
    ]
    chat_log.clear()
    message_save_times.clear()
    for item in history:
        try:
            chat_seq = max(chat_seq, int(item["id"]))
        except (TypeError, ValueError):
            pass
        chat_log[item["id"]] = (item["from"], item["text"])
    while len(chat_log) > 60:
        chat_log.popitem(last=False)
    auth_message(history=history)
    push_conversations()
    set_state(ready_state())

# ---------- WEBSOCKET ----------
def _broadcast(msg):
    if not (ws_loop and connected_clients): return
    async def send_all():
        await asyncio.gather(*[c.send(msg) for c in list(connected_clients)], return_exceptions=True)
    asyncio.run_coroutine_threadsafe(send_all(), ws_loop)

def state_msg():
    return json.dumps({"action": "state", "state": state, "mini": ui_mini, "silent": silent, "online": online,
                       "memory": memory_on, "text_mode": text_mode, "output": output_pref,
                       "private_mode": private_mode,
                       "user": active_user["username"] if active_user else None,
                       "role": active_user["role"] if active_user else None,
                       "engine": {"mode": forced_engine, "name": active["name"], "model": active["model"]}})

def push_state(): _broadcast(state_msg())

def set_state(s):
    global state
    state = s; push_state()

def ready_state():
    return "listening" if online and not silent else "standby"

def set_active(name, model):
    active["name"], active["model"] = name, model; push_state()

def push_chat(mid, who, text, persist=False):
    global auth_error
    turn_epoch = getattr(turn_context, "epoch", None)
    if turn_epoch is not None and turn_epoch != auth_epoch:
        return
    chat_log[mid] = (who, text)
    while len(chat_log) > 60: chat_log.popitem(last=False)
    now = time.monotonic()
    should_persist = (
        who == "you"
        or persist
        or now - message_save_times.get(mid, 0) >= 1.0
    )
    if active_user and active_session_id is not None and should_persist:
        try:
            target_store = private_store if active_session_store == "local" else auth_store
            target_store.save_message(
                active_user["id"],
                active_session_id,
                mid,
                "user" if who == "you" else "assistant",
                text,
            )
            message_save_times[mid] = now
        except Exception as error:
            print(f"[Cloud conversation save error: {error}]")
            with auth_lock:
                auth_error = "Conversation save failed. Check the selected storage is available."
            auth_message()
    _broadcast(json.dumps({"action": "chat", "id": mid, "from": who, "text": text}))
    if who == "you":
        push_conversations()

def set_text_mode(on):
    global text_mode
    text_mode = bool(on); push_state()

def set_output_preference(mode):
    global output_pref
    value = str(mode or "").strip().lower()
    if value not in ("voice", "text", "auto"):
        print(f"[Output preference error: unsupported mode {mode!r}]")
        return False
    output_pref = value
    push_state()
    return True

def handle_auth_action(data):
    global auth_error, auth_mode, auth_management, auth_username, active_user, auth_setup
    action = data.get("do")
    try:
        if action == "close_app":
            if auth_mode == "admin_takeover" and suspended_user_session:
                cancel_admin_takeover()
            else:
                close_jarvis()
        elif action == "cancel_admin_takeover":
            cancel_admin_takeover()
        elif action == "bootstrap":
            if active_user or auth_store.has_admin():
                raise AuthenticationError("Administrator setup is already complete.")
            user = auth_store.bootstrap_admin(data.get("pin", ""))
            auth_setup = False
            activate_user(user)
        elif action == "username":
            set_login_username(data.get("username", ""))
        elif action == "username_reset":
            with auth_lock:
                if active_user or auth_mode == "admin_takeover":
                    raise AuthenticationError("This sign-in step cannot be changed.")
                auth_username = None
                auth_mode = "login"
                auth_error = ""
                if MIC is not None:
                    MIC.set_muted(False)
            auth_message()
        elif action == "login":
            if active_user:
                raise AuthenticationError("End the current session before signing in again.")
            with auth_lock:
                username = auth_username
                require_admin = auth_mode == "admin_takeover" or (
                    auth_mode == "pin"
                    and isinstance(username, str)
                    and username.casefold() == DEFAULT_ADMIN_NAME.casefold()
                )
            user = auth_store.authenticate(
                username or "",
                data.get("pin", ""),
                require_admin=require_admin,
            )
            activate_user(user)
        elif action == "set_gender":
            if not active_user:
                raise AuthenticationError("Sign in before setting a profile.")
            set_active_user_gender(data.get("gender"))
        elif action == "logout":
            if active_user is None:
                raise AuthenticationError("There is no signed-in session.")
            request_end_session()
        elif action == "confirm_end_session":
            confirm_end_session(data)
        elif action == "new_conversation":
            new_conversation()
        elif action == "open_conversation":
            open_conversation(data.get("conversation_id"))
        elif action == "set_private_mode":
            set_private_mode(data.get("enabled", False))
        elif action == "archive_history":
            archive_history()
        elif action == "restore_conversation":
            set_conversation_archived(data.get("conversation_id"), False)
            push_conversations()
        elif action == "open_permanent_delete_history":
            auth_management = {"mode": "permanently_delete_history"}
            auth_error = ""
            auth_message()
        elif action == "permanently_delete_history":
            if not auth_management or auth_management.get("mode") != "permanently_delete_history":
                raise AuthenticationError("Confirm permanent deletion in the window first.")
            permanently_delete_history()
        elif action == "open_add_user":
            if not active_user or active_user["role"] != "admin":
                raise AuthenticationError("Only the signed-in administrator can add users.")
            name = normalize_spoken_username(data.get("username", ""))
            with auth_lock:
                auth_management = {
                    "mode": "add_user",
                    "step": "spelling" if name else "username",
                    "username": name[:60],
                }
                auth_error = ""
            auth_message()
            if name:
                auth_prompt_queue.put(
                    f"Please say {name}'s spelling one letter at a time, then say done."
                )
            else:
                auth_prompt_queue.put("What's the new user's name? Say it, or type it in the window.")
        elif action == "set_add_username":
            set_add_user_username(data.get("username", ""))
        elif action == "set_add_spelling":
            set_add_user_spelling(data.get("spelling", ""), complete=True)
        elif action == "set_add_gender":
            handle_gender_choice(data.get("gender", ""))
        elif action == "add_user":
            if not active_user or active_user["role"] != "admin":
                raise AuthenticationError("Only the signed-in administrator can add users.")
            if (
                not auth_management
                or auth_management.get("mode") != "add_user"
                or auth_management.get("step") != "pin"
            ):
                raise AuthenticationError("Complete the name and gender steps before setting a PIN.")
            user = auth_store.add_user(
                active_user["id"],
                auth_management["username"],
                data.get("pin", ""),
                gender=auth_management["gender"],
            )
            title = {
                "male": "Sir",
                "female": "Ma'am",
                "non_binary": user["username"],
                "prefer_not_to_say": user["username"],
            }[user["gender"]]
            confirmation = (
                f"{user['username']} was added. Welcome, {title}. "
                "Your account is ready whenever you want to sign in."
            )
            with auth_lock:
                auth_management = None
                auth_error = confirmation
                if MIC is not None:
                    MIC.set_muted(False)
            auth_message()
            auth_prompt_queue.put(confirmation)
        elif action == "open_delete_user":
            if not active_user or active_user["role"] != "admin":
                raise AuthenticationError("Only the signed-in administrator can manage users.")
            with auth_lock:
                auth_management = {"mode": "users"}
                auth_error = ""
            auth_message()
        elif action == "prepare_user_action":
            prepare_user_action(data.get("operation", ""), data.get("user_id"))
        elif action == "confirm_user_action":
            request_admin_pin()
        elif action == "manage_user":
            perform_user_action(data)
        elif action == "close_management":
            with auth_lock:
                auth_management = None
                auth_error = ""
                if MIC is not None:
                    MIC.set_muted(False)
            auth_message()
        elif action == "authorize_action":
            authorize_pending_action(data.get("admin_pin", ""))
        elif action == "confirm_pending_action":
            confirm_pending_action()
        elif action == "cancel_pending_action":
            cancel_pending_action()
        else:
            raise AuthenticationError("That account action is not supported.")
    except (AuthenticationError, TypeError, ValueError, RuntimeError, sqlite3.Error) as error:
        with auth_lock:
            auth_error = (
                "Local private-chat storage is unavailable."
                if isinstance(error, sqlite3.Error)
                else str(error)
            )
        auth_message()

async def ws_handler(websocket):
    connected_clients.add(websocket)
    await websocket.send(state_msg())
    await websocket.send(json.dumps(auth_message_dict()))
    if active_user:
        conversations, archived = conversations_for_user(active_user["id"])
        await websocket.send(json.dumps({
            "action": "conversations",
            "items": conversations,
            "archived_items": archived,
            "active_id": active_conversation_id(),
        }))
    for mid, (who, text) in list(chat_log.items()):          
        await websocket.send(json.dumps({"action": "chat", "id": mid, "from": who, "text": text}))
    try:
        async for message in websocket:
            try:
                d = json.loads(message); a = d.get("action")
                if a == "auth":
                    handle_auth_action(d)
                elif not active_user:
                    continue
                elif a == "command":
                    text = d.get("text", "")
                    if CLOSE_REQUEST.search(text):
                        close_jarvis()
                    else:
                        text_queue.put((text, "text"))
                elif a == "set_engine": threading.Thread(target=ui_engine, args=(d.get("engine", "Auto"),), daemon=True).start()
                elif a == "set_memory": set_memory(bool(d.get("on")))
                elif a == "set_mode": set_text_mode(bool(d.get("text")))
                elif a == "set_output": set_output_preference(d.get("mode"))
                elif a == "set_mute":
                    set_silent(d.get("muted", False))
                elif a == "ui":
                    if d.get("do") == "minimize": act_minimize()
                    elif d.get("do") == "maximize": act_maximize()
                    elif d.get("do") == "close": close_jarvis()
            except Exception as e:
                print(f"[WS message error: {e}]")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)

def start_ws_server():
    async def run():
        global ws_loop
        ws_loop = asyncio.get_running_loop()
        async with websockets.serve(ws_handler, "localhost", 8000):
            await asyncio.Future()
    asyncio.run(run())

def heartbeat():
    while True:
        time.sleep(1.5)
        push_state()

# ---------- WINDOW ----------
def glide(x2, y2, ms=350, steps=18):
    x1, y1 = main_window.x, main_window.y
    for i in range(1, steps + 1):
        e = 1 - (1 - i / steps) ** 3
        main_window.move(int(x1 + (x2 - x1) * e), int(y1 + (y2 - y1) * e))
        time.sleep(ms / 1000 / steps)

def window_to_corner():
    global ui_mini
    if not main_window: return
    with win_lock:
        ui_mini = True; push_state()
        time.sleep(0.75)
        cx = main_window.x + main_window.width // 2
        cy = main_window.y + main_window.height // 2
        main_window.resize(SMALL, SMALL)
        main_window.move(cx - SMALL // 2, cy - SMALL // 2)
        glide(WORK_X + SW - SMALL - 30, WORK_Y + SH - SMALL - 30)

def window_to_center():
    global ui_mini
    if not main_window: return
    with win_lock:
        glide(WORK_X + SW // 2 - SMALL // 2, WORK_Y + SH // 2 - SMALL // 2)
        main_window.resize(BIG_W, BIG_H)
        main_window.move(WORK_X, WORK_Y)
        time.sleep(0.15)
        ui_mini = False; push_state()

def close_jarvis():
    if main_window:
        try:
            main_window.destroy()
        except Exception as e:
            print(f"[Jarvis shutdown error: {e}]")

def set_silent(value):
    global silent
    silent = bool(value)
    if MIC is not None:
        try:
            MIC.set_muted(False)
        except Exception as e:
            print(f"[Microphone mute error: {e}]")
    push_state()

def act_minimize(mute=None):
    global mini, silent
    was = mini
    mini = True
    if mute is not None:
        silent = bool(mute)
    if MIC is not None:
        try:
            MIC.set_muted(False)
        except Exception as e:
            print(f"[Microphone mute error: {e}]")
    if not was: threading.Thread(target=window_to_corner, daemon=True).start()
    else: push_state()

def act_maximize():
    global mini
    was = mini
    mini = False
    if was: threading.Thread(target=window_to_center, daemon=True).start()
    else: push_state()

# ---------- AUDIO CORE ----------
def rms(x): return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0

def is_voice(frame):
    if _vad is None: return True
    try:
        return _vad.is_speech((np.clip(frame, -1, 1) * 32767).astype(np.int16).tobytes(), FS)
    except Exception:
        return True

class Mic:
    def __init__(self):
        self.q = queue.Queue(maxsize=300)
        self.muted = False
        self.stream = sd.InputStream(samplerate=FS, channels=1, dtype="float32", blocksize=FRAME, callback=self._cb)
        self.stream.start()
    def _cb(self, indata, frames, tinfo, status):
        if self.muted:
            return
        x = indata[:, 0].copy()
        try: self.q.put_nowait(x)
        except queue.Full:
            try: self.q.get_nowait(); self.q.put_nowait(x)
            except Exception: pass
    def set_muted(self, muted):
        muted = bool(muted)
        if muted == self.muted: return
        if muted:
            self.muted = True
            self.flush()
            if self.stream.active: self.stream.stop()
        else:
            if not self.stream.active: self.stream.start()
            self.flush()
            self.muted = False
    def read(self, timeout=0.1):
        try: return self.q.get(timeout=timeout)
        except queue.Empty: return None
    def flush(self):
        while True:
            try: self.q.get_nowait()
            except queue.Empty: break

class Speaker:
    def __init__(self):
        self.lock = threading.Lock()
        self.chunks = collections.deque()
        self.cur, self.pos, self.queued = None, 0, 0
        self.gain, self.target, self.pausing = 1.0, 1.0, False
        self.hist = collections.deque(maxlen=120)
        self.last_callback_status = ""
        self.stream = sd.OutputStream(samplerate=TTS_SR, channels=1, dtype="float32",
                                      blocksize=512, latency=0.15, callback=self._cb)
        self.stream.start()
    def _cb(self, outdata, frames, tinfo, status):
        if status:
            message = str(status)
            if message != self.last_callback_status:
                print(f"[Audio output warning: {message}]")
                self.last_callback_status = message
        elif self.last_callback_status:
            self.last_callback_status = ""
        buf = outdata[:, 0]
        n = 0
        if not (self.pausing and self.gain < 0.03):
            with self.lock:
                while n < frames:
                    if self.cur is None:
                        if not self.chunks: break
                        self.cur, self.pos = self.chunks.popleft(), 0
                    take = min(frames - n, len(self.cur) - self.pos)
                    buf[n:n + take] = self.cur[self.pos:self.pos + take]
                    n += take; self.pos += take; self.queued -= take
                    if self.pos >= len(self.cur): self.cur = None
        buf[n:] = 0
        self.gain += (self.target - self.gain) * 0.3
        buf *= self.gain
        self.hist.append((time.monotonic(), float(np.sqrt(np.mean(buf * buf)))))
    def push(self, a):
        with self.lock: self.chunks.append(a); self.queued += len(a)
    def flush(self):
        with self.lock: self.chunks.clear(); self.cur = None; self.queued = 0
    def pause(self): self.pausing = True; self.target = 0.0
    def resume(self): self.pausing = False; self.target = 1.0
    def stop_now(self):
        self.pause(); time.sleep(0.1); self.flush()
        self.pausing = False; self.target = 1.0; self.gain = 1.0
    def echo_level(self, window=0.7):
        try: items = list(self.hist)
        except RuntimeError: return 0.0
        now = time.monotonic()
        return max((r for t, r in items if now - t <= window), default=0.0)

MIC = SPK = None

def init_audio():
    global MIC, SPK
    speaker = None
    microphone = None
    try:
        speaker = Speaker()
        microphone = Mic()
        microphone.set_muted(silent)
    except Exception:
        for stream in (
            getattr(microphone, "stream", None),
            getattr(speaker, "stream", None),
        ):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as cleanup_error:
                    print(f"[Audio cleanup error: {cleanup_error}]")
        raise
    SPK, MIC = speaker, microphone

def calibrate_noise():
    global noise
    MIC.flush(); time.sleep(1.0)
    vals = []
    while True:
        f = MIC.read(0.01)
        if f is None: break
        vals.append(rms(f))
    if vals: noise = max(0.002, float(np.median(vals)))

def speech_thr(): return max(0.009, noise * 2.5)

# ---------- EARS ----------
def clean(t): return re.sub(r"[^\w\s]", "", t.lower()).strip()
HALLU = {"thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "you", "so", "oh"}

def transcribe(audio, spelling_mode=False, gender_mode=False, wake_only=False):
    buf = io.BytesIO(); sf.write(buf, audio, FS, format="WAV", subtype="PCM_16")
    prompt = (
        "The user is spelling a username aloud. Transcribe each spoken letter "
        "separately as its letter name or letter: A, B, C, D, E, F, G, H, I, "
        "J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z."
        if spelling_mode else
        "The user is choosing a gender option. Transcribe exactly what they say: "
        "male, female, non-binary, or prefer not to say."
        if gender_mode else
        "The microphone is muted. Transcribe only the exact wake command if spoken: "
        "Jarvis unmute. Do not infer or add words."
        if wake_only else
        "J.A.R.V.I.S. Jarvis. Gemini, Groq, Ollama. Mute, unmute, stop listening, "
        "start listening, text mode, voice mode, memory, minimize, maximize."
    )
    try:
        r = groq_client.audio.transcriptions.create(
            file=("audio.wav", buf.getvalue()), model="whisper-large-v3-turbo", language="en",
            response_format="verbose_json",
            prompt=prompt,
            temperature=0)
        text = (getattr(r, "text", None) or (r.get("text") if isinstance(r, dict) else "") or "").strip()
        segs = getattr(r, "segments", None) or (r.get("segments") if isinstance(r, dict) else None) or []
        def g(s, k):
            v = s.get(k) if isinstance(s, dict) else getattr(s, k, None)
            return 0.0 if v is None else v
        if (
            segs
            and all(g(s, "no_speech_prob") > 0.5 for s in segs)
            and not spelling_mode
            and not gender_mode
            and not wake_only
        ):
            return None
        return text if text and (spelling_mode or gender_mode or wake_only or len(text) > 1) else None
    except Exception as e:
        print(f"[STT error: {e}]"); return None

def listen_fast(allow_unauthenticated=False):
    global noise
    set_state(ready_state())
    gender_setup = bool(active_user and auth_mode == "gender_setup")
    spelling_mode = bool(
        auth_management
        and auth_management.get("mode") == "add_user"
        and auth_management.get("step") == "spelling"
    )
    gender_mode = bool(
        (active_user and auth_mode == "gender_setup")
        or (
            auth_management
            and auth_management.get("mode") == "add_user"
            and auth_management.get("step") == "gender"
        )
    )
    ring, pre = collections.deque(maxlen=8), collections.deque(maxlen=10)
    frames, trig, quiet, voiced_n, t0 = [], False, 0, 0, time.time()
    while True:
        if not auth_prompt_queue.empty():
            set_state("standby")
            return None
        if allow_unauthenticated and not gender_setup and (
            auth_mode != "login" or auth_username is not None
        ):
            set_state("standby")
            return None
        if not auth_ready.is_set() and not allow_unauthenticated:
            return None
        if not text_queue.empty(): return None
        f = MIC.read(0.1)
        if f is None:
            if not trig and time.time() - t0 > 20: return None
            continue
        r = rms(f)
        voiced = r > speech_thr() and is_voice(f)
        if not trig:
            pre.append(f); ring.append(voiced)
            if not voiced and r < noise * 3 + 0.003: noise = 0.97 * noise + 0.03 * r
            if sum(ring) >= (3 if spelling_mode or gender_mode else 5):
                trig, frames, voiced_n = True, list(pre), sum(ring)
            elif time.time() - t0 > 20: return None
        else:
            frames.append(f)
            voiced_n += voiced
            quiet = 0 if voiced else quiet + 1
            if quiet >= END_FRAMES or len(frames) > 500: break
    min_voiced_frames = 3 if spelling_mode else 4 if gender_mode else MIN_VOICED_FRAMES
    if voiced_n < min_voiced_frames: return None
    frames = frames[: len(frames) - max(0, quiet - 5)]
    set_state("processing")
    t = transcribe(
        np.concatenate(frames),
        spelling_mode=spelling_mode,
        gender_mode=gender_mode,
        wake_only=silent,
    )
    if silent and (not t or not UNMUTE_REQUEST.fullmatch(clean(t))):
        set_state("standby")
        return None
    if not t or (not spelling_mode and clean(t) in HALLU) or not clean(t):
        set_state(ready_state()); return None
    print(f"You: {t}")
    return t

# ---------- ENGINES ----------
def discover_gemini():
    try:
        found = []
        for m in client.models.list():
            acts = getattr(m, "supported_actions", None) or []
            if acts and "generateContent" not in acts: continue
            n = m.name.replace("models/", "")
            if "flash" in n and not any(x in n for x in ("image", "tts", "live", "lite", "audio", "thinking", "exp")):
                found.append(n)
        for n in sorted(found, reverse=True)[:3]:
            if n not in GEMINI_MODELS: GEMINI_MODELS.append(n)
    except Exception as e:
        print(f"[Gemini discovery skipped: {e}]")

def model_of(name):
    return {"Groq": GROQ_MODEL, "Gemini": GEMINI_MODELS[0], "Ollama": OLLAMA_MODEL}[name]

def groq_stream(msgs):
    s = groq_client.chat.completions.create(model=GROQ_MODEL, messages=msgs, temperature=0.9,
                                            max_tokens=1500, stream=True, reasoning_effort="low")
    for ch in s:
        d = ch.choices[0].delta.content
        if d: yield d

def gemini_stream(msgs):
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[types.Part(text=m["content"])]) for m in msgs[1:]]
    cfg = types.GenerateContentConfig(system_instruction=msgs[0]["content"], temperature=0.9)
    last = None
    for model in list(GEMINI_MODELS):
        set_active("Gemini", model)
        got = False
        try:
            for ch in client.models.generate_content_stream(model=model, contents=contents, config=cfg):
                if ch.text: got = True; yield ch.text
            return
        except Exception as e:
            last = e
            if got: return
    raise last

def ollama_stream(msgs):
    prompt = "\n".join(f"{m['role']}: {m['content']}" for m in msgs) + "\nassistant:"
    r = requests.post("http://localhost:11434/api/generate",
                      json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=60)
    r.raise_for_status()
    yield r.json().get("response", "").strip()

ENGINES = {"Groq": groq_stream, "Gemini": gemini_stream, "Ollama": ollama_stream}

def engine_ok(name):
    try:
        if name == "Ollama":
            try:
                r = requests.get("http://localhost:11434/api/tags", timeout=2); r.raise_for_status()
            except requests.exceptions.RequestException:
                return False, "Ollama isn't running."
            have = [m.get("name", "") for m in r.json().get("models", [])]
            if not any(OLLAMA_MODEL in h for h in have):
                return False, f"the {OLLAMA_MODEL} model isn't installed."
            return True, ""
        if name == "Groq":
            groq_client.models.list(); return True, ""
        if name == "Gemini":
            for m in list(GEMINI_MODELS):
                try:
                    client.models.generate_content(model=m, contents="ping",
                                                   config=types.GenerateContentConfig(max_output_tokens=8))
                    GEMINI_MODELS.remove(m); GEMINI_MODELS.insert(0, m)
                    return True, ""
                except Exception:
                    pass
            return False, "it isn't responding."
    except Exception:
        pass
    return False, "it isn't responding."

def do_engine(name):
    global forced_engine
    key = (name or "").strip().lower()
    names = {"auto": "Auto", "gemini": "Gemini", "groq": "Groq", "ollama": "Ollama"}
    if key not in names: return f"I don't know an engine called {name}, Sir."
    target = names[key]
    if target != "Auto":
        ok, why = engine_ok(target)
        if not ok: return f"I can't use {target} right now, Sir: {why} Staying on {forced_engine}."
        set_active(target, model_of(target))
    forced_engine = target
    push_state()
    return None

def ui_engine(name):
    note = do_engine(name)
    push_chat(new_id(), "jarvis", note or f"Switched to {forced_engine}, Sir.")

def llm_stream(msgs, deep):
    eng = forced_engine
    if eng == "Auto": eng = "Gemini" if deep else "Groq"
    order = {"Gemini": ["Gemini", "Groq", "Ollama"], "Groq": ["Groq", "Gemini", "Ollama"],
             "Ollama": ["Ollama", "Groq", "Gemini"]}[eng]
    for name in order:
        set_active(name, model_of(name))
        got = False
        try:
            for piece in ENGINES[name](msgs):
                if not got and name != order[0] and forced_engine != "Auto":
                    push_chat(new_id(), "jarvis", f"Note: {order[0]} didn't respond, so I answered with {name}.")
                got = True; yield piece
            if got: return
        except Exception:
            if got: return
    yield "Sorry, I can't reach any of my brains right now."

SENT_END = re.compile(r"(?<=[.!?])\s+")
def sentences(chunks):
    buf, first = "", True
    for c in chunks:
        buf += c
        parts = SENT_END.split(buf)
        for p in parts[:-1]:
            if p.strip(): yield p.strip(); first = False
        buf = parts[-1]
        if first and len(buf) > 80 and ", " in buf:
            head, _, tail = buf.rpartition(", ")
            yield head.strip() + ","; buf, first = tail, False
    if buf.strip(): yield buf.strip()

ROUTER_SYS = """You are the intent router for Jarvis, a voice and text assistant. Work out what the user wants from MEANING, never from keywords.
The input may contain speech-recognition mistakes (Jarvis may appear as "service" or "Travis"); infer charitably.

Reply with ONLY one JSON object:
{"intent":"chat|command|ignore","actions":[],"reply":"","speak":null,"deep":false}

intent:
- "command": the user wants Jarvis ITSELF to do something from the action list. Put every needed action in "actions" (in order) and a short natural in-character "reply" (max 12 words, vary the wording, "Sir" only sometimes).
- "chat": anything else addressed to Jarvis (questions, tasks, conversation). Leave actions empty. deep=true only for heavy reasoning, coding, research or long explanations; otherwise false.
- "ignore": background talk not meant for Jarvis, noise, or a bare interruption such as "no", "stop", "jarvis", "okay".
"speak": true only if the user explicitly asks for THIS answer out loud / in voice; false only if they explicitly want it as text; otherwise null.

Actions:
{"do":"minimize","mute":false} shrink to the corner orb. Use mute=true only when the user explicitly asks to mute AND minimize; muting alone must never minimize.
{"do":"mute"} pause voice input without changing the window size.
{"do":"unmute"} resume voice input. While muted, only an explicit unmute command is accepted.
{"do":"maximize"} open to the full view / wake up / come on screen. Does NOT change online or offline.
{"do":"close"} close the Jarvis window and assistant process while leaving the separate wake listener running.
{"do":"offline"} stop answering anything until told to return.
{"do":"online"} resume answering. Does NOT change the window size or position.
{"do":"memory","state":"on|off|wipe"} remember this conversation / stop remembering / erase stored memory.
{"do":"engine","name":"auto|gemini|groq|ollama"} switch the AI brain. groq = fastest, gemini = best for complex work, ollama = local model on this PC, auto = Jarvis picks per question.
{"do":"mode","mode":"text|voice"} open the text chat (answers arrive as text) or go back to voice.
{"do":"output","mode":"voice|text|auto"} standing preference for HOW answers are delivered: always voice, always text, or auto (match how the user asked).

Laptop and account actions (Jarvis enforces administrator approval separately; always emit the action normally):
{"do":"open","target":"URL, app, file, or folder"} open something on the laptop.
{"do":"search","query":"what to search for","open":true,"read":true} search the web in the browser and optionally have Jarvis read the result aloud.
{"do":"file","action":"open|read|write|append|list|find","target":"file name, folder, or path","content":"text to write","query":"file name to search for"} open, read, write, list, or find files.
{"do":"app","name":"chrome|notepad|settings|explorer|terminal|word|excel|outlook|whatsapp|..."} launch an app.
{"do":"shell","command":"exact PowerShell command"} run a command on the laptop.
{"do":"system","action":"volume_up|volume_down|mute|lock|screenshot|sleep|shutdown|restart|cancel_shutdown|minimize_all|show_desktop|list_windows|activate|close_app|open_settings","target":"window or app name when needed"} control Windows.
{"do":"email","action":"open|draft|send","to":"address or contact name","subject":"...","body":"full email body"} open Gmail, draft an email, or send one after approval.
{"do":"whatsapp","to":"phone number or contact name","message":"full message"} draft a WhatsApp message and open the chat after approval.
{"do":"calendar","action":"open|list|create","days":7,"title":"...","start":"ISO 8601 local time","end":"ISO 8601 local time","description":"...","location":"..."} open, read, or add Google Calendar events.
{"do":"message","app":"whatsapp|gmail","action":"read|open|conversation|reply","to":"chat or contact name","message":"reply text","subject":"email subject","limit":8} read unread messages, open a chat, read a conversation, or draft a reply. For a WhatsApp reply use the chat name shown by Jarvis; no phone number is needed.
{"do":"screen","action":"look|act","question":"what to look for","instruction":"what to do on screen"} look at the screen and answer, or prepare clicks/typing on the screen.

Computer-action rules:
- "open the browser and search X" -> search with open=true. Set read=true when the user asks to hear the result; otherwise false.
- Open a file by name -> file. Open a folder -> open with the folder as target. Open an app -> app.
- "run ipconfig" or any command -> shell with exactly what the user asked.
- "open my email" -> email with action open. "draft an email" -> email with action draft. "send an email" -> email with action send.
- For email send, write a complete, natural body from the user's instruction. Never invent a recipient. If the user only gives a name, put that name in "to" (Jarvis resolves contacts).
- "what's on my calendar" -> calendar list with days=1 for today or days=7 for this week. Add an event -> calendar create.
- "do I have new messages" / "read my messages" -> message with app whatsapp or gmail (use both as two actions when the user says messages without naming an app), action read.
- "reply to Srija saying I'm on my way" -> message app whatsapp action reply with the chat name the user gave and the full reply in "message". Jarvis drafts it first.
- "read my chat with Srija" -> message app whatsapp action conversation with to=Srija.
- "what's on my screen" / "look at my screen" -> screen action look with a question.
- "click the blue button", "type this in the field", "scroll down and open settings" -> screen action act with the full instruction. Jarvis plans it and asks for confirmation before touching the mouse or keyboard.
- "read notes.txt" -> file action read. "write meeting notes to notes.txt saying ..." -> file action write with content. "list my Downloads" -> file action list. "find the file called report" -> file action find.
- Use STATE.now to resolve today/tomorrow. If no time is given, use 09:00 local; if no end is given, use one hour later.
- For system controls, map "turn up the volume" to volume_up, "lock my laptop" to lock, "take a screenshot" to screenshot, "switch to Chrome" to activate with target Chrome, and "shut down" to shutdown.
- If a request is unrelated to these actions, use intent "chat" and leave actions empty.
- Do not reveal or repeat passwords, API keys, or PINs in "reply".

STATE (given with each input) describes the situation:
- online=false: Jarvis is offline. Only honour requests that bring him back or move the window (online, maximize, minimize, mode). For anything else addressed to him: intent "command", no actions, and a short reply saying all systems are offline. Talk not for him: "ignore".
- muted=true: Jarvis is silent. Only honor an explicit unmute, wake, or return request; ignore other speech.
- role="admin": the signed-in user is the administrator and laptop actions will run immediately. role="user": the action will wait for an administrator PIN.
Compound requests give several actions, e.g. "go offline and sit in the corner" = offline + minimize(mute=false).

Examples (the user will phrase things differently):
"hold on a second" -> {"intent":"command","actions":[{"do":"mute"}],"reply":"","speak":null,"deep":false}
"tuck yourself away but keep listening" -> {"intent":"command","actions":[{"do":"minimize","mute":false}],"reply":"Of course, I'll stay close.","speak":null,"deep":false}
"Jarvis, terminate" -> {"intent":"command","actions":[{"do":"close"}],"reply":"","speak":null,"deep":false}
"you can shut down for now" -> {"intent":"command","actions":[{"do":"offline"}],"reply":"Going offline, Sir.","speak":null,"deep":false}
"let's use the faster brain" -> {"intent":"command","actions":[{"do":"engine","name":"groq"}],"reply":"Switching to Groq.","speak":null,"deep":false}
"open Chrome and search the weather, read it out" -> {"intent":"command","actions":[{"do":"search","query":"weather today","open":true,"read":true}],"reply":"On it.","speak":null,"deep":false}
"open my Downloads folder" -> {"intent":"command","actions":[{"do":"open","target":"Downloads"}],"reply":"Opening it.","speak":null,"deep":false}
"open the file tax return 2025.pdf" -> {"intent":"command","actions":[{"do":"file","target":"tax return 2025.pdf"}],"reply":"Opening the file.","speak":null,"deep":false}
"send an email to Mom saying I'll be late" -> {"intent":"command","actions":[{"do":"email","action":"send","to":"Mom","subject":"Running late","body":"Hi Mom, I'll be late tonight. I'll let you know when I'm on my way. Love you."}],"reply":"I'll draft it for you.","speak":null,"deep":false}
"what's on my calendar today" -> {"intent":"command","actions":[{"do":"calendar","action":"list","days":1}],"reply":"Checking your calendar.","speak":null,"deep":false}
"schedule a meeting with Alex tomorrow at 3pm" -> {"intent":"command","actions":[{"do":"calendar","action":"create","title":"Meeting with Alex","start":"2026-11-07T15:00:00","end":"2026-11-07T16:00:00"}],"reply":"Adding it.","speak":null,"deep":false}
"run ipconfig" -> {"intent":"command","actions":[{"do":"shell","command":"ipconfig"}],"reply":"Running it.","speak":null,"deep":false}
"lock my laptop" -> {"intent":"command","actions":[{"do":"system","action":"lock"}],"reply":"Locking it.","speak":null,"deep":false}
"do I have any new WhatsApp messages" -> {"intent":"command","actions":[{"do":"message","app":"whatsapp","action":"read"}],"reply":"Checking WhatsApp.","speak":null,"deep":false}
"read my unread email" -> {"intent":"command","actions":[{"do":"message","app":"gmail","action":"read"}],"reply":"Checking your inbox.","speak":null,"deep":false}
"reply to Srija saying I'll call later" -> {"intent":"command","actions":[{"do":"message","app":"whatsapp","action":"reply","to":"Srija","message":"I'll call later."}],"reply":"I'll draft that reply.","speak":null,"deep":false}
"what's on my screen" -> {"intent":"command","actions":[{"do":"screen","action":"look","question":"Describe what is on the screen and point out anything important."}],"reply":"Let me look.","speak":null,"deep":false}
"click the Compose button and type hello" -> {"intent":"command","actions":[{"do":"screen","action":"act","instruction":"Click the Compose button, then type hello in the message body."}],"reply":"I'll prepare that.","speak":null,"deep":false}
"read the file notes.txt" -> {"intent":"command","actions":[{"do":"file","action":"read","target":"notes.txt"}],"reply":"Reading it.","speak":null,"deep":false}
"list my Downloads folder" -> {"intent":"command","actions":[{"do":"file","action":"list","target":"Downloads"}],"reply":"Listing it.","speak":null,"deep":false}
"tell me a joke out loud" -> {"intent":"chat","actions":[],"reply":"","speak":true,"deep":false}
"explain how TCP congestion control works" -> {"intent":"chat","actions":[],"reply":"","speak":null,"deep":true}
"no" -> {"intent":"ignore","actions":[],"reply":"","speak":null,"deep":false}"""

OFFLINE_LINES = ["All systems are offline, Sir.", "I'm offline at the moment, Sir.", "Systems are offline, Sir."]

CONTROL_REQUEST = re.compile(
    r"\b(?:close|quit|exit|terminate|shutdown|shut down|"
    r"mute|unmute|deafen|deaf|stop listening|start listening|listen again|"
    r"hold on|hush|give me a moment|wake up|bring me back|come back|shut down|"
    r"go offline|come online|go online|turn (?:(?:the|your) )?(?:mic|microphone) (?:on|off)|"
    r"(?:enable|disable) (?:(?:the|your) )?(?:mic|microphone)|"
    r"minimi[sz]e|m[a]ximi[sz]e|"
    r"(?:switch|change) (?:to )?(?:the )?(?:ai )?(?:engine|model)|"
    r"(?:faster|best|local) brain|sit in (?:the )?corner|"
    r"use (?:gemini|groq|ollama|auto)|"
    r"(?:turn|switch) (?:the )?memory (?:on|off)|"
    r"remember|forget|wipe (?:my )?memory|clear (?:my )?memory|"
    r"(?:switch|change|set) (?:to )?(?:text|voice) mode|"
    r"(?:speak|talk) (?:to me )?(?:in )?(?:text|voice)|"
    r"(?:answer|respond|reply) (?:in )?(?:text|voice)|"
    r"go quiet|stop talking|be quiet)\b",
    re.IGNORECASE,
)
COMPUTER_REQUEST = re.compile(
    r"\b(?:open|launch|start|run)\s+(?:the\s+|my\s+|a\s+)?"
    r"(?:browser|chrome|edge|firefox|notepad|calculator|calc|paint|settings|"
    r"explorer|file explorer|terminal|powershell|cmd|command prompt|word|excel|"
    r"powerpoint|outlook|spotify|whatsapp|vscode|visual studio code|task manager|"
    r"control panel|file|folder|document|downloads|desktop|documents|pictures|"
    r"email|gmail|mail|inbox|calendar|google calendar|"
    r"command|script)\b|"
    r"\bopen\s+(?:the\s+|my\s+|a\s+)?[\w][\w .'()\-]*\."
    r"(?:pdf|docx?|xlsx?|pptx?|txt|csv|png|jpe?g|gif|mp3|mp4|zip|rar|7z|"
    r"py|js|html?|json)\b|"
    r"\b(?:search|google|look\s+up|find\s+out|browse)\b|"
    r"\b(?:send|draft|compose|write|check|read|show)\s+(?:me\s+)?(?:an?\s+)?"
    r"(?:email|mail|inbox|gmail)\b|"
    r"\b(?:send|message|text)\s+(?:a\s+|an?\s+)?(?:whatsapp|whats\s+app)\b|"
    r"\b(?:draft|compose)\s+(?:a\s+)?(?:whatsapp|whats\s+app)\b|"
    r"\b(?:calendar|schedule|appointment|meeting|event)\b|"
    r"\b(?:run|execute)\s+(?:a\s+)?(?:command|powershell|shell|script)\b|"
    r"\b(?:lock|unlock)\s+(?:the\s+|my\s+)?(?:pc|computer|laptop|screen|workstation)\b|"
    r"\b(?:take|grab|capture)\s+(?:a\s+)?screenshot\b|"
    r"\b(?:volume|brightness)\b|"
    r"\b(?:shut\s*down|restart|reboot|sleep)\s+(?:the\s+|my\s+)?(?:pc|computer|laptop|system)\b|"
    r"\b(?:switch|focus|activate|close|minimi[sz]e)\s+(?:to\s+)?(?:the\s+)?"
    r"(?:window|app|application)\b|"
    r"\b(?:switch|focus|activate|close|minimi[sz]e)\s+(?:to\s+)?(?:the\s+)?"
    r"[\w][\w .'()\-]*\s+(?:window|app|application)\b|"
    r"\b(?:list|show)\s+(?:my\s+)?(?:open\s+)?windows\b|"
    r"\b(?:read|check|open|show|any|new|unread)\b[^\r\n]{0,40}"
    r"\b(?:messages?|whats\s*app|inbox|chats?|email|gmail|mail)\b|"
    r"\b(?:reply|respond)\s+(?:to\s+)?[\w][\w .'()\-]{0,40}\s+"
    r"(?:saying|that|with|on\s+whats\s*app)\b|"
    r"\b(?:look\s+at|see|read|check|what'?s\s+on|what\s+is\s+on)\s+"
    r"(?:my\s+|the\s+)?(?:screen|display)\b|"
    r"\b(?:click|double[- ]?click|right[- ]?click|scroll|type|press|drag)\b"
    r"[^\r\n]{0,60}\b(?:on\s+(?:my\s+|the\s+)?screen|on[- ]screen|there|button|field)\b|"
    r"\b(?:read|write|append|open|list|find|search)\s+(?:the\s+|my\s+|a\s+)?"
    r"(?:file|folder|directory|notes?|document)\b|"
    r"\b(?:list|show)\s+(?:the\s+|my\s+)?"
    r"(?:files?|folders?|directories|downloads|documents|desktop|pictures)\b",
    re.IGNORECASE,
)
PRIVATE_ON_REQUEST = re.compile(
    r"\b(?:go|switch|turn|keep|make|start)\s+(?:(?:this|it|the)\s+)?"
    r"(?:discussion\s+)?(?:incognito|private)\b|"
    r"\b(?:incognito|private)\s+mode\b",
    re.IGNORECASE,
)
PRIVATE_OFF_REQUEST = re.compile(
    r"\b(?:leave|exit|stop|disable|turn off|switch off)\s+(?:the\s+)?"
    r"(?:incognito|private)(?:\s+mode)?\b|"
    r"\b(?:go|switch)\s+back\s+to\s+(?:cloud|normal|regular)\b",
    re.IGNORECASE,
)
PERMANENT_DELETE_CHAT_REQUEST = re.compile(
    r"\b(?:permanently|forever|completely)\s+(?:delete|erase|remove)\b"
    r".{0,50}\b(?:chat|conversation)s?(?:\s+history)?\b|"
    r"\b(?:delete|erase|remove)\s+(?:my\s+)?(?:chat|conversation)s?"
    r"(?:\s+history)?\s+permanently\b",
    re.IGNORECASE,
)
ARCHIVE_CHAT_REQUEST = re.compile(
    r"\b(?:delete|clear|hide|archive)\s+(?:(?:all|the)\s+)?"
    r"(?:my\s+)?(?:chat|conversation)s?(?:\s+history)?\b",
    re.IGNORECASE,
)
CLOSE_REQUEST = re.compile(
    r"\bjarvis\b.{0,40}\b(?:close|quit|exit|terminate|shutdown|shut down)\b|"
    r"\b(?:close|quit|exit|terminate|shutdown|shut down)\b.{0,40}\b"
    r"(?:jarvis|yourself|the app|the application|the ui|this app|the window|this window)\b",
    re.IGNORECASE,
)
ADMIN_TAKEOVER_REQUEST = re.compile(
    r"\b(?:jarvis[\s,:-]+)?admin[\s,:-]+taking[\s,:-]+control\b|"
    r"\badmin[\s,:-]+take[\s,:-]+control\b|"
    r"\b(?:switch|witch|change)\s+(?:the\s+)?(?:current\s+)?"
    r"(?:user\s+)?(?:over\s+)?to\s+admin\b|"
    r"\b(?:switch|change)\s+(?:the\s+)?admin\s+user\b",
    re.IGNORECASE,
)
ADD_USER_REQUEST = re.compile(
    r"\badd\s+(?:a\s+)?new\s+user(?:\s+(?:named|called)\s+([^.!?]+))?",
    re.IGNORECASE,
)
USER_ACTION_REQUEST = re.compile(
    r"\b(?P<operation>permanently\s+delete|delete|disable|enable|restore)\s+"
    r"(?:the\s+|a\s+)?(?:user|account)"
    r"(?:\s+(?:named|called)\s+)?(?:\s+(?P<username>.+?))?[.!?]*$",
    re.IGNORECASE,
)
END_SESSION_REQUEST = re.compile(
    r"^(?:jarvis )?(?:please )?(?:(?:i want to|can you|could you) )?"
    r"(?:end|terminate|finish|close|log out of|logout of) "
    r"(?:the |my )?(?:current )?session$|^(?:jarvis )?(?:please )?sign out$",
    re.IGNORECASE,
)
MUTE_MINIMIZE_REQUEST = re.compile(
    r"^(?:jarvis )?(?:please )?(?:mute and minimi[sz]e|minimi[sz]e and mute)"
    r"(?: (?:the )?(?:mic|microphone))?$",
    re.IGNORECASE,
)
MUTE_REQUEST = re.compile(
    r"^(?:jarvis )?(?:please )?mute(?: (?:me|yourself|(?:the )?(?:mic|microphone)))?$",
    re.IGNORECASE,
)
UNMUTE_REQUEST = re.compile(
    r"^(?:jarvis )?unmute(?: (?:me|yourself|(?:the )?(?:mic|microphone)))?$",
    re.IGNORECASE,
)
DEEP_REQUEST = re.compile(
    r"\b(?:in depth|deep dive|comprehensive|thorough|step by step|research)\b",
    re.IGNORECASE,
)
OUTPUT_REQUEST = re.compile(
    r"\b(?:always\s+)?(?:(?:answer|respond|reply)\s+(?:always\s+)?|"
    r"(?:speak|talk)\s+(?:to me\s+)?(?:always\s+)?)(?:in\s+)?(?P<mode>voice|text)\b",
    re.IGNORECASE,
)
VOICE_REQUEST = re.compile(
    r"\b(?:out\s+loud|aloud|in\s+(?:your\s+)?voice|"
    r"speak\s+(?:this|that|it|the\s+answer)\s+(?:out\s+loud|aloud)|"
    r"read\s+(?:this|that|it|the\s+answer)\s+(?:out\s+loud|aloud))\b",
    re.IGNORECASE,
)
REPEAT_REQUEST = re.compile(
    r"\b(?:(?:read|repeat|say)\s+(?:that|it|your\s+(?:last|previous)\s+(?:reply|answer)|"
    r"the\s+(?:last|previous)\s+(?:reply|answer))|(?:repeat|read)\s+(?:your\s+)?"
    r"last\s+(?:reply|answer))(?:\s+(?:back\s+)?(?:out\s+loud|aloud|in\s+(?:your\s+)?voice))?\b",
    re.IGNORECASE,
)

def classify(text, source):
    ctx = " | ".join(f"{m['role']}: {m['content'][:90]}" for m in recent[-4:]) or "none"
    st = {"online": online, "minimised": mini, "muted": silent, "memory": memory_on, "engine": forced_engine,
          "text_mode": text_mode, "output_pref": output_pref,
          "now": datetime.now().astimezone().isoformat(timespec="minutes"),
          "role": active_user["role"] if active_user else None}
    user = f"STATE: {json.dumps(st)}\nRECENT: {ctx}\nINPUT ({source}): {text}"
    for model in dict.fromkeys((ROUTER_MODEL, GROQ_MODEL)):
        try:
            kw = dict(model=model, messages=[{"role": "system", "content": ROUTER_SYS}, {"role": "user", "content": user}],
                      temperature=0, max_tokens=1200,
                      response_format={"type": "json_object"})
            if model == GROQ_MODEL: kw["reasoning_effort"] = "low"
            raw = groq_client.chat.completions.create(**kw).choices[0].message.content or ""
            d = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            acts = [a for a in (d.get("actions") or []) if isinstance(a, dict) and a.get("do")]
            intent = d.get("intent") if d.get("intent") in ("chat", "command", "ignore") else "chat"
            speak = d.get("speak") if isinstance(d.get("speak"), bool) else None
            return {"intent": intent, "actions": acts, "reply": str(d.get("reply") or "").strip(),
                    "speak": speak, "deep": bool(d.get("deep"))}
        except Exception as e:
            print(f"[Router {model} error: {e}]")
    return {"intent": "chat", "actions": [], "reply": "", "speak": None, "deep": False}

def enforce(route, source):
    dos = {a.get("do") for a in route["actions"]}
    if source == "voice" and silent and route["intent"] != "ignore" and not (dos & {"maximize", "online", "unmute"}):
        return {**route, "intent": "ignore", "actions": [], "reply": ""}
    if not online:
        route["actions"] = [a for a in route["actions"] if a.get("do") in ("online", "maximize", "minimize", "mode", "close")]
        if route["intent"] == "chat" or (route["intent"] == "command" and not route["actions"] and not route["reply"]):
            return {**route, "intent": "command", "actions": [], "reply": random.choice(OFFLINE_LINES)}
    return route

def pending_public():
    if not pending_action:
        return None
    public = {
        "stage": pending_action.get("stage", ""),
        "label": pending_action.get("label", ""),
        "source": pending_action.get("source", "text"),
    }
    if pending_action.get("draft"):
        public["draft"] = dict(pending_action["draft"])
    if pending_action.get("warning"):
        public["warning"] = pending_action["warning"]
    if pending_action.get("command"):
        public["command"] = pending_action["command"]
    if pending_action.get("screen_plan"):
        public["screen_plan"] = dict(pending_action["screen_plan"])
    return public


def pending_expired():
    return bool(
        pending_action
        and time.time() - pending_action.get("created", 0) > PENDING_TIMEOUT
    )


def clear_pending():
    global pending_action, auth_error
    with auth_lock:
        pending_action = None
        auth_error = ""
    auth_message()


def set_pending(stage, actions, source, label, **extra):
    global pending_action
    pending_action = {
        "stage": stage,
        "actions": [dict(action) for action in actions if isinstance(action, dict)],
        "source": source,
        "label": label,
        "created": time.time(),
        **extra,
    }


def format_draft(draft):
    kind = draft.get("kind")
    if kind == "email":
        return (
            "EMAIL DRAFT\n"
            f"To: {draft.get('to', '')}\n"
            f"Subject: {draft.get('subject', '')}\n\n"
            f"{draft.get('body', '')}"
        )
    if kind == "whatsapp":
        target = draft.get("to", "")
        if draft.get("phone"):
            target = f"{target} ({draft.get('phone')})"
        elif draft.get("chat"):
            target = f"{target} (WhatsApp chat)"
        return (
            "WHATSAPP DRAFT\n"
            f"To: {target}\n\n"
            f"{draft.get('message', '')}"
        )
    return json.dumps(draft, indent=2, ensure_ascii=False)


def show_draft(draft):
    text = format_draft(draft)
    push_chat(new_id(), "jarvis", text, persist=True)
    return text


def build_draft(action):
    name = action.get("do")
    if name == "email":
        return jarvis_services.build_email_draft(
            action.get("to", ""),
            action.get("subject", ""),
            action.get("body", ""),
        )
    if name == "whatsapp":
        return jarvis_services.build_whatsapp_draft(
            action.get("to", ""),
            action.get("message", ""),
        )
    if name == "message":
        app = str(action.get("app", "whatsapp")).lower()
        if app == "whatsapp":
            return jarvis_services.build_whatsapp_chat_draft(
                action.get("to") or action.get("chat", ""),
                action.get("message", ""),
            )
        if app in ("gmail", "email"):
            return jarvis_services.build_email_draft(
                action.get("to", ""),
                action.get("subject", ""),
                action.get("message") or action.get("body", ""),
            )
    raise ActionError("I don't know how to draft that action.")


def execute_action(action, source="text", speak=None):
    name = action.get("do")
    if name == "open":
        target = action.get("target") or action.get("name") or action.get("query")
        if not target:
            raise ActionError("What should I open?")
        target_text = str(target).strip().casefold()
        if target_text in {"email", "gmail", "mail", "inbox", "my email", "my gmail"}:
            return f"Opened {jarvis_services.open_email()}."
        if target_text in {"calendar", "google calendar", "my calendar"}:
            return f"Opened {jarvis_services.open_calendar()}."
        opened = jarvis_pc.open_any(str(target))
        return f"Opened {opened}."
    if name == "search":
        query = action.get("query") or action.get("target")
        if not query:
            raise ActionError("What should I search for?")
        outcome = jarvis_pc.web_search(
            str(query), open_browser=action.get("open", True) is not False
        )
        full = jarvis_pc.format_search_results(outcome)
        read_aloud = action.get("read")
        if read_aloud is None:
            read_aloud = want_voice(source, speak)
        else:
            read_aloud = bool(read_aloud)
        if speak is True:
            read_aloud = True
        if read_aloud:
            push_chat(new_id(), "jarvis", full, persist=True)
            return jarvis_pc.summarize_search_results(outcome)
        return full
    if name == "file":
        mode = str(action.get("action", "open")).lower()
        target = action.get("target") or action.get("path") or ""
        if mode == "read":
            if not target:
                raise ActionError("Which file should I read?")
            return jarvis_pc.read_file(str(target))
        if mode in ("write", "append"):
            if not target:
                raise ActionError("Which file should I write to?")
            if "content" not in action and "text" not in action:
                raise ActionError("What should I write in that file?")
            content = action.get("content", action.get("text", ""))
            return jarvis_pc.write_file(
                str(target), str(content), append=(mode == "append")
            )
        if mode == "list":
            return jarvis_pc.list_directory(str(target))
        if mode == "find":
            query = action.get("query") or target
            if not query:
                raise ActionError("What file name should I look for?")
            return jarvis_pc.find_files(str(query))
        if not target:
            raise ActionError("Which file should I open?")
        opened = jarvis_pc.open_path(str(target))
        return f"Opened {opened}."
    if name == "app":
        app_name = action.get("name") or action.get("target")
        if not app_name:
            raise ActionError("Which app should I open?")
        app_text = str(app_name).strip().casefold()
        if app_text in {"email", "gmail", "mail", "inbox"}:
            return f"Opened {jarvis_services.open_email()}."
        if app_text in {"calendar", "google calendar"}:
            return f"Opened {jarvis_services.open_calendar()}."
        return f"Opened {jarvis_pc.launch_app(str(app_name))}."
    if name == "shell":
        command = action.get("command")
        if not command:
            raise ActionError("What command should I run?")
        result = jarvis_pc.run_powershell(str(command))
        full = jarvis_pc.format_shell_result(result)
        if want_voice(source, speak) and len(full) > 500:
            push_chat(new_id(), "jarvis", full, persist=True)
            return full[:500].rsplit(" ", 1)[0] + "."
        return full
    if name == "system":
        return jarvis_pc.system_action(
            str(action.get("action", "")), str(action.get("target", ""))
        )
    if name == "email":
        mode = str(action.get("action", "send")).lower()
        if mode == "open":
            return f"Opened {jarvis_services.open_email()}."
        if mode == "draft":
            draft = build_draft(action)
            show_draft(draft)
            return "I've put the draft in the chat. Nothing has been sent."
        raise ActionError("I need to draft that email before sending it.")
    if name == "whatsapp":
        raise ActionError("I need to draft that WhatsApp message before sending it.")
    if name == "calendar":
        mode = str(action.get("action", "list")).lower()
        if mode == "open":
            return f"Opened {jarvis_services.open_calendar()}."
        if mode == "create":
            return jarvis_services.create_event(
                action.get("title") or action.get("summary", ""),
                action.get("start", ""),
                action.get("end", ""),
                action.get("description", ""),
                action.get("location", ""),
            )
        return jarvis_services.list_events(int(action.get("days", 7) or 7))
    if name == "message":
        app = str(action.get("app", "whatsapp")).lower()
        mode = str(action.get("action", "read")).lower()
        target = action.get("to") or action.get("chat") or ""
        if app == "whatsapp":
            if mode in ("read", "list", "unread"):
                full = jarvis_whatsapp.format_unread_chats(
                    jarvis_whatsapp.list_unread_chats(
                        int(action.get("limit", 8) or 8)
                    )
                )
                if want_voice(source, speak) and len(full) > 700:
                    push_chat(new_id(), "jarvis", full, persist=True)
                    return full[:700].rsplit(" ", 1)[0] + "."
                return full
            if mode == "open":
                return f"Opened the WhatsApp chat with {jarvis_whatsapp.open_chat(target)}."
            if mode == "conversation":
                if not target:
                    raise ActionError("Which WhatsApp chat should I read?")
                return jarvis_whatsapp.read_conversation(
                    target, str(action.get("question", ""))
                )
            raise ActionError("I need to draft that WhatsApp reply first.")
        if app in ("gmail", "email"):
            if mode in ("read", "list", "unread"):
                return jarvis_services.format_unread_email(
                    jarvis_services.read_unread_email(
                        int(action.get("limit", 5) or 5)
                    )
                )
            if mode == "open":
                return f"Opened {jarvis_services.open_email()}."
            raise ActionError("I need to draft that email reply first.")
        raise ActionError(f"I don't know how to read {app} messages.")
    if name == "screen":
        mode = str(action.get("action", "look")).lower()
        if mode in ("act", "action", "do"):
            raise ActionError("I need to prepare that screen action first.")
        question = action.get("question") or action.get("target") or (
            "Describe what is on the screen and point out anything important."
        )
        answer = jarvis_screen.look(str(question))
        if want_voice(source, speak) and len(answer) > 700:
            push_chat(new_id(), "jarvis", answer, persist=True)
            return answer[:700].rsplit(" ", 1)[0] + "."
        return answer
    raise ActionError(f"I don't know how to {describe_action(action)}.")


def run_actions(
    acts,
    source="text",
    authorized=None,
    confirmed_danger=False,
    confirmed_screen=False,
    speak=None,
):
    global online, silent, output_pref
    if authorized is None:
        authorized = bool(active_user and active_user["role"] == "admin")
    notes = []
    for index, action in enumerate(acts):
        if not isinstance(action, dict):
            continue
        name = action.get("do")
        if not name:
            continue

        if name == "close": close_jarvis()
        elif name == "minimize": act_minimize(bool(action["mute"]) if "mute" in action else None)
        elif name == "maximize": act_maximize()
        elif name == "mute": set_silent(True)
        elif name == "unmute": set_silent(False)
        elif name == "offline": online = False
        elif name == "online":
            online, silent = True, False
            if MIC is not None:
                try:
                    MIC.set_muted(False)
                except Exception as e:
                    print(f"[Microphone unmute error: {e}]")
        elif name == "memory":
            state_value = str(action.get("state", "")).lower()
            if state_value == "wipe": wipe_memory()
            else: set_memory(state_value == "on")
        elif name == "engine":
            note = do_engine(action.get("name")) or None
            if note:
                notes.append(note)
        elif name == "mode":
            set_text_mode(str(action.get("mode", "")).lower() == "text")
        elif name == "output":
            mode = str(action.get("mode", "auto")).lower()
            output_pref = mode if mode in ("voice", "text", "auto") else "auto"
        else:
            if is_sensitive(action):
                if not authorized:
                    set_pending(
                        "admin_pin",
                        acts[index:],
                        source,
                        describe_action(action),
                        speak=speak,
                    )
                    auth_message()
                    return (
                        f"This needs administrator approval: {describe_action(action)}. "
                        "Enter the administrator PIN in the window, or say cancel."
                    )
                if requires_approval(action):
                    try:
                        draft = build_draft(action)
                    except ActionError as error:
                        return str(error)
                    show_draft(draft)
                    set_pending(
                        "confirm_send",
                        [action],
                        source,
                        describe_action(action),
                        draft=draft,
                        authorized=True,
                        speak=speak,
                    )
                    auth_message()
                    return (
                        "I've put the draft in the chat. Say send it to go ahead, "
                        "or say cancel."
                    )
                if requires_screen_confirmation(action) and not confirmed_screen:
                    try:
                        screen_plan = jarvis_screen.prepare_screen_action(
                            str(
                                action.get("instruction")
                                or action.get("target")
                                or action.get("question")
                                or ""
                            )
                        )
                    except ActionError as error:
                        return str(error)
                    set_pending(
                        "confirm_screen",
                        [action],
                        source,
                        describe_action(action),
                        screen_plan=screen_plan,
                        authorized=True,
                        speak=speak,
                    )
                    auth_message()
                    summary = str(
                        screen_plan.get("summary") or describe_action(action)
                    ).rstrip(" .")
                    return (
                        f"I've prepared the screen action: {summary}. "
                        "Review the plan in the window and confirm, or say cancel."
                    )
                if is_destructive(action) and not confirmed_danger:
                    command = action.get("command") or action.get("action", "")
                    set_pending(
                        "danger_confirm",
                        acts[index:],
                        source,
                        describe_action(action),
                        warning=(
                            "This action can change or damage the machine. "
                            "Only confirm if you are sure."
                        ),
                        command=str(command),
                        authorized=True,
                        speak=speak,
                    )
                    auth_message()
                    return (
                        "That looks destructive. Say confirm dangerous to proceed, "
                        "or say cancel."
                    )
            try:
                result = execute_action(action, source, speak=speak)
            except ActionError as error:
                return str(error)
            except Exception as error:
                print(f"[Action error: {error}]")
                return "I couldn't complete that action."
            if result:
                if is_sensitive(action):
                    audit_action(action, result)
                notes.append(result)
    push_state()
    return " ".join(notes).strip() or None


def resume_actions(
    actions,
    source="text",
    authorized=True,
    confirmed_danger=False,
    confirmed_screen=False,
    speak=None,
):
    global pending_action
    pending_action = None
    note = run_actions(
        actions,
        source,
        authorized=authorized,
        confirmed_danger=confirmed_danger,
        confirmed_screen=confirmed_screen,
        speak=speak,
    )
    auth_message()
    if note:
        reply_text(note, source, speak)


def authorize_pending_action(pin):
    global pending_action, auth_error
    request = pending_action
    if not request or request.get("stage") != "admin_pin":
        raise AuthenticationError(
            "There is no action waiting for administrator approval."
        )
    if pending_expired():
        clear_pending()
        raise AuthenticationError("That authorization request expired. Please ask again.")
    auth_store.authenticate(DEFAULT_ADMIN_NAME, pin, require_admin=True)
    actions = list(request.get("actions") or [])
    source = request.get("source", "text")
    speak = request.get("speak")
    with auth_lock:
        auth_error = ""
    auth_message()
    resume_actions(actions, source, authorized=True, speak=speak)


def confirm_pending_action():
    global pending_action, auth_error
    request = pending_action
    if not request:
        raise AuthenticationError("There is no pending action to confirm.")
    if pending_expired():
        clear_pending()
        raise AuthenticationError("That action expired. Please ask again.")
    stage = request.get("stage")
    source = request.get("source", "text")
    speak = request.get("speak")
    if stage == "danger_confirm":
        resume_actions(
            list(request.get("actions") or []),
            source,
            authorized=True,
            confirmed_danger=True,
            speak=speak,
        )
        return
    if stage == "confirm_screen":
        action = (request.get("actions") or [{}])[0]
        plan = request.get("screen_plan") or {}
        try:
            message = jarvis_screen.execute_plan(plan)
        except ActionError as error:
            with auth_lock:
                auth_error = str(error)
            auth_message()
            return
        with auth_lock:
            pending_action = None
            auth_error = ""
        auth_message()
        audit_action(action, message)
        reply_text(
            message,
            source,
            speak if speak is not None else (True if source == "voice" else None),
        )
        return
    if stage != "confirm_send":
        raise AuthenticationError("That action isn't ready to confirm.")
    action = (request.get("actions") or [{}])[0]
    draft = request.get("draft") or {}
    try:
        if draft.get("kind") == "email" or action.get("do") == "email":
            sent_to = jarvis_services.send_email(draft)
            message = f"Sent the email to {sent_to}."
        elif draft.get("kind") == "whatsapp":
            if draft.get("chat"):
                message = jarvis_services.open_whatsapp_chat(
                    draft.get("chat", ""), draft.get("message", "")
                )
            else:
                message = jarvis_services.open_whatsapp(
                    draft.get("to", ""),
                    draft.get("message", ""),
                    draft.get("phone"),
                )
        else:
            raise ActionError("I don't know how to confirm that action.")
    except ActionError as error:
        with auth_lock:
            auth_error = str(error)
        auth_message()
        return
    with auth_lock:
        pending_action = None
        auth_error = ""
    auth_message()
    audit_action(action, message)
    reply_text(message, source, speak if speak is not None else (True if source == "voice" else None))


def cancel_pending_action():
    global pending_action, auth_error
    source = (pending_action or {}).get("source", "text")
    with auth_lock:
        pending_action = None
        auth_error = ""
    auth_message()
    reply_text("Cancelled.", source)

def to_np(a):
    if hasattr(a, "detach"): a = a.detach().cpu().numpy()
    return np.asarray(a, dtype=np.float32).reshape(-1)

def windows_speech_fallback(text):
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$text = [Console]::In.ReadToEnd(); "
        "$voice.Speak($text); "
        "$voice.Dispose()"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input=text, capture_output=True, text=True, timeout=90, check=True,
    )

def get_kokoro_pipeline():
    global kokoro_pipeline
    if kokoro_pipeline is None:
        with kokoro_lock:
            if kokoro_pipeline is None:
                from kokoro import KPipeline
                kokoro_pipeline = KPipeline(lang_code="b")
    return kokoro_pipeline

def warm_kokoro():
    global kokoro_warm_started
    with auth_lock:
        if kokoro_warm_started:
            return
        kokoro_warm_started = True
    try:
        get_kokoro_pipeline()
        print("[TTS model is ready.]")
    except Exception as error:
        print(f"[TTS warmup error: {error}]")

def speak_auth_prompt(text):
    set_state("speaking")
    try:
        windows_speech_fallback(text)
    except Exception as error:
        print(f"[Authentication voice prompt error: {error}]")
    finally:
        if MIC is not None:
            MIC.flush()
        set_state("listening" if MIC is not None and not MIC.muted and not silent else "standby")

def typed_waiting(): return not text_queue.empty()

def valid_barge(text, said):
    c = clean(text)
    if not c or c in HALLU: return False
    w = c.split()
    if len(w) >= 3:
        spoken = set(clean(" ".join(said)).split())
        if sum(x in spoken for x in w) / len(w) >= 0.75: return False
    return True

def barge_monitor(stop, done, out, said):
    global echo_g, barge_boost
    ring, pre = collections.deque(maxlen=8), collections.deque(maxlen=10)
    try:
        while not done.is_set() and not stop.is_set():
            f = MIC.read(0.1)
            if f is None: continue
            r, lvl = rms(f), SPK.echo_level()
            thr = max(BARGE_MIN, noise * 4, echo_g * lvl * 1.6 + noise * 2) * barge_boost
            user = r > thr and is_voice(f)
            pre.append(f); ring.append(user)
            barge_boost = max(1.0, barge_boost * 0.9995)
            if not user and lvl > 0.02:
                echo_g = 0.97 * echo_g + 0.03 * min(r / lvl, 3.0)
            if sum(ring) < 4: continue
            lvl_trig = lvl
            SPK.pause()
            frames, quiet = list(pre), 0
            while len(frames) < 130:
                f = MIC.read(0.1)
                if f is None: continue
                frames.append(f)
                voiced = rms(f) > max(BARGE_MIN * 0.6, noise * 3) and is_voice(f)
                quiet = 0 if voiced else quiet + 1
                if quiet >= 14: break
            text = transcribe(np.concatenate(frames))
            if text and valid_barge(text, said):
                out["text"] = text; stop.set(); return
            SPK.resume()
            if lvl_trig > 0.02:
                echo_g = max(echo_g, min(float(np.mean([rms(x) for x in frames])) / lvl_trig, 3.0) * 1.1)
            barge_boost = min(barge_boost * 1.2, 2.5)
            ring.clear(); pre.clear()
    except Exception:
        pass
    finally:
        if not stop.is_set(): SPK.resume()

def speak_stream(sent_iter, said, mid):
    global LEAD
    stop, done, out = threading.Event(), threading.Event(), {"text": None}
    q = queue.Queue(maxsize=12)
    audio_duration = [0.0]

    def put(item):
        while not stop.is_set():
            try: q.put(item, timeout=0.1); return
            except queue.Full: pass

    def synth():
        synthesis_failed = False
        fallback_text = ""
        try:
            for sent in sent_iter:
                if stop.is_set(): break
                sent = re.sub(r"[*#_`~>]", "", sent).strip()
                if not sent: continue
                said.append(sent); print(f"Jarvis: {sent}")
                push_chat(mid, "jarvis", " ".join(said))
                try:
                    produced_audio = False
                    for _, _, a in get_kokoro_pipeline()(sent, voice=VOICE, speed=1.08):
                        if stop.is_set(): break
                        audio = to_np(a)
                        if audio.size:
                            produced_audio = True
                            audio_duration[0] += len(audio) / TTS_SR
                            put(audio)
                    if not produced_audio and not stop.is_set():
                        raise RuntimeError("Kokoro returned no audio for the sentence.")
                except Exception as e:
                    synthesis_failed = True
                    fallback_text = sent
                    print(f"[TTS synthesis error: {e}]")
                    break
        except Exception as e:
            synthesis_failed = True
            fallback_text = " ".join(said)
            print(f"[Speech generation error: {e}]")
        finally:
            if synthesis_failed and fallback_text and not stop.is_set():
                try:
                    set_state("speaking")
                    windows_speech_fallback(fallback_text)
                except Exception as e:
                    print(f"[Windows speech fallback error: {e}]")
            put(None)

    SPK.resume()
    mon = None
    if BARGE_MODE:
        mon = threading.Thread(target=barge_monitor, args=(stop, done, out, said), daemon=True)
        mon.start()
    threading.Thread(target=synth, daemon=True).start()

    lead = LEAD
    pending, pend_s, started, ended, underrun, t_first = [], 0.0, False, False, False, None

    def begin():
        nonlocal started
        for p in pending: SPK.push(p)
        pending.clear(); started = True; set_state("speaking")

    while not stop.is_set():
        if typed_waiting(): stop.set(); break                
        try:
            a = q.get(timeout=0.05)
        except queue.Empty:
            if started and SPK.queued == 0 and not ended and not SPK.pausing: underrun = True
            if not started and pending and time.time() - t_first > 2.5: begin()
            continue
        if a is None: ended = True; break
        if started: SPK.push(a)
        else:
            t_first = t_first or time.time()
            pending.append(a); pend_s += len(a) / TTS_SR
            if pend_s >= lead: begin()
    if not stop.is_set() and pending and not started: begin()
    playback_deadline = time.monotonic() + max(12.0, audio_duration[0] * 2.5 + 5.0)
    while not stop.is_set() and SPK.queued > 0:
        if typed_waiting(): stop.set(); break
        if time.monotonic() >= playback_deadline:
            print(f"[Audio output error: playback queue did not drain ({SPK.queued} samples remain).]")
            SPK.stop_now()
            break
        time.sleep(0.02)
    if stop.is_set(): SPK.stop_now()

    if underrun: LEAD = min(LEAD + 0.5, 3.0)
    elif started: LEAD = max(0.6, LEAD - 0.05)

    done.set()
    if mon: mon.join(timeout=12)
    set_state("listening" if online and not silent else "standby")
    if out["text"] is None:
        time.sleep(0.45); MIC.flush()                        
    return out["text"]

def text_stream(chunks, mid):
    buf, last = "", 0.0
    for c in chunks:
        buf += c
        if time.time() - last > 0.06:
            push_chat(mid, "jarvis", buf); last = time.time()
    buf = buf.strip() or "…"
    push_chat(mid, "jarvis", buf, persist=True)
    print(f"Jarvis (text): {buf}")
    return buf

def want_voice(source, flag):
    if flag is not None: return flag                         
    if output_pref == "voice": return True
    if output_pref == "text": return False
    return source == "voice" and not text_mode               

def reply_text(text, source, flag=None):
    mid = new_id()
    if want_voice(source, flag): return speak_stream(iter([text]), [], mid)
    push_chat(mid, "jarvis", text); print(f"Jarvis (text): {text}")
    set_state("listening" if online and not silent else "standby")
    return None

def say(text):
    return speak_stream(iter([text]), [], new_id())

def greet():
    h = datetime.now().hour
    tod = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    username = active_user["username"] if active_user else "there"
    gender = active_user.get("gender") if active_user else None
    title = "Sir" if gender == "male" else "Ma'am" if gender == "female" else username
    return random.choice([f"Good {tod}, {title}. Everything's up and running.",
                          f"Ah, good {tod}, {title}. I'm all ears.",
                          f"Systems are up. Good {tod}, {title}. What are we working on?"])

def chat(text, source, route):
    voice = want_voice(source, route["speak"])
    ctx = stored[-40:] if memory_on else recent[-6:]
    msgs = [{"role": "system", "content": system_prompt(voice)}] + ctx + [{"role": "user", "content": text}]
    set_state("processing")
    mid = new_id()
    barge = None
    if voice:
        said = []
        barge = speak_stream(sentences(llm_stream(msgs, route["deep"])), said, mid)
        reply = " ".join(said).strip()
        push_chat(mid, "jarvis", reply or "(interrupted)", persist=True)
    else:
        reply = text_stream(llm_stream(msgs, route["deep"]), mid)
        set_state(ready_state())
    pair = [{"role": "user", "content": text}, {"role": "assistant", "content": reply or "(interrupted)"}]
    recent.extend(pair); del recent[:-12]
    if memory_on:
        stored.extend(pair); del stored[:-200]; save_profile()
    return barge

def handle(text, source):
    global auth_management, auth_error
    command_text = clean(text)
    if UNMUTE_REQUEST.fullmatch(command_text):
        set_silent(False)
        return None
    if pending_action and pending_expired():
        clear_pending()
    if pending_action:
        if source == "text":
            push_chat(new_id(), "you", text)
            set_state("processing")
        stage = pending_action.get("stage")
        if is_cancel_text(command_text):
            if source == "voice":
                push_chat(new_id(), "you", text)
            cancel_pending_action()
            return None
        if stage == "admin_pin":
            return reply_text(
                "Enter the administrator PIN in the window to authorize this action, "
                "or say cancel.",
                source,
            )
        if stage == "confirm_send":
            if is_approval_text(command_text):
                if source == "voice":
                    push_chat(new_id(), "you", text)
                confirm_pending_action()
                return None
            return reply_text(
                "I'm waiting for your approval. Say send it or cancel.", source
            )
        if stage == "danger_confirm":
            if is_danger_confirmation_text(command_text):
                if source == "voice":
                    push_chat(new_id(), "you", text)
                confirm_pending_action()
                return None
            return reply_text(
                "That action is destructive. Say confirm dangerous or cancel.",
                source,
            )
        if stage == "confirm_screen":
            if is_approval_text(command_text):
                if source == "voice":
                    push_chat(new_id(), "you", text)
                confirm_pending_action()
                return None
            return reply_text(
                "Review the screen plan in the window, then say confirm or cancel.",
                source,
            )
        clear_pending()
    if source == "voice" and silent:
        set_state("standby")
        return None
    if MUTE_MINIMIZE_REQUEST.fullmatch(command_text):
        set_silent(True)
        act_minimize(mute=True)
        return None
    if MUTE_REQUEST.fullmatch(command_text):
        set_silent(True)
        return None
    if END_SESSION_REQUEST.fullmatch(command_text):
        if not active_user:
            return None
        if source == "voice":
            push_chat(new_id(), "you", text)
        request_end_session()
        return None
    if source == "voice" and (silent or not online) and len(text.split()) > 15:
        set_state(ready_state()); return None
    if (
        active_user
        and active_user["role"] == "admin"
        and auth_management
        and auth_management.get("mode") == "user_action"
        and auth_management.get("step") == "confirm"
        and re.fullmatch(r"\s*(?:yes|confirm|confirmed|do it)[.! ]*\s*", text, re.I)
    ):
        if source == "voice":
            push_chat(new_id(), "you", text)
        request_admin_pin()
        return None
    private_on = bool(PRIVATE_ON_REQUEST.search(text))
    if source == "text" and not private_on:
        push_chat(new_id(), "you", text)
        set_state("processing")
    takeover = ADMIN_TAKEOVER_REQUEST.search(text)
    if takeover:
        if active_user and active_user["role"] == "admin":
            return reply_text("You're already signed in as the administrator.", source)
        if not active_user:
            return reply_text("There isn't an active user session to switch from.", source)
        if source == "voice":
            push_chat(new_id(), "you", text)
        begin_admin_takeover()
        if mini:
            act_maximize()
        return None
    user_action = USER_ACTION_REQUEST.search(text)
    if user_action:
        if not active_user or active_user["role"] != "admin":
            return reply_text("Only the administrator can manage users.", source)
        if source == "voice":
            push_chat(new_id(), "you", text)
        operation = user_action.group("operation").lower()
        operation = "delete" if "delete" in operation else (
            "enable" if operation in ("enable", "restore") else operation
        )
        requested_name = (user_action.group("username") or "").strip()
        if requested_name:
            matches = [
                user for user in auth_store.list_users()
                if user["role"] == "user"
                and user["username"].casefold() == requested_name.casefold()
            ]
            if len(matches) == 1:
                prepare_user_action(operation, matches[0]["id"])
                return None
        with auth_lock:
            auth_management = {"mode": "users", "operation": operation}
            auth_error = (
                f"No user named {requested_name} was found."
                if requested_name else ""
            )
        auth_message()
        auth_prompt_queue.put(
            "Choose a user and action in the window."
            if not requested_name else "I couldn't find that user. Choose an account in the window."
        )
        return None
    add_user = ADD_USER_REQUEST.search(text)
    if add_user:
        if not active_user or active_user["role"] != "admin":
            return reply_text("Only the administrator can add users.", source)
        if source == "voice":
            push_chat(new_id(), "you", text)
        with auth_lock:
            auth_management = {
                "mode": "add_user",
                "step": "username",
                "username": (add_user.group(1) or "").strip()[:60],
            }
            auth_error = ""
        auth_message()
        return reply_text("What's the new user's name? Say it, or type it in the window.", source)
    if private_on or PRIVATE_OFF_REQUEST.search(text):
        enabled = private_on
        if enabled != private_mode:
            set_private_mode(enabled)
        if enabled and source == "voice":
            push_chat(new_id(), "you", text)
        elif enabled and source == "text":
            push_chat(new_id(), "you", text)
        message = (
            "This discussion is private and stored only on this computer."
            if enabled
            else "Private mode is off. New discussions will be stored in your cloud history."
        )
        return reply_text(message, source)
    if PERMANENT_DELETE_CHAT_REQUEST.search(text):
        if source == "voice":
            push_chat(new_id(), "you", text)
        with auth_lock:
            auth_management = {"mode": "permanently_delete_history"}
            auth_error = ""
        auth_message()
        return reply_text(
            "I'll permanently erase your chat history after you confirm in the window.",
            source,
        )
    if ARCHIVE_CHAT_REQUEST.search(text):
        archive_history()
        return reply_text(
            "Your conversations are archived. Open Archived in the sidebar to restore them.",
            source,
        )
    if CLOSE_REQUEST.search(text):
        close_jarvis()
        return None
    output_request = OUTPUT_REQUEST.search(text)
    if output_request:
        mode = output_request.group("mode").lower()
        set_output_preference(mode)
        reply = "I'll speak my replies aloud from now on." if mode == "voice" else "I'll keep my replies in text from now on."
        return reply_text(reply, source)
    repeat_text = re.sub(r"^\s*(?:jarvis[,:]?\s+)?", "", text, flags=re.IGNORECASE).strip(" .!?")
    if REPEAT_REQUEST.fullmatch(repeat_text):
        previous_reply = next(
            (message["content"] for message in reversed(recent) if message["role"] == "assistant"),
            None,
        )
        if previous_reply:
            return reply_text(previous_reply, source, True)
    if source == "text" or CONTROL_REQUEST.search(text) or COMPUTER_REQUEST.search(text):
        route = classify(text, source)
    else:
        route = {"intent": "chat", "actions": [], "reply": "", "speak": None,
                 "deep": bool(DEEP_REQUEST.search(text))}
    if VOICE_REQUEST.search(text):
        route["speak"] = True
    route = enforce(route, source)
    if route["intent"] == "ignore":
        set_state(ready_state()); return None
    if source == "voice": push_chat(new_id(), "you", text)
    if route["intent"] == "command":
        note = run_actions(route["actions"], source, speak=route.get("speak"))
        reply = note or route["reply"]
        if reply: return reply_text(reply, source, route["speak"])
        set_state(ready_state()); return None
    return chat(text, source, route)

def jarvis_brain():
    global audio_ready, auth_error
    last_audio_attempt = 0.0
    greeting_pending = True
    while True:
        if not audio_ready and time.monotonic() - last_audio_attempt >= 3:
            last_audio_attempt = time.monotonic()
            try:
                init_audio()
                audio_ready = True
                threading.Thread(target=discover_gemini, daemon=True).start()
                auth_error = ""
                auth_message()
            except Exception as e:
                print(f"[Audio device error: {e}]")
                with auth_lock:
                    auth_error = "Microphone unavailable. You can still sign in by typing; Jarvis will retry audio."
                auth_message()

        if not auth_ready.wait(0.1):
            if not ui_loaded.is_set():
                time.sleep(0.1)
                continue
            try:
                prompt = auth_prompt_queue.get_nowait()
            except queue.Empty:
                prompt = None
            if prompt:
                speak_auth_prompt(prompt)
                continue
            if active_user:
                if auth_mode == "gender_setup" and audio_ready:
                    text = listen_fast(allow_unauthenticated=True)
                    if text and active_user and auth_mode == "gender_setup":
                        try:
                            set_active_user_gender(text)
                        except AuthenticationError as error:
                            with auth_lock:
                                auth_error = str(error)
                            auth_message()
                            auth_prompt_queue.put(
                                "Please say male, female, non-binary, or prefer not to say."
                            )
                time.sleep(0.1)
                continue
            if not audio_ready:
                time.sleep(0.1)
                continue
            if auth_mode == "login" and auth_username is None:
                text = listen_fast(allow_unauthenticated=True)
                if text and not auth_ready.is_set():
                    try:
                        set_login_username(text)
                        speak_auth_prompt(
                            f"I heard {auth_username}. Enter the PIN in the Jarvis window."
                        )
                    except AuthenticationError as error:
                        with auth_lock:
                            auth_error = str(error)
                        auth_message()
                        auth_prompt_queue.put(
                            "I didn't catch a valid username. Please say it again or type it."
                        )
            continue

        threading.Thread(target=warm_kokoro, daemon=True).start()
        if not ui_loaded.is_set():
            ui_loaded.wait()
        if greeting_pending and active_user:
            speak_auth_prompt(greet())
        greeting_pending = False
        pending = None
        while auth_ready.is_set():
            with auth_lock:
                management = dict(auth_management) if auth_management else None
            if management and management.get("mode") == "add_user":
                try:
                    prompt = auth_prompt_queue.get_nowait()
                except queue.Empty:
                    prompt = None
                if prompt:
                    speak_auth_prompt(prompt)
                step = management.get("step")
                if step not in ("username", "spelling", "gender"):
                    time.sleep(0.1)
                    continue
                if MIC is None:
                    time.sleep(0.1)
                    continue
                text = listen_fast()
                if text and auth_ready.is_set():
                    try:
                        if step == "username":
                            set_add_user_username(text)
                        elif step == "spelling":
                            set_add_user_spelling(text)
                        elif step == "gender":
                            handle_gender_choice(text)
                    except AuthenticationError as error:
                        with auth_lock:
                            auth_error = str(error)
                        auth_message()
                        if step == "gender":
                            auth_prompt_queue.put(
                                "Please say male, female, non-binary, or prefer not to say."
                            )
                        elif step == "spelling":
                            auth_prompt_queue.put(
                                "I didn't catch those letters. Say one letter at a time, "
                                "then say done, or say clear to start over."
                            )
                        elif step == "gender":
                            auth_prompt_queue.put(
                                "Please say male, female, non-binary, or prefer not to say."
                            )
                continue
            try:
                prompt = auth_prompt_queue.get_nowait()
            except queue.Empty:
                prompt = None
            if prompt:
                speak_auth_prompt(prompt)
                continue
            if pending:
                text, src, pending = pending, "voice", None
            elif not text_queue.empty():
                text, src = text_queue.get()
            elif MIC is None:
                time.sleep(0.1)
                continue
            else:
                text, src = listen_fast(), "voice"
            if not auth_ready.is_set():
                break
            if not text or not text.strip():
                continue
            turn_context.epoch = auth_epoch
            try:
                pending = handle(text.strip(), src)
            except Exception as e:
                print(f"[Handler error: {e}]")
                set_state("listening" if online and not silent else "standby")
            finally:
                turn_context.epoch = None
        if SPK is not None:
            SPK.stop_now()
        greeting_pending = True

if __name__ == "__main__":
    auth_store = SupabaseAuthStore()
    private_store = LocalChatStore()
    auth_setup = not auth_store.has_admin()
    if not auth_setup:
        auth_prompt_queue.put(
            "Who's using Jarvis? Say your username, or type it on screen."
        )
    threading.Thread(target=start_ws_server, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    threading.Thread(target=jarvis_brain, daemon=True).start()

    def on_loaded():
        if not getattr(main_window, "_jarvis_camera_permission_handler", None):
            from System import Action
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

            def register_camera_permission_handler():
                core_webview = main_window.native.webview.CoreWebView2

                def on_camera_permission_requested(sender, event):
                    if (
                        event.PermissionKind.ToString() == "Camera"
                        and str(event.Uri).rstrip("/") == "http://localhost:3000"
                    ):
                        event.State = CoreWebView2PermissionState.Allow

                # Only grant camera access to Jarvis's exact local UI origin.
                main_window._jarvis_camera_permission_handler = on_camera_permission_requested
                core_webview.PermissionRequested += main_window._jarvis_camera_permission_handler

            main_window.native.Invoke(Action(register_camera_permission_handler))

        main_window.evaluate_js("""
        window.__jarvisCameraPermissionReady = true;
        let ws;
        const pending = [];
        function connect() {
          ws = new WebSocket('ws://localhost:8000');
          ws.onopen = () => {
            window.__jarvisLinked = true;
            while (pending.length && ws.readyState === 1) ws.send(JSON.stringify(pending.shift()));
          };
          ws.onclose = () => { window.__jarvisLinked = false; setTimeout(connect, 1000); };
          ws.onmessage = (e) => {
            const d = JSON.parse(e.data);
            if (d.action === 'state') window.dispatchEvent(new CustomEvent('jarvisState', { detail: d }));
            else if (d.action === 'chat') window.dispatchEvent(new CustomEvent('jarvisChat', { detail: d }));
            else if (d.action === 'conversations') window.dispatchEvent(new CustomEvent('jarvisConversations', { detail: d }));
            else if (d.action === 'auth') {
              window.__jarvisAuthenticated = Boolean(d.user && !d.required && !d.gender_required);
              window.dispatchEvent(new CustomEvent('jarvisAuth', { detail: d }));
            }
          };
        }
        connect();
        const out = (o) => {
          if (ws && ws.readyState === 1) ws.send(JSON.stringify(o));
          else pending.push(o);
        };
        window.addEventListener('jarvisCommand', (ev) => out({ action: 'command', text: ev.detail }));
        window.addEventListener('jarvisAction', (ev) => out(ev.detail));
        window.addEventListener('jarvisAuthAction', (ev) => out({ action: 'auth', ...ev.detail }));
        window.dispatchEvent(new Event('jarvisCameraPermissionReady'));
        """)
        ui_loaded.set()

    print("[Launching Pywebview UI...]")
    main_window = webview.create_window("Jarvis", "http://localhost:3000", frameless=True,
                                        width=BIG_W, height=BIG_H, on_top=True,
                                        x=WORK_X, y=WORK_Y)
    main_window.events.loaded += on_loaded
    webview.start(gui="edgechromium")
    if active_user:
        end_user_session()