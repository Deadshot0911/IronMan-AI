import asyncio, os, time, json, threading, queue, re, io, random, collections, ctypes
from datetime import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf
import requests
import websockets
import webview
from dotenv import load_dotenv
from kokoro import KPipeline
from google import genai
from google.genai import types
from groq import Groq

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ---------- CONFIG ----------
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]
GROQ_MODEL = "openai/gpt-oss-20b"
OLLAMA_MODEL = "llama3"
VOICE = "bm_george"
FS, CH, END_QUIET = 16000, 0.1, 6
BIG, SMALL = 900, 200
BARGE_IN = True          # set False to disable voice interruption entirely (useful for debugging)
PREBUFFER_S = 0.8        # seconds of speech buffered before playback starts (smoother, tiny delay)
MEM_FILE = "jarvis_memory.json"
SPEECH_LEVEL, BARGE_LEVEL = 0.012, 0.08   # auto-calibrated at startup

print("[Loading Local Kokoro TTS...]")
kokoro_pipeline = KPipeline(lang_code="b")

PERSONA = (
    "You are J.A.R.V.I.S., talking out loud with your user like a sharp, warm friend who happens to be a genius. "
    "Never sound like a script or a help desk. Talk the way people really talk: contractions, natural reactions "
    "('Ha', 'Hmm', 'Right', 'Oh, nice one'), and a little dry British wit now and then. "
    "Default to one to three short spoken sentences. Go longer only when asked to explain something, and stay conversational. "
    "Vary how you start every reply and never repeat a phrase you used recently. "
    "Match the user's mood: playful when they joke, calm and focused when they're stressed. "
    "Sometimes ask a quick follow-up or give a real opinion, but not every time. "
    "Remember what was said earlier and refer back to it naturally. "
    "Call the user 'Sir' only occasionally, when it fits. If you don't know something, say so casually. "
    "Everything you write is spoken aloud: no markdown, lists, emojis or symbols; write numbers and units the way you'd say them."
)

def system_prompt():
    mem = ("Long-term memory is ON: you remember this chat and earlier sessions." if memory_on else
           "Long-term memory is OFF: you only keep short context. If the user wants you to remember things, "
           "tell them to press the Memory button or say 'memorise this'.")
    return f"{PERSONA}\nIt is {datetime.now().strftime('%A, %I:%M %p')}.\n{mem}"

# ---------- STATE ----------
state = "listening"
mini = False        # logic: minimised?
silent = False      # logic: minimised AND muted ("wait")
ui_mini = False     # what the UI shows (lags during window animation)
forced_engine = "Auto"
active = {"name": "Auto", "model": ""}   # engine actually in use right now
main_window = None
connected_clients = set()
text_queue = queue.Queue()
ws_loop = None
win_lock = threading.Lock()

# ---------- MEMORY ----------
memory_on = False
stored = []   # persistent conversation (only grows while memory is ON)
recent = []   # short in-RAM context (always)

def disk_write():
    try:
        with open(MEM_FILE, "w", encoding="utf-8") as f:
            json.dump({"on": memory_on, "history": stored[-200:]}, f, ensure_ascii=False)
    except Exception as e:
        print(f"[Memory save error: {e}]")

def disk_load():
    global memory_on
    try:
        with open(MEM_FILE, encoding="utf-8") as f:
            d = json.load(f)
        memory_on = bool(d.get("on"))
        stored[:] = d.get("history", [])
    except Exception:
        pass

def set_memory(on):
    global memory_on
    if on == memory_on: return
    if on: stored.extend(recent)      # "remember this conversation" includes what was said so far
    memory_on = on
    disk_write(); push_state()
    print(f"[Memory {'ON' if on else 'OFF'}]")

def wipe_memory():
    stored.clear(); disk_write(); push_state()

# ---------- WEBSOCKET ----------
def push_state():
    if not (ws_loop and connected_clients): return
    msg = json.dumps({"action": "state", "state": state, "mini": ui_mini, "silent": silent,
                      "memory": memory_on,
                      "engine": {"mode": forced_engine, "name": active["name"], "model": active["model"]}})
    async def send_all():
        await asyncio.gather(*[c.send(msg) for c in list(connected_clients)], return_exceptions=True)
    asyncio.run_coroutine_threadsafe(send_all(), ws_loop)

def set_state(s):
    global state
    state = s
    push_state()

def set_active(name, model):
    active["name"], active["model"] = name, model
    push_state()

async def ws_handler(websocket):
    global forced_engine
    connected_clients.add(websocket)
    push_state()
    try:
        async for message in websocket:
            try:
                d = json.loads(message)
                a = d.get("action")
                if a == "set_engine":
                    forced_engine = d.get("engine", "Auto"); push_state()
                    print(f"[Engine mode: {forced_engine}]")
                elif a == "set_memory":
                    set_memory(bool(d.get("on")))
                elif a == "command":
                    text_queue.put(d.get("text"))
            except Exception:
                pass
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

# ---------- WINDOW (shrink in place -> glide to corner, and back) ----------
try:
    SW, SH = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
except Exception:
    SW, SH = 1920, 1080

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
        glide(SW - SMALL - 30, SH - SMALL - 90)

def window_to_center():
    global ui_mini
    if not main_window: return
    with win_lock:
        glide(SW // 2 - SMALL // 2, SH // 2 - SMALL // 2)
        main_window.resize(BIG, BIG)
        main_window.move(SW // 2 - BIG // 2, SH // 2 - BIG // 2)
        time.sleep(0.15)
        ui_mini = False; push_state()

def go_mini(is_silent):
    global mini, silent
    was = mini
    mini, silent = True, is_silent
    if not was: threading.Thread(target=window_to_corner, daemon=True).start()
    else: push_state()

def do_wake():
    global mini, silent
    was = mini
    mini, silent = False, False
    if was: threading.Thread(target=window_to_center, daemon=True).start()
    else: push_state()
    return say(random.choice(WAKE_LINES))

# ---------- EARS ----------
def calibrate():
    global SPEECH_LEVEL, BARGE_LEVEL
    rec = sd.rec(FS, samplerate=FS, channels=1, dtype="float32"); sd.wait()
    n = float(np.abs(rec).max())
    SPEECH_LEVEL, BARGE_LEVEL = max(0.012, n * 2.0), max(0.08, n * 6)
    print(f"[Mic calibrated: speech>{SPEECH_LEVEL:.3f} barge>{BARGE_LEVEL:.3f}]")

def transcribe(audio):
    buf = io.BytesIO(); sf.write(buf, audio, FS, format="WAV"); buf.seek(0)
    try:
        r = groq_client.audio.transcriptions.create(
            file=("audio.wav", buf.read()), model="whisper-large-v3-turbo",
            language="en", response_format="text", prompt="Hey Jarvis.", temperature=0)
        t = (r if isinstance(r, str) else r.text).strip()
        return t if len(t) > 1 else None
    except Exception as e:
        print(f"[STT error: {e}]"); return None

def clean(t): return re.sub(r"[^\w\s]", "", t.lower()).strip()
HALLU = {"thank you", "thanks for watching", "you", "bye", "thanks"}   # Whisper's usual silence hallucinations

def listen_fast(max_s=15):
    set_state("listening")
    n = int(FS * CH)
    pre, frames, speaking, quiet = collections.deque(maxlen=3), [], False, 0
    t0 = time.time()
    with sd.InputStream(samplerate=FS, channels=1, dtype="float32", blocksize=n) as s:
        while time.time() - t0 < max_s:
            if not text_queue.empty(): return None
            chunk, _ = s.read(n)
            loud = float(np.abs(chunk).max()) > SPEECH_LEVEL
            if not speaking:
                pre.append(chunk.copy())
                if loud: speaking, frames, quiet, t0 = True, list(pre), 0, time.time()
            else:
                frames.append(chunk.copy())
                quiet = 0 if loud else quiet + 1
                if quiet >= END_QUIET: break
    if not speaking or len(frames) < 4: return None
    set_state("processing")
    t = transcribe(np.concatenate(frames))
    if t:
        print(f"You: {t}")
        if clean(t) in HALLU: return None
    return t

# ---------- BRAINS (all stream) ----------
def groq_stream(msgs):
    s = groq_client.chat.completions.create(model=GROQ_MODEL, messages=msgs, temperature=0.9,
                                            max_tokens=1024, stream=True, reasoning_effort="low")
    for ch in s:
        d = ch.choices[0].delta.content
        if d: yield d

def gemini_stream(msgs):
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                              parts=[types.Part(text=m["content"])]) for m in msgs[1:]]
    cfg = types.GenerateContentConfig(system_instruction=msgs[0]["content"], temperature=0.9)
    last = None
    for model in GEMINI_MODELS:
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
                      json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=30)
    r.raise_for_status()
    yield r.json().get("response", "").strip()

ENGINES = {"Groq": groq_stream, "Gemini": gemini_stream, "Ollama": ollama_stream}
MODEL_OF = {"Groq": GROQ_MODEL, "Gemini": GEMINI_MODELS[0], "Ollama": OLLAMA_MODEL}
COMPLEX = re.compile(r"\b(research|search|code|script|analy[sz]e|explain|deep dive|compare|summari[sz]e)\b")

def llm_stream(msgs, c):
    eng = forced_engine
    if eng == "Auto": eng = "Gemini" if COMPLEX.search(c) else "Groq"
    order = {"Gemini": ["Gemini", "Groq", "Ollama"], "Groq": ["Groq", "Gemini", "Ollama"],
             "Ollama": ["Ollama", "Groq", "Gemini"]}[eng]
    for name in order:
        set_active(name, MODEL_OF[name])
        got = False
        try:
            for piece in ENGINES[name](msgs):
                got = True; yield piece
            if got: return
        except Exception as e:
            print(f"[{name} error: {e}]")
            if got: return
    yield "Sorry, I can't reach any of my brains right now."

SENT_END = re.compile(r"(?<=[.!?])\s+")
def sentences(chunks):
    buf = ""
    for c in chunks:
        buf += c
        parts = SENT_END.split(buf)
        for p in parts[:-1]:
            if p.strip(): yield p.strip()
        buf = parts[-1]
    if buf.strip(): yield buf.strip()

# ---------- MOUTH (streamed, interruptible, echo-safe) ----------
def is_echo(text, said):
    """True if what the mic heard is noise or Jarvis's own voice rather than you."""
    w = clean(text).split()
    if not w or clean(text) in HALLU: return True
    if len(w) <= 3 and set(w) & {"no", "nope", "stop", "jarvis", "wait", "enough", "hold"}: return False
    spoken = set(clean(" ".join(said)).split())
    return sum(x in spoken for x in w) / len(w) >= 0.7

def barge_monitor(stop, pause, done, out, said):
    """Loud sound => PAUSE audio, listen, and only STOP if it was really you."""
    n = int(FS * CH)
    level = BARGE_LEVEL
    recent_chunks, loud_n = collections.deque(maxlen=3), 0
    try:
        with sd.InputStream(samplerate=FS, channels=1, dtype="float32", blocksize=n) as s:
            while not done.is_set() and not stop.is_set():
                chunk, _ = s.read(n)
                recent_chunks.append(chunk.copy())
                loud_n = loud_n + 1 if float(np.abs(chunk).max()) > level else 0
                if loud_n < 2: continue
                pause.set()
                frames, quiet = list(recent_chunks), 0
                while len(frames) < 60:
                    chunk, _ = s.read(n)
                    frames.append(chunk.copy())
                    quiet = 0 if float(np.abs(chunk).max()) > SPEECH_LEVEL else quiet + 1
                    if quiet >= END_QUIET: break
                text = transcribe(np.concatenate(frames))
                if text and not is_echo(text, said):
                    out["text"] = text
                    stop.set()
                    return
                pause.clear()                       # false alarm: carry on talking
                level = min(level * 1.4, 0.6)       # and be less sensitive next time
                loud_n = 0; recent_chunks.clear()
    except Exception as e:
        print(f"[Barge-in error: {e}]")
    finally:
        pause.clear()

def speak_stream(sent_iter, said):
    """Speaks sentences as they arrive. Returns what you said if you interrupted, else None."""
    stop, pause, done = threading.Event(), threading.Event(), threading.Event()
    out = {"text": None}
    q = queue.Queue(maxsize=8)

    def put(item):
        while not stop.is_set():
            try: q.put(item, timeout=0.1); return
            except queue.Full: pass

    def synth():
        try:
            for sent in sent_iter:
                if stop.is_set(): break
                sent = re.sub(r"[*#_`~>]", "", sent).strip()
                if not sent: continue
                said.append(sent)
                print(f"Jarvis: {sent}")
                for _, _, a in kokoro_pipeline(sent, voice=VOICE, speed=1.08):
                    if stop.is_set(): break
                    put(np.asarray(a, dtype=np.float32))
        except Exception as e:
            print(f"[TTS/LLM error: {e}]")
        finally:
            put(None)

    def audio_iter():
        buf, have, ended = [], 0.0, False
        while not stop.is_set() and not ended and have < PREBUFFER_S:   # small pre-buffer => no stutter
            try: a = q.get(timeout=0.05)
            except queue.Empty: continue
            if a is None: ended = True; break
            buf.append(a); have += len(a) / 24000
        for a in buf: yield a
        while not ended and not stop.is_set():
            try: a = q.get(timeout=0.05)
            except queue.Empty: continue
            if a is None: break
            yield a

    mon = None
    if BARGE_IN:
        mon = threading.Thread(target=barge_monitor, args=(stop, pause, done, out, said), daemon=True)
        mon.start()
    threading.Thread(target=synth, daemon=True).start()
    try:
        with sd.OutputStream(samplerate=24000, channels=1, dtype="float32") as o:
            started = False
            for a in audio_iter():
                if not started: set_state("speaking"); started = True
                for i in range(0, len(a), 2400):          # 0.1s blocks
                    while pause.is_set() and not stop.is_set(): time.sleep(0.02)
                    if stop.is_set(): break
                    o.write(a[i:i + 2400].reshape(-1, 1))
                if stop.is_set(): break
            if stop.is_set(): o.abort()
            else: o.stop()                                 # let the tail finish playing
    except Exception as e:
        print(f"[Audio error: {e}]")
    done.set()
    if mon: mon.join(timeout=10)
    set_state("listening")
    return out["text"]

def say(text):
    return speak_stream(iter([text]), [])

# ---------- LINES ----------
WAKE_LINES = ["I'm here, Sir.", "Back online. What do you need?", "Right here. Go ahead.", "Welcome back, Sir."]
MINI_LINES = ["Sure thing. I'll hang in the corner, still listening.", "Tucked away. Just talk to me.",
              "Got it. Out of your way, but I'm still here."]
BYE_LINES = ["Anytime, Sir. I'll be here if you need me.", "Of course. Shout if you need anything."]
MEM_ON_LINES = ["Memory's on. I'll remember all of this.", "Got it, I'm remembering this conversation from now on.",
                "Done. Everything we say is staying with me."]
MEM_OFF_LINES = ["Memory off. I'll stop keeping notes.", "Okay, I'm not remembering anything new."]
def greet():
    h = datetime.now().hour
    tod = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    return random.choice([f"Good {tod}, Sir. Everything's up and running.",
                          f"Ah, good {tod}. I'm all ears.",
                          f"Systems are up. Good {tod}, Sir. What are we working on?"])

# ---------- MAIN LOOP ----------
FILLER = {"no", "nope", "jarvis", "stop", "hey", "enough", "ok", "okay"}
WAKE_NAMES = ("jarvis", "jervis", "jarvas", "service", "travis")
SILENT_CMDS = ("wait", "hold on", "one second", "one sec")
MEM_ON = re.compile(r"\b(memori[sz]e|start remembering|remember (this|our|the) (conversation|chat))\b")
MEM_OFF = re.compile(r"\b(stop (remembering|memori[sz]ing)|forget this|don'?t remember)\b")
MEM_WIPE = re.compile(r"\b(clear|wipe|erase|delete) (your |the )?memory\b")

def respond(text, c):
    ctx = stored[-40:] if memory_on else recent[-6:]
    msgs = [{"role": "system", "content": system_prompt()}] + ctx + [{"role": "user", "content": text}]
    set_state("processing")
    said = []
    barge = speak_stream(sentences(llm_stream(msgs, c)), said)
    pair = [{"role": "user", "content": text},
            {"role": "assistant", "content": " ".join(said).strip() or "(interrupted)"}]
    recent.extend(pair); del recent[:-12]
    if memory_on:
        stored.extend(pair); del stored[:-200]; disk_write()
    return barge

def jarvis_brain():
    pending = None
    time.sleep(1.5)
    calibrate()
    list(kokoro_pipeline("Ready.", voice=VOICE))        # warm the TTS silently
    pending = say(greet())
    while True:
        if pending: text, pending = pending, None
        elif not text_queue.empty(): text = text_queue.get()
        else: text = listen_fast()
        if not text: continue
        c = clean(text); words = c.split()

        if "wake up" in c and any(n in c for n in WAKE_NAMES):
            pending = do_wake(); continue
        if silent: continue
        if len(words) <= 6:
            if MEM_WIPE.search(c):
                wipe_memory(); pending = say("Done. My memory is wiped clean."); continue
            if MEM_ON.search(c):
                set_memory(True); pending = say(random.choice(MEM_ON_LINES)); continue
            if MEM_OFF.search(c):
                set_memory(False); pending = say(random.choice(MEM_OFF_LINES)); continue
        if re.search(r"\bminimi[sz]e\b", c):
            go_mini(False); pending = say(random.choice(MINI_LINES)); continue
        if len(words) <= 4 and any(k in c for k in SILENT_CMDS):
            go_mini(True); continue
        if "thank you jarvis" in c:
            go_mini(True); pending = say(random.choice(BYE_LINES)); continue
        if words and set(words) <= FILLER:
            continue
        pending = respond(text, c)

# ---------- LAUNCH ----------
if __name__ == "__main__":
    disk_load()
    threading.Thread(target=start_ws_server, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    threading.Thread(target=jarvis_brain, daemon=True).start()

    def on_loaded():
        main_window.evaluate_js("""
        let ws;
        function connect() {
          ws = new WebSocket('ws://localhost:8000');
          ws.onopen = () => { window.__jarvisLinked = true; };
          ws.onclose = () => { window.__jarvisLinked = false; setTimeout(connect, 1000); };
          ws.onmessage = (e) => {
            const d = JSON.parse(e.data);
            if (d.action === 'state') window.dispatchEvent(new CustomEvent('jarvisState', { detail: d }));
          };
        }
        connect();
        const out = (o) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };
        window.addEventListener('jarvisCommand', (ev) => out({ action: 'command', text: ev.detail }));
        window.addEventListener('jarvisAction', (ev) => out(ev.detail));
        """)

    print("[Launching Pywebview UI...]")
    main_window = webview.create_window("Jarvis", "http://localhost:3000", frameless=True,
                                        width=BIG, height=BIG, on_top=True)
    main_window.events.loaded += on_loaded
    webview.start(gui="edgechromium")