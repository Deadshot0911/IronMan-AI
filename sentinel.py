import speech_recognition as sr
import os
import time
import sys
from dotenv import load_dotenv
from groq import Groq

# Load keys securely from the .env file
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

LOCK_FILE = "active.lock"

def listen_for_wake_word():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 150 
    recognizer.dynamic_energy_threshold = True

    while True:
        if os.path.exists(LOCK_FILE):
            time.sleep(1)
            continue

        try:
            with sr.Microphone() as source:
                audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
                
            text = recognizer.recognize_google(audio).lower()
            print(f"[Sentinel heard]: {text}")
            
            if "jarvis" in text:
                print("[Wake word detected! Launching Jarvis...]")
                
                with open(LOCK_FILE, "w") as f:
                    f.write("running")
                
                os.system("start Start_Jarvis.bat")
                sys.exit(0) 
                
        except sr.WaitTimeoutError:
            pass
        except Exception:
            pass

if __name__ == "__main__":
    listen_for_wake_word()