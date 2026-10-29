import asyncio
import os
import time
import queue
import json
import numpy as np
import sounddevice as sd
import soundfile as sf
import io
import sys
import subprocess
import speech_recognition as sr
import threading
from dotenv import load_dotenv

# Hide Hugging Face warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from kokoro import KPipeline
from google import genai
from google.genai import types
from groq import Groq
from PyQt6.QtWidgets import QApplication
from hologram import HologramUI

# --- 1. SETUP ---
# Load keys securely from the .env file
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

ui = None

def speak(text):
    print(f"\nJarvis: {text}")
    if ui: ui.set_state("speaking")
    try:
        generator = kokoro_pipeline(text, voice='bm_george', speed=1.0)
        for i, (gs, ps, audio) in enumerate(generator):
            sd.play(audio, samplerate=24000)
            sd.wait()
    except Exception as e:
        print(f"[TTS Error: {e}]")
    if ui: ui.set_state("standby")

def listen_google():
    if ui: ui.set_state("listening")
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 0.8
    recognizer.energy_threshold = 300 
    
    print("\n[Listening...]")
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            audio = recognizer.listen(source, timeout=4, phrase_time_limit=10)
            
        print("[Recognizing...]")
        text = recognizer.recognize_google(audio).lower()
        print(f"You: {text}")
        if ui: ui.set_state("standby")
        return text
    except sr.WaitTimeoutError:
        if ui: ui.set_state("standby")
        return None
    except sr.UnknownValueError:
        if ui: ui.set_state("standby")
        return None
    except Exception:
        if ui: ui.set_state("standby")
        return None

def save_session_summary(summary):
    with open(SESSION_FILE, "a") as f:
        f.write(f"- {summary}\n")

def load_last_session():
    if not os.path.exists(SESSION_FILE): return "No previous log found."
    with open(SESSION_FILE, "r") as f:
        lines = f.readlines()
    if not lines: return "No previous log found."
    return "".join(lines[-3:])

# --- 2. THE BACKGROUND BRAIN LOOP ---
def jarvis_brain():
    models_to_try = ["gemini-3.8-flash", "gemini-flash-latest"]
    active_model_index = 0
    
    def get_chat(model_name):
        return client.chats.create(model=model_name, config=types.GenerateContentConfig(system_instruction=system_instruction))

    active_chat = get_chat(models_to_try[active_model_index])
    groq_history = [{"role": "system", "content": system_instruction}]
    
    is_text_mode = False 
    time.sleep(2) 
    speak("Good evening, Sir. All systems are online.")

    text_queue = queue.Queue()

    def handle_ui_text(text):
        text_queue.put(text)

    if ui:
        ui.on_submit_callback = handle_ui_text

    while True:
        user_input = None
        
        if not text_queue.empty():
            user_input = text_queue.get()
            print(f"You (Text): {user_input}")
        elif not is_text_mode:
            user_input = listen_google()
        else:
            time.sleep(0.5)
            continue
            
        if not user_input: continue

        # --- MODE SWITCHING ---
        if "shift to text" in user_input.lower():
            is_text_mode = True
            speak("Switched to text mode, Sir.")
            if ui: ui.show_text_mode()
            continue
            
        if "shift to voice" in user_input.lower():
            is_text_mode = False
            speak("Switched back to voice mode.")
            if ui: ui.hide_text_mode()
            continue

        # --- WAIT / PAUSE COMMAND ---
        if "wait jarvis" in user_input.lower():
            speak("Pausing, Sir.")
            if ui: ui.set_state("waiting")
            is_paused = True
            
            while is_paused:
                if not text_queue.empty():
                    user_input = text_queue.get()
                else:
                    user_input = listen_google()
                    
                if user_input and ("so jarvis" in user_input.lower() or "wake up" in user_input.lower()):
                    is_paused = False
                    if ui: ui.set_state("listening")
                    speak("I am back, Sir.")
            continue

        # --- WIPE MEMORY ---
        if any(cmd in user_input.lower() for cmd in ["delete all session records", "wipe memory", "clear memory"]):
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
            speak("All session records have been permanently deleted, Sir.")
            continue

        # --- SHUTDOWN COMMAND ---
        if any(cmd in user_input.lower() for cmd in ["thank you jar", "thank you jarvis", "shut down", "exit", "goodbye"]):
            speak("Powering down. Goodbye, Sir.")
            
            try:
                summary_prompt = f"Summarize what we did in 1 sentence. Last command: {user_input}"
                completion = groq_client.chat.completions.create(model="openai/gpt-oss-20b", messages=[{"role": "user", "content": summary_prompt}], max_tokens=50)
                save_session_summary(completion.choices[0].message.content.strip())
            except: 
                pass
            
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
                
            current_dir = os.path.dirname(os.path.abspath(__file__))
            sentinel_path = os.path.join(current_dir, "Start_Sentinel.bat")
            os.system(f'start /min "{sentinel_path}"')
            
            if ui: 
                ui.fade_out_and_close()
            
            time.sleep(1.5) 
            
            subprocess.run(f"taskkill /f /pid {os.getpid()}", shell=True)
            sys.exit(0)

        # --- AI CALL ---
        past_context = load_last_session()
        full_prompt = f"System Note (Secret History): {past_context}\n\nUser: {user_input}"

        response_text = None
        attempts = 0
        use_groq = False
        
        while attempts < len(models_to_try):
            if use_groq: break
            try:
                response = active_chat.send_message(full_prompt)
                response_text = response.text
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "404" in error_msg or "503" in error_msg:
                    active_model_index = (active_model_index + 1) % len(models_to_try)
                    try: active_chat = get_chat(models_to_try[active_model_index])
                    except: pass
                    attempts += 1
                else:
                    use_groq = True
                    break
        
        if not response_text:
            try:
                groq_history.append({"role": "user", "content": full_prompt})
                completion = groq_client.chat.completions.create(model="openai/gpt-oss-20b", messages=groq_history, temperature=0.7, max_tokens=150)
                response_text = completion.choices[0].message.content
                groq_history.append({"role": "assistant", "content": response_text})
            except Exception:
                speak("Sir, I am having trouble reaching the server.")
                continue

        if response_text:
            speak(response_text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = HologramUI()
    ui.show()
    threading.Thread(target=jarvis_brain, daemon=True).start()
    sys.exit(app.exec())