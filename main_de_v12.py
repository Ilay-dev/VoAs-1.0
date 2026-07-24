import os
import sys
import re
import asyncio
import io
import queue
import threading
import datetime
import base64
import time
import socket
import subprocess
import wave
import struct

# --- Verstecke nervige Warnungen (Requests & Pygame) ---
import warnings
warnings.filterwarnings("ignore")
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import requests 
import numpy as np
import sounddevice as sd
import pygame
import edge_tts
import mss
import pyautogui
import pyperclip
from PIL import Image
from openai import OpenAI
from duckduckgo_search import DDGS

import openwakeword
from openwakeword.model import Model

if sys.platform == "win32":
    import msvcrt

# =========================================================
# 1. WINDOWS CUDA / CTRANSLATE2 DLL FIX
# =========================================================

if sys.platform == "win32":
    try:
        import nvidia.cublas
        import nvidia.cudnn

        cublas_dir = nvidia.cublas.__path__[0] if hasattr(nvidia.cublas, "__path__") else os.path.dirname(getattr(nvidia.cublas, "__file__", ""))
        cudnn_dir = nvidia.cudnn.__path__[0] if hasattr(nvidia.cudnn, "__path__") else os.path.dirname(getattr(nvidia.cudnn, "__file__", ""))

        cublas_bin = os.path.join(cublas_dir, "bin")
        cudnn_bin = os.path.join(cudnn_dir, "bin")

        if os.path.exists(cublas_bin):
            os.environ["PATH"] = cublas_bin + os.path.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(cublas_bin)

        if os.path.exists(cudnn_bin):
            os.environ["PATH"] = cudnn_bin + os.path.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(cudnn_bin)
    except Exception:
        pass

from faster_whisper import WhisperModel

# =========================================================
# 2. CONFIGURATION & STARTUP CHECKS
# =========================================================

LM_STUDIO_URL = "http://localhost:1234/v1"
LM_STUDIO_MODELS_URL = "http://localhost:1234/v1/models"
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.020
SILENCE_DURATION = 0.60
TTS_RATE = "+0%"  

SCREENSHOT_TRIGGERS = ["schau", "siehst du", "bildschirm", "zeig", "guck", "look", "screen"]
TIME_TRIGGERS = ["uhrzeit", "wie viel uhr", "wie spät", "uhr ist es", "welche uhrzeit", "welcher tag", "datum"]
CLIPBOARD_TRIGGERS = ["zwischenablage", "zwischenspeicher", "kopierten text", "erklär den text"]

# --- TÖNE IM ARBEITSSPEICHER GENERIEREN ---
def create_beep_sound(frequency=600, duration=0.15, volume=0.1):
    """Generiert einen sanften Signalton direkt im Arbeitsspeicher (ohne externe Dateien)"""
    sample_rate = 44100
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        samples = []
        for i in range(int(sample_rate * duration)):
            t = float(i) / sample_rate
            # Sanfter Fade-In/Fade-Out, damit der Ton nicht knackt
            envelope = 1.0
            if t < 0.02: envelope = t / 0.02
            elif t > duration - 0.02: envelope = (duration - t) / 0.02
            
            val = int(volume * envelope * 32767.0 * np.sin(2.0 * np.pi * frequency * t))
            samples.append(struct.pack('<h', val))
        wav.writeframes(b''.join(samples))
    buffer.seek(0)
    return pygame.mixer.Sound(buffer)

# --- INITIALISIERE OPEN WAKE WORD ---
print("⚡ Lade 100% Offline Wake-Word Engine (openWakeWord)...")
try:
    openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
    oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
except Exception as e:
    print(f"\n❌ Fehler beim Laden von OpenWakeWord: {e}")
    sys.exit(1)

# --- LM STUDIO AUTO-START LOGIK ---
def ensure_lm_studio_running():
    print("🔍 Prüfe, ob LM Studio Server läuft...")
    try:
        if requests.get(LM_STUDIO_MODELS_URL, timeout=2).status_code == 200:
            print("✅ LM Studio ist bereits aktiv!")
            return
    except requests.exceptions.RequestException:
        pass

    print("⏳ LM Studio Server läuft nicht. Versuche Auto-Start der LM Studio App...")
    if sys.platform == "win32":
        paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\LM Studio\LM Studio.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\lm-studio\LM Studio.exe"),
            r"C:\Users\Ilay\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\LM Studio.lnk"
        ]
        
        for path in paths:
            if os.path.exists(path):
                os.startfile(path)
                break
        else:
            print("❌ Fehler: LM Studio nicht gefunden.")
            input("Drücke ENTER, sobald du LM Studio manuell gestartet hast...")
            return

        print("⏳ Warte darauf, dass der LM Studio Server erreichbar wird...")
        for _ in range(15):
            time.sleep(2)
            try:
                if requests.get(LM_STUDIO_MODELS_URL, timeout=2).status_code == 200:
                    print("🚀 LM Studio erfolgreich verbunden!")
                    return
            except requests.exceptions.RequestException:
                pass
        input("Bitte starte den lokalen Server in LM Studio manuell und drücke ENTER...")

ensure_lm_studio_running()
pygame.mixer.init()

# Erstelle die Signaltöne
try:
    BEEP_START = create_beep_sound(frequency=800, duration=0.15, volume=0.08)
    BEEP_STOP = create_beep_sound(frequency=500, duration=0.15, volume=0.08)
except Exception:
    BEEP_START, BEEP_STOP = None, None

print("⚡ Lade High-Quality Whisper STT (large-v3-turbo)...")
stt_model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

print("⚡ Verbinde mit LM Studio API...")
llm_client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")

# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def clean_text_for_tts(text):
    if not text:
        return ""
    text = re.sub(r'\[OPEN:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[SEARCH:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[DDG:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[VOLUME:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[.*?\]', '', text) 
    text = re.sub(r'(\d{1,2}):(\d{2})', r'\1 Uhr \2', text)
    text = re.sub(r'[*_#~`>\[\]]', '', text)
    text = re.sub(r'^\s*[-+•]\s*', '', text)
    return text.replace(',', '').strip()

def get_current_time():
    return datetime.datetime.now().strftime("Es ist %H Uhr %M am %d.%m.%Y.")

def capture_main_screen_base64():
    with mss.MSS() as sct:
        main_monitor = sct.monitors[1]
        sct_img = sct.grab(main_monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def execute_system_commands(ai_response):
    match_open = re.search(r'\[OPEN:\s*(.*?)\]', ai_response, re.IGNORECASE)
    if match_open:
        app_name = match_open.group(1).strip()
        print(f"\n🖥️ [System] Suche und öffne '{app_name}' über das Startmenü...")
        if sys.platform == "win32":
            pyautogui.press('win')
            time.sleep(0.5) 
            pyautogui.write(app_name, interval=0.05)
            time.sleep(0.5) 
            pyautogui.press('enter')
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", app_name])

    match_search = re.search(r'\[SEARCH:\s*(.*?)\]', ai_response, re.IGNORECASE)
    if match_search:
        search_query = match_search.group(1).strip()
        print(f"\n🌐 [System] Öffne Opera für Suche nach '{search_query}'...")
        if sys.platform == "win32":
            pyautogui.press('win')
            time.sleep(0.5)
            pyautogui.write("Opera", interval=0.05)
            time.sleep(0.5)
            pyautogui.press('enter')
            time.sleep(0.6)
            pyperclip.copy(search_query)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            pyautogui.press('enter')

    match_volume = re.search(r'\[VOLUME:\s*(.*?)\]', ai_response, re.IGNORECASE)
    if match_volume:
        action = match_volume.group(1).strip().lower()
        print(f"\n🔊 [System] System-Lautstärke: {action}")
        if action == "up":
            pyautogui.press('volumeup', presses=5)
        elif action == "down":
            pyautogui.press('volumedown', presses=5)
        elif action == "mute":
            pyautogui.press('volumemute')

# =========================================================
# 4. INSTANT WAKE-WORD RECORDING MIT OPENWAKEWORD
# =========================================================

def wait_for_wake_word_and_record():
    """Hört offline auf 'Hey Jarvis' und nimmt DANN den Befehl auf."""
    print(f"\r⏳ Warte auf 'Hey Jarvis'... (Mikrofon aktiv)    ", end="", flush=True)
    
    # ❗ BUGFIX FÜR DIE ENDLOSSCHLEIFE (ECHO/REVERB):
    # Setzt den Puffer der OpenWakeWord-Engine zurück, damit 
    # ein zuvor gesprochenes "Jarvis" (aus den Lautsprechern) gelöscht wird.
    if hasattr(oww_model, "reset"):
        oww_model.reset()
        
    audio_data = []
    is_recording_command = False
    has_spoken_command = False
    silent_chunks = 0
    chunk_size = 1280 
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
        
        # ❗ BUGFIX TEIL 2:
        # Die erste halbe Sekunde des Mikrofon-Streams verwerfen. 
        # Das löscht eventuelle Ton-Überbleibsel aus dem Mikrofonpuffer.
        for _ in range(int(SAMPLE_RATE / chunk_size * 0.5)):
            stream.read(chunk_size)

        while True:
            pcm, _ = stream.read(chunk_size)
            pcm = pcm.flatten()
            
            if not is_recording_command:
                # 1. WAKE WORD ENGINE CHECK
                prediction = oww_model.predict(pcm)
                jarvis_score = prediction.get("hey_jarvis", 0.0)
                
                # Wake Word erkannt!
                if jarvis_score > 0.5:
                    print(f"\n🔔 Jarvis ist wach! Höre auf deinen Befehl... 🗣️", flush=True)
                    
                    # START-TON SPIELEN
                    if BEEP_START:
                        BEEP_START.play()
                        
                    is_recording_command = True
                    silent_chunks = 0
            else:
                # 2. BEFEHL AUFZEICHNEN FÜR WHISPER
                pcm_float = pcm.astype(np.float32) / 32768.0
                amplitude = np.max(np.abs(pcm_float))
                audio_data.append(pcm_float)
                
                if amplitude > SILENCE_THRESHOLD:
                    has_spoken_command = True
                    silent_chunks = 0
                else:
                    silent_chunks += 1
                
                current_silence_limit = SILENCE_DURATION if has_spoken_command else 1.5
                
                # Pause/Ende des Satzes erkannt!
                if (silent_chunks * (chunk_size / SAMPLE_RATE)) >= current_silence_limit:
                    # STOPP-TON SPIELEN
                    if BEEP_STOP:
                        BEEP_STOP.play()
                    break
                    
    return np.concatenate(audio_data, axis=0).flatten() if audio_data else np.array([])

# =========================================================
# 5. WORKER THREADS
# =========================================================

def monitor_keyboard_input(stop_ev):
    while not stop_ev.is_set():
        if sys.platform == "win32" and msvcrt.kbhit():
            if msvcrt.getch().decode('utf-8', errors='ignore').lower() == 'x':
                print("\n🛑 [Unterbrechung per Taste 'X'!]")
                stop_ev.set()
                try: pygame.mixer.music.stop()
                except Exception: pass
                break
        time.sleep(0.05)

async def generate_tts_stream(t_queue, p_queue, stop_ev):
    while not stop_ev.is_set():
        try: text = await asyncio.to_thread(t_queue.get)
        except Exception: break
        if text is None:
            p_queue.put(None); t_queue.task_done(); break
        if stop_ev.is_set():
            t_queue.task_done(); break
            
        try:
            text_cleaned = clean_text_for_tts(text)
            if text_cleaned and not stop_ev.is_set():
                communicate = edge_tts.Communicate(text_cleaned, "de-DE-KillianNeural", rate=TTS_RATE)
                audio_bytes = io.BytesIO()
                async for chunk in communicate.stream():
                    if stop_ev.is_set(): break
                    if chunk["type"] == "audio": audio_bytes.write(chunk["data"])
                if not stop_ev.is_set():
                    audio_bytes.seek(0)
                    p_queue.put(audio_bytes)
        except Exception: pass
        finally: t_queue.task_done()

def start_tts_worker(t_queue, p_queue, stop_ev):
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: loop.run_until_complete(generate_tts_stream(t_queue, p_queue, stop_ev))
        except Exception: pass
        finally:
            try: loop.run_until_complete(loop.shutdown_asyncgens()); loop.close()
            except Exception: pass
    threading.Thread(target=run_loop, daemon=True).start()

def audio_player_worker(p_queue, stop_ev):
    while not stop_ev.is_set():
        try: audio_bytes = p_queue.get()
        except Exception: break
        if audio_bytes is None:
            p_queue.task_done(); break
        if stop_ev.is_set():
            p_queue.task_done(); break
            
        try:
            pygame.mixer.music.load(audio_bytes)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if stop_ev.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(60)
            pygame.mixer.music.unload()
        except Exception: pass
        finally: p_queue.task_done()

# =========================================================
# 6. MAIN BOT LOOP
# =========================================================

def run_voice_bot():
    print(f"\n🚀 Jarvis ist startklar! (Sage 'Hey Jarvis')")
    print("💡 Drücke im Terminal jederzeit 'x', um das Sprechen der KI abzubrechen.")

    messages = [
        {"role": "system", "content": (
            "Du bist Jarvis, ein extrem schneller, präziser Sprachassistent. "
            "Antworte auf Deutsch in maximal 1-2 kurzen Sätzen. "
            "Verwende keine Sternchen, Rautenzeichen oder Unterstriche in deiner Antwort. "
            "Schreibe Abkürzungen immer als Wort aus (zum Beispiel anstatt z.B.). "
            "Schreibe Uhrzeiten IMMER als Wort (14 Uhr 30).\n\n"
            "=== SYSTEM-BEFEHLE (NUR BEI AUSDRÜCKLICHEM BEFEHL!) ===\n"
            "Achtung: Wenn der Nutzer nur eine ganz normale Frage stellt (z.B. 'Was ist Linux?'), antwortest du NUR mit Text und benutzt NIEMALS eckige Klammern!\n"
            "Benutze die folgenden Befehle AUSSCHLIESSLICH, wenn der Nutzer dir einen direkten Befehl dazu gibt:\n\n"
            "1. [OPEN: appname] - NUTZE DIES NUR, wenn der Nutzer explizit sagt 'Öffne [Programm]' oder 'Starte [Programm]'.\n"
            "2. [SEARCH: suchbegriff] - NUTZE DIES NUR, wenn der Nutzer explizit sagt 'Suche im Browser nach...', 'Öffne Opera' oder 'Zeig mir im Browser...'. Es öffnet physisch den Browser!\n"
            "3. [VOLUME: up/down/mute] - NUTZE DIES NUR, wenn der Nutzer sagt 'Mache lauter', 'Mache leiser' oder 'Ton aus'.\n\n"
            "=== INTERNET HINTERGRUND-SUCHE ===\n"
            "Wenn du eine Frage des Nutzers nicht aus dem Kopf beantworten kannst und selbst recherchieren musst, setze [DDG: Suchbegriff] ans Ende. Dies passiert unsichtbar im Hintergrund."
        )}
    ]

    while True:
        try:
            audio = wait_for_wake_word_and_record()
        except KeyboardInterrupt:
            print("\n👋 Bot beendet.")
            sys.exit(0)
            
        if len(audio) == 0:
            continue
        
        segments, _ = stt_model.transcribe(
            audio,
            beam_size=1,
            language="de",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=150),
            condition_on_previous_text=False
        )
        user_text = "".join([segment.text for segment in segments]).strip()
        
        if not user_text:
            continue
            
        print(f"👤 Du: {user_text}")
        text_lower = user_text.lower()
        
        is_time_req = any(t in text_lower for t in TIME_TRIGGERS)
        is_screen_req = any(s in text_lower for s in SCREENSHOT_TRIGGERS)
        is_clip_req = any(c in text_lower for c in CLIPBOARD_TRIGGERS)

        prompt_text = user_text
        if is_time_req: prompt_text = f"[System-Info: {get_current_time()}]\n{prompt_text}"
        if is_clip_req:
            try:
                clip_text = pyperclip.paste()
                if clip_text: prompt_text += f"\n[Zwischenablage: {clip_text}]"
            except Exception: pass

        user_content = [{"type": "text", "text": prompt_text}]

        if is_screen_req:
            img_b64 = capture_main_screen_base64()
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        messages.append({"role": "user", "content": user_content})
        
        needs_rag_search = False
        rag_query = ""
        full_response = ""
        
        for attempt in range(2):
            current_stop_event = threading.Event()
            current_tts_queue = queue.Queue()
            current_playback_queue = queue.Queue()

            if attempt == 0: print("🤖 Jarvis: ", end="", flush=True)
                
            start_tts_worker(current_tts_queue, current_playback_queue, current_stop_event)
            threading.Thread(target=audio_player_worker, args=(current_playback_queue, current_stop_event), daemon=True).start()
            threading.Thread(target=monitor_keyboard_input, args=(current_stop_event,), daemon=True).start()
            
            sentence_buffer = ""
            full_response = ""
            
            try:
                response_stream = llm_client.chat.completions.create(
                    model="mistralai/ministral-3-3b",
                    messages=messages,
                    stream=True,
                    temperature=0.3,
                    max_tokens=150
                )

                for chunk in response_stream:
                    if current_stop_event.is_set(): break
                    raw_token = chunk.choices[0].delta.content or ""
                    print(raw_token, end="", flush=True)
                    sentence_buffer += raw_token
                    full_response += raw_token
                    
                    match = re.search(r'\[DDG:\s*(.*?)\]', full_response, re.IGNORECASE)
                    if match:
                        rag_query = match.group(1).strip()
                        needs_rag_search = True
                        break 
                        
                    if re.search(r'[.!?]\s*$', sentence_buffer):
                        if '[' not in sentence_buffer or ']' in sentence_buffer:
                            clean_chunk = clean_text_for_tts(sentence_buffer)
                            if clean_chunk and not current_stop_event.is_set():
                                current_tts_queue.put(clean_chunk)
                            sentence_buffer = ""
                            
                if not needs_rag_search and sentence_buffer.strip() and not current_stop_event.is_set():
                    current_tts_queue.put(clean_text_for_tts(sentence_buffer))
                    
            except KeyboardInterrupt: sys.exit(0)
            except Exception as e: print(f"\n⚠️ Verbindungsfehler: {e}")
                
            if not current_stop_event.is_set():
                current_tts_queue.put(None)
                current_tts_queue.join()
                current_playback_queue.join()

            current_stop_event.set()
            try: pygame.mixer.music.stop()
            except Exception: pass
                
            if needs_rag_search:
                print(f"\n🔍 [Hintergrund-Suche] '{rag_query}'...")
                try:
                    ddg_results = DDGS().text(rag_query, max_results=3)
                    context_text = "\n".join([f"- {res['title']}: {res['body']}" for res in ddg_results])
                    messages.append({"role": "assistant", "content": f"[DDG: {rag_query}]"})
                    messages.append({"role": "user", "content": f"Web-Ergebnisse:\n{context_text}\nBitte beantworte basierend darauf die Frage."})
                    needs_rag_search = False
                    continue  
                except Exception:
                    messages.append({"role": "assistant", "content": f"[DDG: {rag_query}]"})
                    messages.append({"role": "user", "content": "Sag mir, dass die Webrecherche fehlgeschlagen ist."})
                    needs_rag_search = False
                    continue
            break 

        execute_system_commands(full_response)
        messages.append({"role": "assistant", "content": full_response})
        print("\n")

if __name__ == "__main__":
    try: run_voice_bot()
    except KeyboardInterrupt: sys.exit(0)
