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

try:                                   # optional but recommended: pip install webrtcvad-wheels
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
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]   # real names are auto-discovered at startup
GROQ_MODEL = "openai/gpt-oss-20b"
ROUTER_MODEL = "llama-3.1-8b-instant"      # tiny + fast: decides what each message MEANS
OLLAMA_MODEL = "llama3"
VOICE = "bm_george"
FS, FRAME, TTS_SR = 16000, 480, 24000
END_FRAMES = 17                            # ~0.5 s of quiet ends your sentence
MIN_VOICED_FRAMES = 8                      # ignore sounds shorter than ~0.25 s (kills "Thank you." hallucinations)
BARGE_MODE = True
BARGE_MIN = 0.02
LEAD = 0.9
MEM_FILE = "jarvis_memory.json"

try:
    SW, SH = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
except Exception:
    SW, SH = 1920, 1080
SMALL = 200
BIG = int(max(560, min(900, SH - 110, SW - 60)))

print("[Loading Local Kokoro TTS...]")
kokoro_pipeline = KPipeline(lang_code="b")

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
state = "listening"
mini = False            # minimised?
silent = False          # minimised + muted ("wait"): only a wake request gets through
ui_mini = False         # what the UI shows (lags during window animation)
online = True           # False => Jarvis refuses to answer anything
text_mode = False       # chat panel open
output_pref = "auto"    # auto | voice | text  (how answers are delivered)
forced_engine = "Auto"
active = {"name": "Auto", "model": ""}
main_window = None
connected_clients = set()
text_queue = queue.Queue()      # items: (text, "text")
ws_loop = None
win_lock = threading.Lock()
noise, echo_g, barge_boost = 0.004, 0.6, 1.0
chat_seq = 0
chat_log = collections.OrderedDict()

def new_id():
    global chat_seq
    chat_seq += 1
    return chat_seq

# ---------- MEMORY ----------
memory_on = False
stored, recent = [], []

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
        memory_on = bool(d.get("on")); stored[:] = d.get("history", [])
    except Exception:
        pass

def set_memory(on):
    global memory_on
    if on == memory_on: return
    if on: stored.extend(recent)
    memory_on = on
    disk_write(); push_state()
    print(f"[Memory {'ON' if on else 'OFF'}]")

def wipe_memory():
    stored.clear(); disk_write(); push_state()

# ---------- WEBSOCKET ----------
def _broadcast(msg):
    if not (ws_loop and connected_clients): return
    async def send_all():
        await asyncio.gather(*[c.send(msg) for c in list(connected_clients)], return_exceptions=True)
    asyncio.run_coroutine_threadsafe(send_all(), ws_loop)

def state_msg():
    return json.dumps({"action": "state", "state": state, "mini": ui_mini, "silent": silent, "online": online,
                       "memory": memory_on, "text_mode": text_mode, "output": output_pref,
                       "engine": {"mode": forced_engine, "name": active["name"], "model": active["model"]}})

def push_state(): _broadcast(state_msg())

def set_state(s):
    global state
    state = s; push_state()

def set_active(name, model):
    active["name"], active["model"] = name, model; push_state()

def push_chat(mid, who, text):
    chat_log[mid] = (who, text)
    while len(chat_log) > 60: chat_log.popitem(last=False)
    _broadcast(json.dumps({"action": "chat", "id": mid, "from": who, "text": text}))

def set_text_mode(on):
    global text_mode
    text_mode = bool(on); push_state()

async def ws_handler(websocket):
    connected_clients.add(websocket)
    await websocket.send(state_msg())
    for mid, (who, text) in list(chat_log.items()):          # replay history after a UI reload
        await websocket.send(json.dumps({"action": "chat", "id": mid, "from": who, "text": text}))
    try:
        async for message in websocket:
            try:
                d = json.loads(message); a = d.get("action")
                if a == "command": text_queue.put((d.get("text", ""), "text"))
                elif a == "set_engine": threading.Thread(target=ui_engine, args=(d.get("engine", "Auto"),), daemon=True).start()
                elif a == "set_memory": set_memory(bool(d.get("on")))
                elif a == "set_mode": set_text_mode(bool(d.get("text")))
                elif a == "ui":
                    if d.get("do") == "minimize": act_minimize(False)
                    elif d.get("do") == "maximize": act_maximize()
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
        time.sleep(1.5); push_state()

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
        glide(SW - SMALL - 30, SH - SMALL - 90)

def window_to_center():
    global ui_mini
    if not main_window: return
    with win_lock:
        glide(SW // 2 - SMALL // 2, SH // 2 - SMALL // 2)
        main_window.resize(BIG, BIG)
        main_window.move(SW // 2 - BIG // 2, max(10, SH // 2 - BIG // 2 - 20))
        time.sleep(0.15)
        ui_mini = False; push_state()

def act_minimize(mute):
    global mini, silent
    was = mini
    mini, silent = True, bool(mute)
    if not was: threading.Thread(target=window_to_corner, daemon=True).start()
    else: push_state()

def act_maximize():
    global mini, silent
    was = mini
    mini, silent = False, False
    if was: threading.Thread(target=window_to_center, daemon=True).start()
    else: push_state()

# ---------- AUDIO CORE: ONE persistent mic stream + ONE persistent speaker stream ----------
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
        self.stream = sd.InputStream(samplerate=FS, channels=1, dtype="float32", blocksize=FRAME, callback=self._cb)
        self.stream.start()
    def _cb(self, indata, frames, tinfo, status):
        x = indata[:, 0].copy()
        try: self.q.put_nowait(x)
        except queue.Full:
            try: self.q.get_nowait(); self.q.put_nowait(x)
            except Exception: pass
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
        self.stream = sd.OutputStream(samplerate=TTS_SR, channels=1, dtype="float32",
                                      blocksize=512, latency=0.15, callback=self._cb)
        self.stream.start()
    def _cb(self, outdata, frames, tinfo, status):
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
    SPK = Speaker(); MIC = Mic()

def calibrate_noise():
    global noise
    MIC.flush(); time.sleep(1.0)
    vals = []
    while True:
        f = MIC.read(0.01)
        if f is None: break
        vals.append(rms(f))
    if vals: noise = max(0.002, float(np.median(vals)))
    print(f"[Mic ambient level: {noise:.4f} | VAD: {'on' if _vad else 'off (pip install webrtcvad-wheels)'}]")

def speech_thr(): return max(0.012, noise * 3.0)

# ---------- EARS ----------
def clean(t): return re.sub(r"[^\w\s]", "", t.lower()).strip()
HALLU = {"thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "you", "so", "oh"}

def transcribe(audio):
    buf = io.BytesIO(); sf.write(buf, audio, FS, format="WAV", subtype="PCM_16")
    try:
        r = groq_client.audio.transcriptions.create(
            file=("audio.wav", buf.getvalue()), model="whisper-large-v3-turbo", language="en",
            response_format="verbose_json", prompt="Hey Jarvis.", temperature=0)
        text = (getattr(r, "text", None) or (r.get("text") if isinstance(r, dict) else "") or "").strip()
        segs = getattr(r, "segments", None) or (r.get("segments") if isinstance(r, dict) else None) or []
        def g(s, k):
            v = s.get(k) if isinstance(s, dict) else getattr(s, k, None)
            return 0.0 if v is None else v
        if segs and all(g(s, "no_speech_prob") > 0.5 for s in segs):     # Whisper itself says "this is silence"
            return None
        return text if len(text) > 1 else None
    except Exception as e:
        print(f"[STT error: {e}]"); return None

def listen_fast():
    global noise
    set_state("listening")
    ring, pre = collections.deque(maxlen=8), collections.deque(maxlen=10)
    frames, trig, quiet, voiced_n, t0 = [], False, 0, 0, time.time()
    while True:
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
            if sum(ring) >= 5: trig, frames, voiced_n = True, list(pre), sum(ring)
            elif time.time() - t0 > 20: return None
        else:
            frames.append(f)
            voiced_n += voiced
            quiet = 0 if voiced else quiet + 1
            if quiet >= END_FRAMES or len(frames) > 500: break
    if voiced_n < MIN_VOICED_FRAMES: return None
    frames = frames[: len(frames) - max(0, quiet - 5)]
    set_state("processing")
    t = transcribe(np.concatenate(frames))
    if not t or clean(t) in HALLU or not clean(t):
        set_state("listening"); return None
    print(f"You: {t}")
    return t

# ---------- ENGINES ----------
def discover_gemini():
    """Find real Gemini model names for this API key and add them as fallbacks."""
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
        print(f"[Gemini models: {GEMINI_MODELS}]")
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
            print(f"[Gemini {model} error: {e}]")
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
    """Health check used when switching engines. Returns (ok, short reason)."""
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
                except Exception as e:
                    print(f"[Gemini check {m}: {e}]")
            return False, "it isn't responding."
    except Exception as e:
        print(f"[{name} check error: {e}]")
    return False, "it isn't responding."

def do_engine(name):
    """Switch engine. Returns a message to say/type if it did NOT work, else None."""
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
        except Exception as e:
            print(f"[{name} error: {e}]")
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

# ---------- INTENT ROUTER (no hard-coded phrases: the model reads meaning) ----------
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
{"do":"minimize","mute":false}  shrink to the corner orb. mute=true when the user wants Jarvis to pause, hold on, hush or give them a moment (then reply MUST be ""); mute=false when he should stay available and keep helping.
{"do":"maximize"}  open to the full view / wake up / come on screen. Does NOT change online or offline.
{"do":"offline"}   stop answering anything until told to return.
{"do":"online"}    resume answering. Does NOT change the window size or position.
{"do":"memory","state":"on|off|wipe"}  remember this conversation / stop remembering / erase stored memory.
{"do":"engine","name":"auto|gemini|groq|ollama"}  switch the AI brain. groq = fastest, gemini = best for complex work, ollama = local model on this PC, auto = Jarvis picks per question.
{"do":"mode","mode":"text|voice"}  open the text chat (answers arrive as text) or go back to voice.
{"do":"output","mode":"voice|text|auto"}  standing preference for HOW answers are delivered: always voice, always text, or auto (match how the user asked).

STATE (given with each input) describes the situation:
- online=false: Jarvis is offline. Only honour requests that bring him back or move the window (online, maximize, minimize, mode). For anything else addressed to him: intent "command", no actions, and a short reply saying all systems are offline. Talk not for him: "ignore".
- muted=true: Jarvis is silent. React only to a request to wake or return (maximize or online); everything else is "ignore".
Compound requests give several actions, e.g. "go offline and sit in the corner" = offline + minimize(mute=false).

Examples (the user will phrase things differently):
"hold on a second" -> {"intent":"command","actions":[{"do":"minimize","mute":true}],"reply":"","speak":null,"deep":false}
"tuck yourself away but keep listening" -> {"intent":"command","actions":[{"do":"minimize","mute":false}],"reply":"Of course, I'll stay close.","speak":null,"deep":false}
"you can shut down for now" -> {"intent":"command","actions":[{"do":"offline"}],"reply":"Going offline, Sir.","speak":null,"deep":false}
"let's use the faster brain" -> {"intent":"command","actions":[{"do":"engine","name":"groq"}],"reply":"Switching to Groq.","speak":null,"deep":false}
"tell me a joke out loud" -> {"intent":"chat","actions":[],"reply":"","speak":true,"deep":false}
"explain how TCP congestion control works" -> {"intent":"chat","actions":[],"reply":"","speak":null,"deep":true}
"no" -> {"intent":"ignore","actions":[],"reply":"","speak":null,"deep":false}"""

OFFLINE_LINES = ["All systems are offline, Sir.", "I'm offline at the moment, Sir.", "Systems are offline, Sir. Bring me back online when you're ready."]

def classify(text, source):
    ctx = " | ".join(f"{m['role']}: {m['content'][:90]}" for m in recent[-4:]) or "none"
    st = {"online": online, "minimised": mini, "muted": silent, "memory": memory_on, "engine": forced_engine,
          "text_mode": text_mode, "output_pref": output_pref}
    user = f"STATE: {json.dumps(st)}\nRECENT: {ctx}\nINPUT ({source}): {text}"
    for model in (ROUTER_MODEL, GROQ_MODEL):
        try:
            kw = dict(model=model, messages=[{"role": "system", "content": ROUTER_SYS}, {"role": "user", "content": user}],
                      temperature=0, max_tokens=250 if model == ROUTER_MODEL else 800,
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

def enforce(route):
    """Hard guarantees, whatever the router said."""
    dos = {a.get("do") for a in route["actions"]}
    if silent and route["intent"] != "ignore" and not (dos & {"maximize", "online"}):
        return {**route, "intent": "ignore", "actions": [], "reply": ""}
    if not online:
        route["actions"] = [a for a in route["actions"] if a.get("do") in ("online", "maximize", "minimize", "mode")]
        if route["intent"] == "chat" or (route["intent"] == "command" and not route["actions"] and not route["reply"]):
            return {**route, "intent": "command", "actions": [], "reply": random.choice(OFFLINE_LINES)}
    return route

def run_actions(acts):
    """Executes actions. Returns a message that replaces the router's reply if something failed."""
    global online, silent, output_pref
    note = None
    for a in acts:
        d = a.get("do")
        if d == "minimize": act_minimize(bool(a.get("mute")))
        elif d == "maximize": act_maximize()
        elif d == "offline": online = False
        elif d == "online": online, silent = True, False
        elif d == "memory":
            s = str(a.get("state", "")).lower()
            if s == "wipe": wipe_memory()
            else: set_memory(s == "on")
        elif d == "engine": note = do_engine(a.get("name")) or note
        elif d == "mode": set_text_mode(str(a.get("mode", "")).lower() == "text")
        elif d == "output":
            m = str(a.get("mode", "auto")).lower()
            output_pref = m if m in ("voice", "text", "auto") else "auto"
    push_state()
    return note

# ---------- MOUTH: smooth playback + echo-proof interruption ----------
def to_np(a):
    if hasattr(a, "detach"): a = a.detach().cpu().numpy()
    return np.asarray(a, dtype=np.float32).reshape(-1)

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
    except Exception as e:
        print(f"[Barge-in error: {e}]")
    finally:
        if not stop.is_set(): SPK.resume()

def speak_stream(sent_iter, said, mid):
    """Speaks sentences as they arrive (and mirrors them to the chat window). Returns what you said if you interrupted."""
    global LEAD
    stop, done, out = threading.Event(), threading.Event(), {"text": None}
    q = queue.Queue(maxsize=12)

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
                said.append(sent); print(f"Jarvis: {sent}")
                push_chat(mid, "jarvis", " ".join(said))
                try:
                    for _, _, a in kokoro_pipeline(sent, voice=VOICE, speed=1.08):
                        if stop.is_set(): break
                        put(to_np(a))
                except Exception as e:
                    print(f"[TTS skipped one sentence: {e}]")
        except Exception as e:
            print(f"[LLM error: {e}]")
        finally:
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
        if typed_waiting(): stop.set(); break                # a typed message interrupts speech
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
    while not stop.is_set() and SPK.queued > 0:
        if typed_waiting(): stop.set(); break
        time.sleep(0.02)
    if stop.is_set(): SPK.stop_now()

    if underrun: LEAD = min(LEAD + 0.5, 3.0)
    elif started: LEAD = max(0.6, LEAD - 0.05)

    done.set()
    if mon: mon.join(timeout=12)
    set_state("listening")
    if out["text"] is None:
        time.sleep(0.45); MIC.flush()                        # ignore the room's echo tail
    return out["text"]

def text_stream(chunks, mid):
    """Text-only reply: streams into the chat window, keeps newlines/code blocks."""
    buf, last = "", 0.0
    for c in chunks:
        buf += c
        if time.time() - last > 0.06:
            push_chat(mid, "jarvis", buf); last = time.time()
    buf = buf.strip() or "…"
    push_chat(mid, "jarvis", buf)
    print(f"Jarvis (text): {buf}")
    return buf

def want_voice(source, flag):
    if flag is not None: return flag                         # "say it out loud" / "just type it"
    if output_pref == "voice": return True
    if output_pref == "text": return False
    return source == "voice" and not text_mode               # auto: match how the user asked

def reply_text(text, source, flag=None):
    mid = new_id()
    if want_voice(source, flag): return speak_stream(iter([text]), [], mid)
    push_chat(mid, "jarvis", text); print(f"Jarvis (text): {text}")
    set_state("listening")
    return None

def say(text):
    return speak_stream(iter([text]), [], new_id())

def greet():
    h = datetime.now().hour
    tod = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    return random.choice([f"Good {tod}, Sir. Everything's up and running.",
                          f"Ah, good {tod}. I'm all ears.",
                          f"Systems are up. Good {tod}, Sir. What are we working on?"])

# ---------- MAIN LOOP ----------
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
    else:
        reply = text_stream(llm_stream(msgs, route["deep"]), mid)
        set_state("listening")
    pair = [{"role": "user", "content": text}, {"role": "assistant", "content": reply or "(interrupted)"}]
    recent.extend(pair); del recent[:-12]
    if memory_on:
        stored.extend(pair); del stored[:-200]; disk_write()
    return barge

def handle(text, source):
    """One message from voice or typing. Returns an interruption (voice) to process next, or None."""
    if source == "voice" and (silent or not online) and len(text.split()) > 15:
        set_state("listening"); return None                  # long talk while muted/offline = background chatter
    if source == "text":
        push_chat(new_id(), "you", text)
        set_state("processing")
    route = enforce(classify(text, source))
    if route["intent"] == "ignore":
        set_state("listening"); return None
    if source == "voice": push_chat(new_id(), "you", text)
    if route["intent"] == "command":
        note = run_actions(route["actions"])
        reply = note or route["reply"]
        if reply: return reply_text(reply, source, route["speak"])
        set_state("listening"); return None
    return chat(text, source, route)

def jarvis_brain():
    time.sleep(1.5)
    try:
        init_audio()
    except Exception as e:
        print(f"[Audio device error: {e}]"); return
    calibrate_noise()
    threading.Thread(target=discover_gemini, daemon=True).start()
    list(kokoro_pipeline("Ready.", voice=VOICE))
    pending = say(greet())
    while True:
        if pending: text, src, pending = pending, "voice", None
        elif not text_queue.empty(): text, src = text_queue.get()
        else: text, src = listen_fast(), "voice"
        if not text or not text.strip(): continue
        try:
            pending = handle(text.strip(), src)
        except Exception as e:
            print(f"[Handler error: {e}]"); set_state("listening")

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
            else if (d.action === 'chat') window.dispatchEvent(new CustomEvent('jarvisChat', { detail: d }));
          };
        }
        connect();
        const out = (o) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };
        window.addEventListener('jarvisCommand', (ev) => out({ action: 'command', text: ev.detail }));
        window.addEventListener('jarvisAction', (ev) => out(ev.detail));
        """)

    print("[Launching Pywebview UI...]")
    main_window = webview.create_window("Jarvis", "http://localhost:3000", frameless=True,
                                        width=BIG, height=BIG, on_top=True,
                                        x=(SW - BIG) // 2, y=max(10, (SH - BIG) // 2 - 20))
    main_window.events.loaded += on_loaded
    webview.start(gui="edgechromium")