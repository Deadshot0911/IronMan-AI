import ctypes
import json
import os
import queue
import socket
import subprocess
import time
from datetime import datetime

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel


BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE, "vosk-model-small")
START_SCRIPT = os.path.join(BASE, "Start_Jarvis.bat")
LOG_FILE = os.path.join(BASE, "sentinel_log.txt")
SAMPLE_RATE = 16000
BLOCK_SIZE = 4000
WAKE_PHRASES = {"jarvis", "hey jarvis", "okay jarvis"}
WAKE_COOLDOWN_SECONDS = 10
MIN_WAKE_CONFIDENCE = 0.75
BACKEND_ADDRESS = ("127.0.0.1", 8000)
MUTEX_NAME = "Local\\IronManAISentinel"
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183


def log(message):
    timestamp = datetime.now().isoformat(timespec="seconds")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def acquire_single_instance():
    handle = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError()
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def jarvis_is_running():
    try:
        with socket.create_connection(BACKEND_ADDRESS, timeout=0.25):
            return True
    except OSError:
        return False


def wake_phrase_matches(result):
    text = " ".join(result.get("text", "").lower().split())
    if text not in WAKE_PHRASES:
        return False
    words = result.get("result") or []
    return bool(words) and all(
        word.get("conf", 0.0) >= MIN_WAKE_CONFIDENCE for word in words
    )


def wake_word_heard(model):
    audio_queue = queue.Queue(maxsize=24)
    recognizer = KaldiRecognizer(
        model,
        SAMPLE_RATE,
        json.dumps(["jarvis", "hey jarvis", "okay jarvis", "[unk]"]),
    )
    recognizer.SetWords(True)

    def receive_audio(indata, frames, timing, status):
        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            pass

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=receive_audio,
    ):
        log("Wake listener ready. Say Jarvis to start.")
        while not jarvis_is_running():
            try:
                audio = audio_queue.get(timeout=1)
            except queue.Empty:
                continue

            if recognizer.AcceptWaveform(audio):
                result = json.loads(recognizer.Result())
            else:
                continue

            if wake_phrase_matches(result):
                text = " ".join(result.get("text", "").lower().split())
                log(f"Wake phrase confirmed: {text}")
                return True
    return False


def launch_jarvis():
    log("Starting Jarvis UI and assistant.")
    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", START_SCRIPT],
            cwd=BASE,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )

    startup_deadline = time.monotonic() + 180
    while time.monotonic() < startup_deadline:
        if jarvis_is_running():
            log("Jarvis is online. Wake listener is pausing while Jarvis uses the microphone.")
            while jarvis_is_running():
                time.sleep(2)
            log("Jarvis stopped. Wake listener is active again.")
            time.sleep(WAKE_COOLDOWN_SECONDS)
            return
        if process.poll() is not None:
            log(f"Jarvis launcher exited with code {process.returncode} before the backend started.")
            return
        time.sleep(1)

    log("Timed out waiting for the Jarvis backend to start.")


def main():
    if os.name != "nt":
        raise RuntimeError("The automatic Jarvis wake listener is supported on Windows.")
    if not os.path.isdir(MODEL_DIR):
        raise FileNotFoundError(f"Bundled wake-word model not found: {MODEL_DIR}")

    mutex = acquire_single_instance()
    if mutex is None:
        log("A wake listener is already running; exiting the duplicate instance.")
        return

    try:
        SetLogLevel(-1)
        log("Loading the bundled offline wake-word model.")
        model = Model(MODEL_DIR)
        log("Offline wake-word model loaded.")
        waiting_for_jarvis = False
        while True:
            if jarvis_is_running():
                if not waiting_for_jarvis:
                    log("Jarvis is already online; wake listener is waiting.")
                    waiting_for_jarvis = True
                time.sleep(2)
                continue
            if waiting_for_jarvis:
                log("Jarvis is offline; wake listener is active.")
                waiting_for_jarvis = False
            try:
                if wake_word_heard(model):
                    launch_jarvis()
            except Exception as error:
                log(f"Wake listener error: {error}")
                time.sleep(5)
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(f"Fatal wake listener error: {error}")
        raise
