import asyncio
import os
import time
import json
import sys
import subprocess
import threading
import queue
import re
import websockets
import webview
import io
import numpy as np
import sounddevice as sd
import soundfile as sf
import requests
from dotenv import load_dotenv
from kokoro import KPipeline
from google import genai
from google.genai import types
from groq import Groq

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# --- 1. SETUP ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

print("[Loading Local Kokoro TTS...]")
kokoro_pipeline = KPipeline(lang_code='b')

system_instruction = (
    "You are J.A.R.V.I.S., the highly advanced AI assistant created by Tony Stark. "
    "You are exceptionally polite, incredibly intelligent, and have a very dry, subtle British wit. "
    "You address the user as 'Sir'. You never use emojis or markdown. "
    "Keep your answers brief and concise, just like a real butler. "
)

SESSION_FILE = "session_log.txt"
LOCK_FILE = "active.lock"
main_window = None

# --- 2. WEBSOCKET SERVER & STATE ---
connected_clients = set()
text_queue = queue.Queue()
forced_engine = "Auto" 
current_state = "listening"

async def ws_handler(websocket):
    global forced_engine
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("action") == "set_engine":
                    forced_engine = data.get("engine", "Auto")
                    print(f"\n[Engine manually switched to: {forced_engine}]")
                elif data.get("action") == "command":
                    text_queue.put(data.get("text"))
            except Exception: pass
    except websockets.exceptions.ConnectionClosed: pass
    finally: connected_clients.remove(websocket)

async def broadcast_state(state):
    global current_state, main_window
    current_state = state
    
    if main_window:
        try:
            if state == "minimized":
                main_window.resize(200, 200)
            elif state in ["maximized", "listening", "processing", "speaking"]:
                main_window.resize(900, 900)
        except Exception: pass

    if connected_clients:
        message = json.dumps({"action": "state", "state": state})
        await asyncio.gather(*[client.send(message) for client in connected_clients])

def start_ws_server():
    async def run():
        async with websockets.serve(ws_handler, "localhost", 8000):
            await asyncio.Future()
    asyncio.run(run())

# --- 3. FAST AUDIO FUNCTIONS ---
def speak(text):
    print(f"\nJarvis: {text}")
    asyncio.run(broadcast_state("speaking"))
    
    try:
        sentences = re.split(r'(?<=[.!?]) +', text)
        for sentence in sentences:
            if not sentence.strip(): continue
            generator = kokoro_pipeline(sentence, voice='bm_george', speed=1.1)
            for i, (gs, ps, audio) in enumerate(generator):
                sd.play(audio, samplerate=24000)
                sd.wait() 
    except Exception as e: 
        print(f"[TTS Error: {e}]")
    
    if current_state != "minimized":
        asyncio.run(broadcast_state("listening"))

def listen_fast():
    global current_state
    if current_state != "minimized":
        asyncio.run(broadcast_state("listening"))
    
    fs = 16000
    chunk_duration = 0.2
    silence_threshold = 0.005 
    max_silence_chunks = 2 
    
    audio_chunks = []
    silent_chunks = 0
    has_spoken = False
    
    if current_state != "minimized":
        print("\n[Listening...]")
        
    try:
        with sd.InputStream(samplerate=fs, channels=1, dtype='float32') as stream:
            for _ in range(50): 
                chunk, overflow = stream.read(int(fs * chunk_duration))
                audio_chunks.append(chunk.copy())
                volume = np.max(np.abs(chunk))
                if volume > silence_threshold:
                    has_spoken = True
                    silent_chunks = 0 
                else:
                    if has_spoken: silent_chunks += 1
                if has_spoken and silent_chunks >= max_silence_chunks: break
        if not has_spoken: return None
        
        myrecording = np.concatenate(audio_chunks, axis=0)
        audio_data = io.BytesIO()
        sf.write(audio_data, myrecording, fs, format='WAV')
        audio_data.seek(0)
        audio_data.name = "audio.wav" 
        
        if current_state != "minimized":
            asyncio.run(broadcast_state("processing"))
            
        transcription = groq_client.audio.transcriptions.create(
            file=audio_data, model="whisper-large-v3-turbo", language="en", response_format="text"
        )
        text = transcription.strip()
        if text and len(text) > 2:
            print(f"You: {text}")
            return text
        return None
    except Exception:
        return None

# --- 4. AI ENGINES ---
def query_local_ollama(prompt):
    print("[Switching to Local Ollama...]")
    try:
        url = "http://localhost:11434/api/generate"
        payload = {"model": "llama3", "prompt": f"{system_instruction}\n\nUser: {prompt}\nJarvis:", "stream": False}
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200: return response.json().get("response", "").strip()
    except Exception: pass
    return None

def load_last_session():
    if not os.path.exists(SESSION_FILE): return "No previous log found."
    with open(SESSION_FILE, "r") as f:
        lines = f.readlines()
    if not lines: return "No previous log found."
    return "".join(lines[-3:])

# --- 5. MAIN BRAIN LOOP ---
def jarvis_brain():
    global forced_engine, current_state
    
    models_to_try = ["gemini-3.8-flash", "gemini-flash-latest"]
    active_model_index = 0
    def get_chat(model_name):
        return client.chats.create(model=model_name, config=types.GenerateContentConfig(system_instruction=system_instruction))

    active_chat = get_chat(models_to_try[active_model_index])
    groq_history = [{"role": "system", "content": system_instruction}]
    
    time.sleep(2) 
    speak("Good evening, Sir. All systems are online.")

    while True:
        user_input = None
        
        if not text_queue.empty():
            user_input = text_queue.get()
            print(f"You (Text): {user_input}")
        else:
            user_input = listen_fast()
            
        if not user_input: continue

        clean_input = re.sub(r'[^\w\s]', '', user_input.lower()) 
        
        # WAKE UP LOGIC
        if current_state == "minimized":
            if len(clean_input) > 1:
                asyncio.run(broadcast_state("maximized"))
                current_state = "listening"
                speak("Welcome back, Sir. How may I assist you?")
            continue

        # MINIMIZE LOGIC
        minimize_commands = ["wait", "hold on", "pause", "later jarvis", "stop listening", "go to sleep", "weight"]
        if any(cmd in clean_input for cmd in minimize_commands):
            speak("I will be in the corner if you need me, Sir.")
            asyncio.run(broadcast_state("minimized"))
            current_state = "minimized"
            continue

        if "thank you jarvis" in clean_input:
            speak("Ending session. Goodbye, Sir.")
            asyncio.run(broadcast_state("minimized"))
            current_state = "minimized"
            continue

        # --- SMART ROUTER ---
        past_context = load_last_session()
        full_prompt = f"System Note (Secret History): {past_context}\n\nUser: {user_input}"
        response_text = None
        
        engine_to_use = forced_engine
        if engine_to_use == "Auto":
            if any(word in clean_input for word in ["research", "search", "code", "write a script", "analyze", "explain", "deep dive"]):
                engine_to_use = "Gemini"
                print("\n[Router: Complex task detected. Using Gemini...]")
            else:
                engine_to_use = "Groq"
                print("\n[Router: Standard command. Using Groq for speed...]")

        # 1. TRY GEMINI
        if engine_to_use == "Gemini":
            attempts = 0
            while attempts < len(models_to_try):
                try:
                    asyncio.run(broadcast_state("processing"))
                    response = active_chat.send_message(full_prompt)
                    response_text = response.text
                    break
                except Exception as e:
                    if "429" in str(e) or "404" in str(e) or "503" in str(e):
                        active_model_index = (active_model_index + 1) % len(models_to_try)
                        try: active_chat = get_chat(models_to_try[active_model_index])
                        except: pass
                        attempts += 1
                    else: break
                    
        # 2. TRY GROQ
        if not response_text and engine_to_use in ["Auto", "Groq"]:
            try:
                asyncio.run(broadcast_state("processing"))
                groq_history.append({"role": "user", "content": full_prompt})
                completion = groq_client.chat.completions.create(
                    model="openai/gpt-oss-20b", 
                    messages=groq_history, 
                    temperature=0.7, 
                    max_tokens=250
                )
                response_text = completion.choices[0].message.content
                groq_history.append({"role": "assistant", "content": response_text})
            except Exception as e:
                print(f"[Groq Error: {e}]")

        # 3. TRY LOCAL OLLAMA
        if not response_text and engine_to_use in ["Auto", "Ollama"]:
            response_text = query_local_ollama(full_prompt)

        if response_text: 
            speak(response_text)
        else: 
            speak("Sir, all my AI models and offline backups are currently offline.")

# --- 6. LAUNCH EVERYTHING ---
if __name__ == "__main__":
    # (Removed the global declaration here to fix the syntax error)
    
    threading.Thread(target=start_ws_server, daemon=True).start()
    threading.Thread(target=jarvis_brain, daemon=True).start()
    
    def on_loaded():
        js_bridge = """
        const ws = new WebSocket('ws://localhost:8000');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.action === 'state') {
                window.dispatchEvent(new CustomEvent('jarvisState', { detail: data.state }));
            }
        };
        window.addEventListener('jarvisCommand', (event) => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'command', text: event.detail }));
            }
        });
        """
        main_window.evaluate_js(js_bridge)

    print("[Launching Pywebview UI...]")
    
    main_window = webview.create_window(
        'Jarvis', 'http://localhost:3000', 
        transparent=True, frameless=True, width=900, height=900, on_top=True
    )
    main_window.events.loaded += on_loaded
    
    webview.start(gui='edgechromium')