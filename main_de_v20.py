import os
import sys
import warnings
import logging
import ctypes
import re
import asyncio
import io
import queue
import threading
import datetime
import base64
import time
import subprocess
import wave
import struct
import uuid
import tempfile
import sqlite3
import json

import requests 
import numpy as np
import sounddevice as sd
import pygame
import edge_tts
import mss
import pyautogui
import pyperclip
from PIL import Image, ImageTk
from openai import OpenAI
import customtkinter as ctk
import tkinter as tk

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

import openwakeword
from openwakeword.model import Model

try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

# =========================================================
# 0. KONSOLE VERSTECKEN & ULTIMATE SILENCER
# =========================================================
if sys.platform == "win32":
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

os.environ["PYTHONWARNINGS"] = "ignore"
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
warnings.filterwarnings("ignore")
warnings.simplefilter("ignore")

def custom_excepthook(type, value, traceback):
    if type is RuntimeError and str(value) == 'Event loop is closed':
        return
    sys.__excepthook__(type, value, traceback)

sys.excepthook = custom_excepthook

logging.basicConfig(level=logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)
for logger_name in ["httpx", "httpcore", "openai", "duckduckgo_search", "urllib3", "asyncio", "melo", "aiohttp.client"]:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# =========================================================
# 1. GPU & CUDA SETUP
# =========================================================
if sys.platform == "win32":
    import msvcrt
    try:
        import nvidia.cublas
        import nvidia.cudnn
        
        if hasattr(nvidia.cublas, "__path__"):
            cublas_dir = nvidia.cublas.__path__[0]
        else:
            cublas_dir = os.path.dirname(getattr(nvidia.cublas, "__file__", ""))
            
        if hasattr(nvidia.cudnn, "__path__"):
            cudnn_dir = nvidia.cudnn.__path__[0]
        else:
            cudnn_dir = os.path.dirname(getattr(nvidia.cudnn, "__file__", ""))
            
        for bin_dir in [os.path.join(cublas_dir, "bin"), os.path.join(cudnn_dir, "bin")]:
            if os.path.exists(bin_dir):
                os.environ["PATH"] = bin_dir + os.path.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(bin_dir)
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

SCREENSHOT_TRIGGERS = ["schau", "siehst du", "bildschirm", "zeig", "guck", "look", "screen"]
TIME_TRIGGERS = ["uhrzeit", "wie viel uhr", "wie spät", "uhr ist es", "welche uhrzeit", "welcher tag", "datum"]
CLIPBOARD_TRIGGERS = ["zwischenablage", "zwischenspeicher", "kopierten text", "erklär den text", "verbesser den code"]

CONFIG_FILE = "jarvis_config.json"
DEFAULT_CONFIG = {
    "tts_rate": "+20%",
    "volume": 0.8,
    "landscape_mode": False,
    "font_size": 16,
    "silence_duration": 0.60,
    "system_prompt": (
        "Du bist Jarvis, ein schneller Sprachassistent. Antworte auf Deutsch kurz.\n"
        "WICHTIG: Verwende NIEMALS Emojis oder Smileys in deinen Antworten!\n"
        "In normalen Sätzen schreib Zahlen als Wort aus. In [ ] Befehlen nutze IMMER Ziffern.\n"
        "Befehle:\n"
        "- Programm öffnen: [OPEN: AppName] (Beispiel: [OPEN: Blender])\n"
        "- Web Suche: [SEARCH: query]\n"
        "- YouTube Suche: [YOUTUBE: suchbegriff]\n"
        "- [VOLUME: up/down/mute]\n"
        "- [TIMER: 60] (Beispiel für 60 Sekunden)\n"
        "- [TIMER_STOP] (Löscht alle aktiven Timer)\n"
        "- [ALARM: 18:30] (Beispiel für Uhrzeit)\n"
        "- [ALARM_STOP] (Löscht alle aktiven Wecker)\n"
        "- Recherche: [DDG: begriff]\n"
        "- Wetter: [WEATHER: Ort] (Wenn kein Ort genannt wird, nimm München!)\n"
        "- Datei lesen: [READ_FILE: dateiname] (Sucht eine Datei im lokalen Ordner und liest sie)\n"
        "- Programmieren: [AGENT: CODE] (Startet die Coding-KI). WICHTIG: Wenn der Nutzer nach dem Bildschirm fragt, beschreibe ihn NORMAL, OHNE [AGENT: CODE]!\n"
        "- [MEMORY_SAVE: Fakt] (Merke dir WICHTIGE Fakten für immer, z.B. \"[MEMORY_SAVE: Nutzer heißt Ilay]\". Speichere KEINE irrelevante Konversation!)\n"
        "- [MEDIA: next/prev/playpause] (Musik steuern)\n"
        "- [WINDOW: minimize/sort] (Fenster verwalten)\n"
        "- [SYSTEM: shutdown] (Fährt den PC herunter)\n"
        "- [SYSTEM: quit] (Beendet Jarvis)"
    )
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass

CONFIG = load_config()
ui_queue = queue.Queue()
global_stop_event = threading.Event()
active_timers = {}
active_alarms = {}

def init_memory_db():
    try:
        conn = sqlite3.connect('jarvis_memory.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS memory USING fts5(fact)
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass

init_memory_db()

def create_beep_sound(frequency=600, duration=0.15, volume=0.1):
    sample_rate = 44100
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        samples = []
        for i in range(int(sample_rate * duration)):
            t = float(i) / sample_rate
            envelope = 1.0
            if t < 0.02:
                envelope = t / 0.02
            elif t > duration - 0.02:
                envelope = (duration - t) / 0.02
            
            val_vol = volume * float(CONFIG.get("volume", 0.8))
            val = int(val_vol * envelope * 32767.0 * np.sin(2.0 * np.pi * frequency * t))
            samples.append(struct.pack('<h', val))
        wav.writeframes(b''.join(samples))
    buffer.seek(0)
    return pygame.mixer.Sound(buffer)

try:
    openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
    oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
except Exception:
    sys.exit(1)

def ensure_lm_studio_running():
    try:
        if requests.get(LM_STUDIO_MODELS_URL, timeout=2).status_code == 200:
            return
    except requests.exceptions.RequestException:
        pass
        
    if sys.platform == "win32":
        try:
            subprocess.Popen(["lms", "server", "start"], creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(5)
            if requests.get(LM_STUDIO_MODELS_URL, timeout=2).status_code == 200:
                return
        except Exception:
            pass

        paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\LM Studio\LM Studio.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\lm-studio\LM Studio.exe")
        ]
        for path in paths:
            if os.path.exists(path):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 6  # SW_MINIMIZE
                subprocess.Popen([path], startupinfo=startupinfo)
                time.sleep(10)
                break

ensure_lm_studio_running()
pygame.mixer.init()

try:
    BEEP_START = create_beep_sound(frequency=800, duration=0.15, volume=0.08)
    BEEP_STOP = create_beep_sound(frequency=500, duration=0.15, volume=0.08)
except Exception:
    BEEP_START, BEEP_STOP = None, None

stt_model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
llm_client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio", timeout=300.0)

MELO_MODEL = None
try:
    import torch
    from melo.api import TTS
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    MELO_MODEL = TTS(language='DE', device=device)
except Exception:
    pass

# =========================================================
# 3. HELPER & SYSTEM FUNCTIONS
# =========================================================
def clean_text_for_tts(text):
    if not text:
        return ""
        
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    for tag in [
        "[OPEN:", "[SEARCH:", "[DDG:", "[WEATHER:", "[VOLUME:", 
        "[AGENT:", "[TIMER:", "[ALARM:", "[MEMORY_SAVE:", "[MEDIA:", "[WINDOW:", "[SYSTEM:",
        "[TIMER_STOP]", "[ALARM_STOP]", "[READ_FILE:", "[YOUTUBE:"
    ]:
        text = re.sub(rf'\{tag}.*?\]', '', text, flags=re.IGNORECASE)
        
    text = re.sub(r'\[.*?\]', '', text) 
    text = re.sub(r'(\d{1,2}):(\d{2})', r'\1 Uhr \2', text)
    text = re.sub(r'[*_#~`>\[\]]', '', text)
    return text.replace(',', '').strip()

def get_current_time():
    return datetime.datetime.now().strftime("Es ist %H Uhr %M am %d.%m.%Y.")

def get_weather(location="München"):
    WEATHER_API_KEY = "758dd1308b128b385184b520c64d3ae3"
    if not location or location.lower() in ["hier", "mein ort", "aktueller ort", ""]:
        location = "München"
    try:
        response = requests.get(f"https://api.openweathermap.org/data/2.5/forecast?q={location}&appid={WEATHER_API_KEY}&units=metric&lang=de", timeout=5)
        if response.status_code != 200:
            return f"Ich konnte den Ort {location} leider nicht finden."
            
        data = response.json()
        forecasts = data["list"][:8] 
        temps = [f["main"]["temp"] for f in forecasts]
        rain_times = [f"{int(f['dt_txt'].split(' ')[1][:2])} Uhr" for f in forecasts if "rain" in f or f["weather"][0]["main"].lower() == "rain"]
        
        if rain_times:
            rain_str = f"Ja, um {', '.join(rain_times)}."
        else:
            rain_str = "Nein, es bleibt trocken."
            
        return f"Wetter für {location.title()}: Max {round(max(temps))}°C, Min {round(min(temps))}°C. Regen? {rain_str} Bewölkung: {forecasts[0]['weather'][0]['description']}."
    except Exception:
        return "Es gab einen Fehler beim Abrufen der Wetterdaten."

def capture_main_screen_base64():
    with mss.MSS() as sct:
        img = sct.grab(sct.monitors[1])
        buffer = io.BytesIO()
        img_pil = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
        img_pil.save(buffer, format="JPEG", quality=80)
        
        ui_queue.put(("SCREENSHOT_PREVIEW", img_pil.copy()))
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def find_and_read_local_file(filename_query):
    try:
        base_dir = os.getcwd()
        files = os.listdir(base_dir)
        best_match = None
        
        for f in files:
            if os.path.isfile(f) and filename_query.lower() in f.lower():
                best_match = f
                break
                
        if best_match:
            filepath = os.path.join(base_dir, best_match)
            with open(filepath, "r", encoding="utf-8") as file:
                content = file.read()
                if len(content) > 3000:
                    content = content[:3000] + "\n\n...[Text gekürzt aufgrund der Länge]..."
            return f"Datei gefunden: {best_match}\nInhalt:\n```\n{content}\n```"
        else:
            return f"Keine Datei ähnlich wie '{filename_query}' im aktuellen Ordner gefunden."
    except Exception as e:
        return f"Fehler beim Lesen der Datei: {e}"

def execute_open(app_name):
    if sys.platform == "win32":
        pyautogui.press('win')
        time.sleep(0.4)
        pyautogui.write(app_name, interval=0.03)
        time.sleep(0.4)
        pyautogui.press('enter')

def execute_search(search_query):
    if sys.platform == "win32":
        pyautogui.press('win')
        time.sleep(0.4)
        pyautogui.write("Opera", interval=0.03)
        time.sleep(0.4)
        pyautogui.press('enter')
        time.sleep(0.6)
        pyperclip.copy(search_query)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
        pyautogui.press('enter')
        
def execute_youtube(search_query):
    if sys.platform == "win32":
        pyautogui.press('win')
        time.sleep(0.4)
        pyautogui.write("Opera", interval=0.03)
        time.sleep(0.4)
        pyautogui.press('enter')
        time.sleep(1.2)
        
        pyautogui.hotkey('ctrl', 't')
        time.sleep(0.3)
        
        pyperclip.copy("youtube.com")
        pyautogui.hotkey('ctrl', 'v')
        pyautogui.press('enter')
        
        time.sleep(2.0)
        
        for _ in range(4):
            pyautogui.press('tab')
            time.sleep(0.1)
            
        pyperclip.copy(search_query)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
        pyautogui.press('enter')

def execute_volume(action):
    if action == "up":
        pyautogui.press('volumeup', presses=5)
    elif action == "down":
        pyautogui.press('volumedown', presses=5)
    elif action == "mute":
        pyautogui.press('volumemute')

def execute_media(action):
    try:
        if action == "next":
            pyautogui.press('nexttrack')
        elif action == "prev":
            pyautogui.press('prevtrack')
        elif action == "playpause":
            pyautogui.press('playpause')
    except Exception:
        pass

def execute_window_manager(action):
    if action == "minimize":
        pyautogui.hotkey('win', 'd')
    elif action == "sort":
        if not WIN32_AVAILABLE:
            return
            
        monitors = win32api.EnumDisplayMonitors()
        if len(monitors) < 2:
            return
            
        main_monitor = None
        sec_monitor = None
        for m in monitors:
            rect = m[2]
            if rect[0] == 0 and rect[1] == 0:
                main_monitor = rect
            else:
                sec_monitor = rect
                
        if not main_monitor:
            main_monitor = monitors[0][2]
        if not sec_monitor:
            sec_monitor = monitors[-1][2]
            
        def enum_windows_callback(hwnd, lParam):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                if not (style & win32con.WS_MINIMIZEBOX):
                    return True
                    
                if any(b in title for b in ["opera", "chrome", "edge", "firefox", "browser", "brave"]):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetWindowPos(hwnd, 0, sec_monitor[0] + 10, sec_monitor[1] + 10, 800, 600, win32con.SWP_NOZORDER)
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                elif any(i in title for i in ["code", "ide", "cursor", "pycharm", "visual studio"]):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetWindowPos(hwnd, 0, main_monitor[0] + 10, main_monitor[1] + 10, 800, 600, win32con.SWP_NOZORDER)
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            return True
            
        win32gui.EnumWindows(enum_windows_callback, None)

def execute_system(action):
    action = action.lower()
    if action == "shutdown":
        ui_queue.put(("JARVIS_SAYS", "PC wird in 5 Sekunden heruntergefahren..."))
        time.sleep(2)
        if sys.platform == "win32":
            os.system("shutdown /s /t 5")
    elif action == "quit":
        ui_queue.put(("QUIT", None))

def play_alert_sound():
    try:
        pygame.mixer.music.set_volume(float(CONFIG.get("volume", 0.8)))
        for _ in range(6):
            if BEEP_START:
                BEEP_START.play()
            time.sleep(0.4)
            if BEEP_STOP:
                BEEP_STOP.play()
            time.sleep(0.4)
    except Exception:
        pass

def execute_timer(seconds_str):
    try:
        sec = int(''.join(filter(str.isdigit, seconds_str)))
        timer_id = str(uuid.uuid4())
        ev = threading.Event()
        active_timers[timer_id] = ev
        ui_queue.put(("TIMER_START", timer_id, sec))
        
        for remaining in range(sec, 0, -1):
            if ev.is_set():
                ui_queue.put(("TIMER_CANCEL", timer_id))
                active_timers.pop(timer_id, None)
                return
            ui_queue.put(("TIMER_TICK", timer_id, remaining))
            time.sleep(1)
            
        ui_queue.put(("TIMER_END", timer_id))
        active_timers.pop(timer_id, None)
        threading.Thread(target=play_alert_sound, daemon=True).start()
    except ValueError:
        pass

def execute_timer_stop(arg):
    for ev in list(active_timers.values()):
        ev.set()

def execute_alarm(time_str):
    match = re.search(r'(\d{1,2}:\d{2})', time_str)
    if not match:
        return
        
    target_time = match.group(1)
    if len(target_time.split(':')[0]) == 1:
        target_time = "0" + target_time
    
    alarm_id = str(uuid.uuid4())
    ev = threading.Event()
    active_alarms[alarm_id] = ev
    ui_queue.put(("ALARM_START", alarm_id, target_time))
    
    while True:
        if ev.is_set():
            ui_queue.put(("ALARM_CANCEL", alarm_id))
            active_alarms.pop(alarm_id, None)
            return
        if datetime.datetime.now().strftime("%H:%M") == target_time:
            ui_queue.put(("ALARM_END", alarm_id))
            active_alarms.pop(alarm_id, None)
            threading.Thread(target=play_alert_sound, daemon=True).start()
            break
        time.sleep(5)

def execute_alarm_stop(arg):
    for ev in list(active_alarms.values()):
        ev.set()

def save_memory(fact):
    try:
        conn = sqlite3.connect('jarvis_memory.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT count(*) FROM memory WHERE fact = ?", (fact,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO memory (fact) VALUES (?)", (fact,))
            conn.commit()
            
        conn.close()
    except Exception:
        pass

def search_memory(query):
    try:
        conn = sqlite3.connect('jarvis_memory.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT fact FROM memory ORDER BY rowid DESC LIMIT 10")
        recent = [r[0] for r in cursor.fetchall()]
        
        words = [w for w in query.split() if len(w) > 3]
        fts_query = " OR ".join([f"{w}*" for w in words])
        matches = []
        if fts_query:
            cursor.execute("SELECT fact FROM memory WHERE memory MATCH ? LIMIT 5", (fts_query,))
            matches = [r[0] for r in cursor.fetchall()]
            
        conn.close()
        
        results = list(dict.fromkeys(recent + matches))
        return results
    except Exception:
        return []

# =========================================================
# 3.1 CODING KI-FUNKTION 
# =========================================================
def remove_lm_studio_logs(text):
    if not text:
        return ""
        
    clean_lines = []
    bad_tags = [
        "[LMSInternal]", "[Multiplexed", "[LLMProvider]", "[CachedFileDataProvider]", 
        "[LM Studio]", "Watching file at", "Applying structured output", 
        "Listing loaded models", "Getting base prediction", "Starting prediction for", 
        '"type": "none"', "[ImageProcessingProxyObject]", "Forking RC lazy worker",
        "[LLMProxyObject]", "Produced communication warning", 
        "caused by communication protocol incompatibility", "[ModelLoadingProvider]", 
        "Unloading model:", "Estimate to use", "Started loading model",
        "Forking model worker", "Resolved GPU config options", "GPU Configuration:",
        "Base endpoint", "GET /", "POST /"
    ]
    
    for line in text.split('\n'):
        if any(tag in line for tag in bad_tags):
            continue
        if re.match(r'^\d{2}:\d{2}:\d{2}\.\d{3}\s+>', line.strip()):
            continue
        if re.match(r'^\s*(Strategy|Priority|Disabled GPUs|Limit weight|Offload KV|GPU \d+|Model:|Context:|Total:|Num Offload|Num CPU|Main GPU|Tensor Split|llama_model_loader|llm_load_tensors|llama_new_context|llama_kv_cache):', line):
            continue
        clean_lines.append(line)
        
    return '\n'.join(clean_lines)

def get_existing_files(directory):
    if not os.path.exists(directory):
        return []
    return [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

def unload_coding_model(requested_model_name):
    try:
        resp = requests.get(LM_STUDIO_URL + "/models", timeout=3)
        if resp.status_code == 200:
            for m in resp.json().get("data", []):
                mid = m.get("id", "")
                if requested_model_name.lower() in mid.lower():
                    requests.post(
                        LM_STUDIO_URL.replace("/v1", "/api/v1/models/unload"), 
                        json={"instance_id": mid}, 
                        timeout=2
                    )
                    return
    except Exception:
        pass

def generate_and_save_code(task_description):
    model_name = "qwopus3.5-9b-coder"
    ui_queue.put(("CODE_START", ""))
    ui_queue.put(("CODE_LOG", "Modell 'qwopus3.5-9b-coder' wird in LM Studio geladen...\nBitte warten, dieser Vorgang kann je nach System bis zu 1 Minute dauern.\n\n"))
    
    save_dir = r"C:\Users\Ilay\Desktop\Scripts\.py\assistantX\code"
    os.makedirs(save_dir, exist_ok=True)
    existing_files = get_existing_files(save_dir)
    files_list_str = "\n".join(existing_files) if existing_files else "Keine Dateien vorhanden."
    
    try:
        task_lower = task_description.lower()
        is_improvement = any(w in task_lower for w in ["verbesser", "überarbeit", "korrigier", "ändere", "füge", "mach", "überschreib"])
        
        step1_prompt = f"Nutzer-Anfrage: '{task_description}'\n\nExistierende Dateien:\n{files_list_str}\n"
        
        if is_improvement and existing_files:
            step1_prompt += "Der Nutzer möchte bestehenden Code ändern. Wähle ZWINGEND eine existierende Datei aus der Liste aus und nenne NUR ihren Dateinamen! (z.B. script.py)"
        else:
            step1_prompt += "Entscheide, an welcher Datei gearbeitet wird (oder generiere einen neuen passenden Namen). Nenne NUR DEN DATEINAMEN (z.B. index.html oder script.py)"
            
        response_file = llm_client.chat.completions.create(
            model=model_name, 
            messages=[{"role": "user", "content": step1_prompt}], 
            temperature=0.1, 
            max_tokens=30
        )
        
        raw_filename = remove_lm_studio_logs(response_file.choices[0].message.content).strip()
        match_filename = re.search(r'([a-zA-Z0-9_\-]+\.(?:html|py|cpp|c|h|js|css|txt|json))', raw_filename, re.IGNORECASE)
        filename = match_filename.group(1) if match_filename else f"code_{int(time.time())}.txt"

        task_lower = task_description.lower()
        if any(w in task_lower for w in ["html", "webseite"]):
            filename = filename.rsplit(".", 1)[0] + ".html"
        elif any(w in task_lower for w in ["python", "py"]):
            filename = filename.rsplit(".", 1)[0] + ".py"
        elif any(w in task_lower for w in ["c++", "cpp"]):
            filename = filename.rsplit(".", 1)[0] + ".cpp"
                
        filepath = os.path.join(save_dir, filename)
        is_existing = os.path.exists(filepath)
        
        if is_existing:
            with open(filepath, "r", encoding="utf-8") as f:
                file_content = f.read()
        else:
            file_content = ""
            
        ui_queue.put(("CODE_LOG", f"Generiere Datei: {filename}...\n"))
        
        code_system_prompt = "Du bist Elite-Programmierer. Antworte AUSSCHLIESSLICH mit Code in Markdown-Blöcken. KEIN TEXT!"
        user_prompt = f"Nutzeranforderung: \"{task_description}\"\n"
        
        if "[Zwischenablage:" in task_description:
            user_prompt += "\nNutze EXAKT diesen Code als Grundlage.\n"
        elif is_existing:
            user_prompt += f"\nBestehender Code:\n```\n{file_content}\n```\nBitte verbessere diesen."
            
        response1 = llm_client.chat.completions.create(
            model=model_name, 
            messages=[
                {"role": "system", "content": code_system_prompt}, 
                {"role": "user", "content": user_prompt}
            ], 
            temperature=0.2, 
            max_tokens=40000, 
            stream=True
        )
        
        draft_code = ""
        line_buffer = ""
        for chunk in response1:
            if global_stop_event.is_set():
                break
            token = chunk.choices[0].delta.content or ""
            draft_code += token
            line_buffer += token
            if '\n' in line_buffer:
                lines = line_buffer.split('\n')
                for i in range(len(lines) - 1):
                    clean_l = remove_lm_studio_logs(lines[i] + '\n')
                    if clean_l.strip():
                        ui_queue.put(("CODE_LOG", clean_l))
                line_buffer = lines[-1]
                
        if line_buffer.strip():
            ui_queue.put(("CODE_LOG", remove_lm_studio_logs(line_buffer)))
            
        if global_stop_event.is_set():
            raise Exception("Vorgang durch Benutzer abgebrochen.")
        
        ui_queue.put(("CODE_LOG", "\n--- Optimiere Code ---\n"))
        draft_code = remove_lm_studio_logs(draft_code) 
        
        response2 = llm_client.chat.completions.create(
            model=model_name, 
            messages=[
                {"role": "system", "content": code_system_prompt}, 
                {"role": "user", "content": user_prompt}, 
                {"role": "assistant", "content": draft_code}, 
                {"role": "user", "content": "Behebe potenzielle Fehler. GIB ERNEUT AUSSCHLIESSLICH DEN CODE AUS!"}
            ], 
            temperature=0.2, 
            max_tokens=40000, 
            stream=True
        )
        
        final_code_raw = ""
        line_buffer = ""
        for chunk in response2:
            if global_stop_event.is_set():
                break
            token = chunk.choices[0].delta.content or ""
            final_code_raw += token
            line_buffer += token
            if '\n' in line_buffer:
                lines = line_buffer.split('\n')
                for i in range(len(lines) - 1):
                    clean_l = remove_lm_studio_logs(lines[i] + '\n')
                    if clean_l.strip():
                        ui_queue.put(("CODE_LOG", clean_l))
                line_buffer = lines[-1]
                
        if line_buffer.strip():
            ui_queue.put(("CODE_LOG", remove_lm_studio_logs(line_buffer)))
            
        if global_stop_event.is_set():
            raise Exception("Vorgang durch Benutzer abgebrochen.")
        
        final_code_raw = remove_lm_studio_logs(final_code_raw)
        
        match_code = re.search(r'```([a-zA-Z0-9_\-\+]*)\n(.*?)```', final_code_raw, re.DOTALL)
        if match_code:
            lang = match_code.group(1).strip().lower()
            final_code = match_code.group(2).strip()
            
            if not is_existing:
                base = os.path.splitext(filepath)[0]
                if lang in ["python", "py"]: filepath = base + ".py"
                elif lang in ["html", "html5"]: filepath = base + ".html"
                elif lang in ["javascript", "js"]: filepath = base + ".js"
                elif lang in ["cpp", "c++"]: filepath = base + ".cpp"
        else:
            final_code = final_code_raw.strip()
            
        if filepath.endswith(".html") and not match_code:
            html_match = re.search(r'(<!DOCTYPE html>.*?</html>|<html.*?>.*?</html>)', final_code, re.DOTALL | re.IGNORECASE)
            if html_match:
                final_code = html_match.group(1).strip()
            
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(final_code)
            
        ui_queue.put(("CODE_LOG", f"\n💾 Erfolgreich gespeichert: {filepath}\n"))
        return filepath
        
    except Exception as e:
        ui_queue.put(("CODE_LOG", f"\n❌ Fehler aufgetreten: {e}\n"))
        raise e
    finally:
        unload_coding_model(model_name)
        time.sleep(3)
        ui_queue.put(("CODE_END", ""))


def wait_for_wake_word_and_record():
    ui_queue.put(("STATE", "idle"))
    if hasattr(oww_model, "reset"):
        oww_model.reset()
        
    audio_data = []
    is_recording = False
    has_spoken = False
    silent_chunks = 0
    chunk_size = 1280 
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
        for _ in range(int(SAMPLE_RATE / chunk_size * 0.5)):
            stream.read(chunk_size)
            
        while True:
            pcm, _ = stream.read(chunk_size)
            pcm = pcm.flatten()
            
            if not is_recording:
                if oww_model.predict(pcm).get("hey_jarvis", 0.0) > 0.5:
                    global_stop_event.set()
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass
                    ui_queue.put(("STATE", "listening"))
                    if BEEP_START:
                        BEEP_START.play()
                    is_recording = True
                    silent_chunks = 0
            else:
                pcm_float = pcm.astype(np.float32) / 32768.0
                audio_data.append(pcm_float)
                
                if np.max(np.abs(pcm_float)) > SILENCE_THRESHOLD:
                    has_spoken = True
                    silent_chunks = 0
                else:
                    silent_chunks += 1
                
                limit = float(CONFIG.get("silence_duration", 0.60)) if has_spoken else 1.5
                if (silent_chunks * (chunk_size / SAMPLE_RATE)) >= limit:
                    if BEEP_STOP:
                        BEEP_STOP.play()
                    ui_queue.put(("STATE", "processing"))
                    break
                    
    if audio_data:
        return np.concatenate(audio_data, axis=0).flatten()
    return np.array([])


async def generate_tts_stream(t_queue, p_queue):
    while not global_stop_event.is_set():
        try:
            text = await asyncio.to_thread(t_queue.get)
        except Exception:
            break
            
        if text is None:
            p_queue.put(None)
            t_queue.task_done()
            break
            
        if global_stop_event.is_set():
            t_queue.task_done()
            break
            
        try:
            text_cleaned = clean_text_for_tts(text)
            if text_cleaned and not global_stop_event.is_set():
                if MELO_MODEL is not None:
                    def _synth_melo():
                        try:
                            temp_filename = os.path.join(tempfile.gettempdir(), f"melo_{uuid.uuid4().hex}.wav")
                            MELO_MODEL.tts_to_file(text_cleaned, MELO_MODEL.hps.data.spk2id['DE'], temp_filename, speed=1.0, quiet=True)
                            return temp_filename
                        except Exception:
                            return None
                            
                    audio_file = await asyncio.to_thread(_synth_melo)
                    if audio_file and not global_stop_event.is_set():
                        p_queue.put(audio_file)
                else:
                    communicate = edge_tts.Communicate(text_cleaned, "de-DE-AmalaNeural", rate=CONFIG.get("tts_rate", "+20%"))
                    audio_bytes = io.BytesIO()
                    async for chunk in communicate.stream():
                        if global_stop_event.is_set():
                            break
                        if chunk["type"] == "audio":
                            audio_bytes.write(chunk["data"])
                    if not global_stop_event.is_set():
                        audio_bytes.seek(0)
                        p_queue.put(audio_bytes)
        except Exception:
            pass
        finally:
            t_queue.task_done()

def start_tts_worker(t_queue, p_queue):
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(generate_tts_stream(t_queue, p_queue))
        except Exception:
            pass
        finally:
            try: 
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except Exception:
                pass
    threading.Thread(target=run_loop, daemon=True).start()

def audio_player_worker(p_queue):
    while not global_stop_event.is_set():
        try:
            audio_item = p_queue.get()
        except Exception:
            break
            
        if audio_item is None or global_stop_event.is_set():
            p_queue.task_done()
            break
        
        ui_queue.put(("STATE", "speaking"))
        try:
            pygame.mixer.music.load(audio_item)
            pygame.mixer.music.set_volume(float(CONFIG.get("volume", 0.8)))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if global_stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(60)
            pygame.mixer.music.unload()
        except Exception:
            pass
        finally: 
            if isinstance(audio_item, str) and os.path.exists(audio_item):
                try:
                    os.remove(audio_item)
                except Exception:
                    pass
            p_queue.task_done()

def keyboard_worker():
    if keyboard is None:
        return
    try:
        while True:
            keyboard.wait('x')
            global_stop_event.set()
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
            except Exception:
                pass
            ui_queue.put(("STATE", "idle"))
    except Exception:
        pass

# =========================================================
# BOT MAIN LOOP (Läuft im Hintergrund)
# =========================================================
def run_voice_bot():
    messages = []

    while True:
        try:
            audio = wait_for_wake_word_and_record()
        except KeyboardInterrupt:
            sys.exit(0)
            
        if len(audio) == 0:
            continue
            
        global_stop_event.clear()
            
        if len(messages) > 0 and messages[0]["role"] == "system":
            messages[0]["content"] = CONFIG.get("system_prompt", DEFAULT_CONFIG["system_prompt"])
        else:
            messages.insert(0, {"role": "system", "content": CONFIG.get("system_prompt", DEFAULT_CONFIG["system_prompt"])})
        
        segments, _ = stt_model.transcribe(audio, beam_size=1, language="de", vad_filter=True, condition_on_previous_text=False)
        user_text = "".join([s.text for s in segments]).strip()
        
        if not user_text:
            continue
            
        ui_queue.put(("TRANSCRIPTION", user_text))
        prompt_text = user_text
        
        if any(t in user_text.lower() for t in TIME_TRIGGERS):
            prompt_text = f"[System-Info: {get_current_time()}]\n{prompt_text}"
            
        if any(c in user_text.lower() for c in CLIPBOARD_TRIGGERS):
            try:
                clip_text = pyperclip.paste()
                if clip_text:
                    prompt_text += f"\n[Zwischenablage: {clip_text}]"
            except Exception:
                pass

        memories = search_memory(prompt_text)
        if memories:
            memory_context = "Erinnere dich an folgende Fakten über den Nutzer:\n" + "\n".join(memories)
            prompt_text = f"{memory_context}\n\n{prompt_text}"

        user_content = [{"type": "text", "text": prompt_text}]
        if any(s in user_text.lower() for s in SCREENSHOT_TRIGGERS):
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{capture_main_screen_base64()}"}})
            user_content.append({"type": "text", "text": "WICHTIG: Beschreibe nur, was du auf dem Bild siehst. Verwende hierfür NIEMALS den Befehl [AGENT: CODE]!"})

        messages.append({"role": "user", "content": user_content})
        
        needs_rag = False
        rag_query = ""
        needs_weather = False
        weather_loc = ""
        needs_code = False
        needs_file = False
        file_query = ""
        
        for attempt in range(2):
            if global_stop_event.is_set():
                break
                
            t_queue = queue.Queue()
            p_queue = queue.Queue()
            executed = set()
                
            start_tts_worker(t_queue, p_queue)
            threading.Thread(target=audio_player_worker, args=(p_queue,), daemon=True).start()
            
            sentence_buf = ""
            full_resp = ""
            
            start_time = time.time()
            token_count = 0
            last_ui_update = start_time
            
            try:
                stream = llm_client.chat.completions.create(
                    model="mistralai/ministral-3-3b", 
                    messages=messages, 
                    stream=True, 
                    temperature=0.3, 
                    max_tokens=150
                )
                
                for chunk in stream:
                    if global_stop_event.is_set():
                        break
                        
                    token = chunk.choices[0].delta.content or ""
                    sentence_buf += token
                    full_resp += token
                    
                    token_count += 1
                    now = time.time()
                    if now - last_ui_update > 0.5:
                        tps = token_count / (now - start_time) if (now - start_time) > 0 else 0
                        ui_queue.put(("TPS", f"⚡ {tps:.1f} t/s"))
                        last_ui_update = now
                    
                    ui_queue.put(("JARVIS_SAYS", clean_text_for_tts(full_resp)))
                    
                    if "```" in full_resp or "<!doctype html" in full_resp.lower() or "<html" in full_resp.lower():
                        needs_code = True
                        break
                        
                    m_file = re.search(r'\[READ_FILE:\s*(.*?)\]', full_resp, re.IGNORECASE)
                    if m_file:
                        needs_file = True
                        file_query = m_file.group(1).strip()
                        break
                        
                    m_ddg = re.search(r'\[DDG:\s*(.*?)\]', full_resp, re.IGNORECASE)
                    if m_ddg:
                        needs_rag = True
                        rag_query = m_ddg.group(1).strip()
                        break 
                        
                    m_wea = re.search(r'\[WEATHER:\s*(.*?)\]', full_resp, re.IGNORECASE)
                    if m_wea:
                        needs_weather = True
                        weather_loc = m_wea.group(1).strip()
                        break
                        
                    if re.search(r'\[AGENT:\s*CODE\]', full_resp, re.IGNORECASE):
                        needs_code = True
                        break

                    cmd_patterns = [
                        ("SEARCH", execute_search, r'\[SEARCH:\s*(.*?)\]'),
                        ("YOUTUBE", execute_youtube, r'\[YOUTUBE:\s*(.*?)\]'),
                        ("OPEN", execute_open, r'\[OPEN:\s*(.*?)\]'), 
                        ("VOLUME", execute_volume, r'\[VOLUME:\s*(.*?)\]'),
                        ("TIMER", execute_timer, r'\[TIMER:\s*(.*?)\]'),
                        ("TIMER_STOP", execute_timer_stop, r'\[TIMER_STOP\]'),
                        ("ALARM", execute_alarm, r'\[ALARM:\s*(.*?)\]'),
                        ("ALARM_STOP", execute_alarm_stop, r'\[ALARM_STOP\]'),
                        ("MEDIA", execute_media, r'\[MEDIA:\s*(.*?)\]'),
                        ("WINDOW", execute_window_manager, r'\[WINDOW:\s*(.*?)\]'),
                        ("MEMORY", save_memory, r'\[MEMORY_SAVE:\s*(.*?)\]'),
                        ("SYSTEM", execute_system, r'\[SYSTEM:\s*(.*?)\]')
                    ]
                    
                    for cmd, func, ptn in cmd_patterns:
                        if cmd not in executed:
                            m = re.search(ptn, full_resp, re.IGNORECASE)
                            if m:
                                executed.add(cmd)
                                arg = m.group(1).strip() if m.lastindex else ""
                                if cmd in ["VOLUME", "MEDIA", "WINDOW", "SYSTEM"]:
                                    arg = arg.lower()
                                threading.Thread(target=func, args=(arg,), daemon=True).start()

                    if re.search(r'[.!?]\s*$', sentence_buf) and ('[' not in sentence_buf or ']' in sentence_buf):
                        clean = clean_text_for_tts(sentence_buf)
                        if clean and not global_stop_event.is_set():
                            t_queue.put(clean)
                        sentence_buf = ""
                            
                if not (needs_file or needs_rag or needs_weather or needs_code) and sentence_buf.strip() and not global_stop_event.is_set():
                    t_queue.put(clean_text_for_tts(sentence_buf))
                
                final_tps = token_count / (time.time() - start_time) if time.time() - start_time > 0 else 0
                ui_queue.put(("TPS", f"⚡ {final_tps:.1f} t/s"))
                    
            except Exception as e:
                pass
            
            if global_stop_event.is_set():
                t_queue.put(None)
                break
                
            if needs_file or needs_rag or needs_weather or needs_code:
                global_stop_event.set()
                
            if not global_stop_event.is_set():
                t_queue.put(None)
                t_queue.join()
                p_queue.join()

            global_stop_event.set()
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
                
            global_stop_event.clear()
                
            if needs_file:
                file_info = find_and_read_local_file(file_query)
                messages.extend([
                    {"role": "assistant", "content": f"[READ_FILE: {file_query}]"},
                    {"role": "user", "content": f"{file_info}\nBitte helfe mir nun bezüglich dieser Datei."}
                ])
                needs_file = False
                continue
                
            if needs_rag:
                try:
                    res = "\n".join([f"- {r['title']}: {r['body']}" for r in DDGS().text(rag_query, max_results=3)])
                    messages.extend([
                        {"role": "assistant", "content": f"[DDG: {rag_query}]"}, 
                        {"role": "user", "content": f"Ergebnisse:\n{res}\nBitte beantworte die Frage kurz."}
                    ])
                except Exception:
                    messages.extend([
                        {"role": "assistant", "content": f"[DDG: {rag_query}]"}, 
                        {"role": "user", "content": "Suche fehlgeschlagen. Sag Bescheid."}
                    ])
                needs_rag = False
                continue
                    
            if needs_weather:
                messages.extend([
                    {"role": "assistant", "content": f"[WEATHER: {weather_loc}]"}, 
                    {"role": "user", "content": f"Wetter:\n{get_weather(weather_loc)}\nBitte sag das EXAKT an."}
                ])
                needs_weather = False
                continue

            if needs_code:
                try:
                    file_name = os.path.basename(generate_and_save_code(prompt_text))
                    messages.extend([
                        {"role": "assistant", "content": "Okay, ich lege los. [AGENT: CODE]"}, 
                        {"role": "user", "content": f"Datei '{file_name}' wurde gespeichert. Bestätige kurz."}
                    ])
                except Exception as e:
                    messages.extend([
                        {"role": "assistant", "content": "Okay, ich lege los. [AGENT: CODE]"}, 
                        {"role": "user", "content": f"Fehler beim Coden: {e}."}
                    ])
                needs_code = False
                continue
                
            break 
            
        if full_resp:
            messages.append({"role": "assistant", "content": full_resp})
            
        ui_queue.put(("STATE", "idle"))

# =========================================================
# GUI APP (CustomTkinter)
# =========================================================
class JarvisGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Jarvis AI")
        
        self.landscape_mode = CONFIG.get("landscape_mode", False)
        
        if self.landscape_mode:
            self.geometry("800x450")
        else:
            self.geometry("450x700")
            
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color="#121212")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        base_size = int(CONFIG.get("font_size", 16))
        self.font_main = ("Inter Light", base_size)
        self.font_title = ("Inter Light", int(base_size * 1.5), "bold")
        self.font_small = ("Inter Light", max(8, int(base_size * 0.75)))

        self.transcription_var = tk.StringVar(value="Warte auf 'Hey Jarvis'...")

        # 1. Top Bar (Settings left, Stop, TPS right)
        self.top_bar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_bar_frame.pack(fill="x", padx=10, pady=5)
        
        self.btn_settings = ctk.CTkButton(self.top_bar_frame, text="⚙️", width=30, height=30, fg_color="#222222", hover_color="#444444", command=self.open_settings)
        self.btn_settings.pack(side="left")
        
        self.btn_stop = ctk.CTkButton(self.top_bar_frame, text="⏹️", width=30, height=30, fg_color="#550000", hover_color="#770000", command=self.stop_audio_generation)
        self.btn_stop.pack(side="left", padx=(5, 0))
        
        self.lbl_tps = ctk.CTkLabel(self.top_bar_frame, text="⚡ 0.0 t/s", font=self.font_small, text_color="#aaaaaa")
        self.lbl_tps.pack(side="right")

        # 2. Main Content Container
        self.main_content = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content.pack(fill="both", expand=True)
        
        if self.landscape_mode:
            # --- QUERMODUS (Landscape) ---
            
            # Linke Seite (Nimmt den restlichen Platz ein)
            self.left_panel = ctk.CTkFrame(self.main_content, fg_color="transparent")
            self.left_panel.pack(side="left", fill="both", expand=True, padx=(20, 10))
            
            # Rechte Seite (Feste Breite für den Orb)
            self.right_panel = ctk.CTkFrame(self.main_content, fg_color="transparent", width=250)
            self.right_panel.pack(side="right", fill="y", padx=(10, 20))
            self.right_panel.pack_propagate(False) # Verhindert, dass die Box sich zusammenzieht
            
            # --- Elemente Links ---
            self.top_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
            self.top_frame.pack(side="top", fill="x", pady=5)
            
            # Die Transkription ("Du sagtest: ...") kommt ganz nach unten
            self.lbl_transcription = ctk.CTkLabel(self.left_panel, textvariable=self.transcription_var, font=self.font_small, text_color="#aaaaaa", wraplength=600, justify="center")
            self.lbl_transcription.pack(side="bottom", pady=(5, 10))
            
            # Die Jarvis Antwort-Box füllt den restlichen Platz in der Mitte
            self.jarvis_response_textbox = ctk.CTkTextbox(
                self.left_panel, font=self.font_main, text_color="#00FFFF", fg_color="transparent", wrap="word", state="disabled"
            )
            self.jarvis_response_textbox.pack(side="top", fill="both", expand=True, pady=10)
            
            # Coding-Fenster (Unsichtbar am Anfang)
            self.code_frame = ctk.CTkFrame(self.left_panel, fg_color="#1e1e1e", corner_radius=10)
            
            # --- Elemente Rechts ---
            self.orb_canvas = tk.Canvas(self.right_panel, width=200, height=200, bg="#121212", highlightthickness=0)
            self.orb_canvas.pack(expand=True) # Perfekt mittig im right_panel
            
        else:
            # --- HOCHFORMAT (Portrait) ---
            self.top_frame = ctk.CTkFrame(self.main_content, fg_color="transparent")
            self.top_frame.pack(fill="x", pady=5, padx=20)
            
            self.jarvis_response_textbox = ctk.CTkTextbox(
                self.main_content, font=self.font_main, text_color="#00FFFF", fg_color="transparent", height=240, wrap="word", state="disabled"
            )
            self.jarvis_response_textbox.pack(pady=(10, 5), fill="x", padx=20)
            
            self.orb_canvas = tk.Canvas(self.main_content, width=200, height=200, bg="#121212", highlightthickness=0)
            self.orb_canvas.pack(pady=20)
            
            self.lbl_transcription = ctk.CTkLabel(self.main_content, textvariable=self.transcription_var, font=self.font_small, text_color="#aaaaaa", wraplength=400, justify="center")
            self.lbl_transcription.pack(pady=10)
            
            self.code_frame = ctk.CTkFrame(self.main_content, fg_color="#1e1e1e", corner_radius=10)

        # Code TextBox (wird dynamisch reingepackt, wenn nötig)
        self.code_textbox = ctk.CTkTextbox(self.code_frame, font=("Consolas", 12), text_color="#00FFCC", fg_color="transparent")
        self.code_textbox.pack(fill="both", expand=True, padx=5, pady=5)

        self.timers = {}
        self.alarms = {}
        
        # Leuchtende Ringe initialisieren
        self.cx, self.cy = 100, 100
        self.r_inner = 40
        self.r_glow1 = 60
        self.r_glow2 = 80
        
        self.glow2 = self.orb_canvas.create_oval(self.cx-self.r_glow2, self.cy-self.r_glow2, self.cx+self.r_glow2, self.cy+self.r_glow2, fill="#1a1a1a", outline="")
        self.glow1 = self.orb_canvas.create_oval(self.cx-self.r_glow1, self.cy-self.r_glow1, self.cx+self.r_glow1, self.cy+self.r_glow1, fill="#252525", outline="")
        self.core = self.orb_canvas.create_oval(self.cx-self.r_inner, self.cy-self.r_inner, self.cx+self.r_inner, self.cy+self.r_inner, fill="#444444", outline="")
        
        self.bot_thread = threading.Thread(target=run_voice_bot, daemon=True)
        self.bot_thread.start()
        
        threading.Thread(target=keyboard_worker, daemon=True).start()
        
        self.after(100, self.process_ui_queue)

    def stop_audio_generation(self):
        global_stop_event.set()
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.jarvis_response_textbox.configure(state="normal")
        self.jarvis_response_textbox.delete("0.0", "end")
        self.jarvis_response_textbox.insert("end", "[Abgebrochen]")
        self.jarvis_response_textbox.configure(state="disabled")
        ui_queue.put(("STATE", "idle"))

    def on_closing(self):
        if sys.platform == "win32":
            os.system("taskkill /F /IM \"LM Studio.exe\" /T >nul 2>&1")
            os.system("taskkill /F /IM lms.exe /T >nul 2>&1")
        self.destroy()
        sys.exit(0)

    def open_settings(self):
        settings_win = ctk.CTkToplevel(self)
        settings_win.title("Einstellungen")
        settings_win.geometry("400x500")
        settings_win.attributes("-topmost", True)
        settings_win.configure(fg_color="#121212")
        
        scroll = ctk.CTkScrollableFrame(settings_win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(scroll, text="Lautstärke (0.0 - 1.0)", font=self.font_small).pack(pady=(10, 0))
        vol_slider = ctk.CTkSlider(scroll, from_=0.0, to=1.0)
        vol_slider.set(float(CONFIG.get("volume", 0.8)))
        vol_slider.pack(pady=5)
        
        ctk.CTkLabel(scroll, text="TTS Geschwindigkeit (z.B. +20%)", font=self.font_small).pack(pady=(10, 0))
        tts_entry = ctk.CTkEntry(scroll)
        tts_entry.insert(0, CONFIG.get("tts_rate", "+20%"))
        tts_entry.pack(pady=5)
        
        ctk.CTkLabel(scroll, text="Quermodus (Links Text, Rechts Orb)", font=self.font_small).pack(pady=(10, 0))
        landscape_var = ctk.BooleanVar(value=CONFIG.get("landscape_mode", False))
        landscape_switch = ctk.CTkSwitch(scroll, text="Aktivieren", variable=landscape_var)
        landscape_switch.pack(pady=5)
        
        ctk.CTkLabel(scroll, text="Schriftgröße (z.B. 16)", font=self.font_small).pack(pady=(10, 0))
        font_entry = ctk.CTkEntry(scroll)
        font_entry.insert(0, str(CONFIG.get("font_size", 16)))
        font_entry.pack(pady=5)
        
        ctk.CTkLabel(scroll, text="Stille vor Antwort (Sekunden, z.B. 0.6)", font=self.font_small).pack(pady=(10, 0))
        silence_entry = ctk.CTkEntry(scroll)
        silence_entry.insert(0, str(CONFIG.get("silence_duration", 0.60)))
        silence_entry.pack(pady=5)
        
        ctk.CTkLabel(scroll, text="System Prompt", font=self.font_small).pack(pady=(10, 0))
        prompt_box = ctk.CTkTextbox(scroll, height=150)
        prompt_box.insert("0.0", CONFIG.get("system_prompt", DEFAULT_CONFIG["system_prompt"]))
        prompt_box.pack(pady=5, fill="x", padx=10)
        
        ctk.CTkLabel(scroll, text="*Änderungen am Quermodus oder der Schriftgröße\nbenötigen einen Neustart.", text_color="#aaaaaa", font=("Inter Light", 10)).pack(pady=(10,0))
        
        def save_and_close():
            CONFIG["volume"] = vol_slider.get()
            CONFIG["tts_rate"] = tts_entry.get()
            CONFIG["landscape_mode"] = landscape_var.get()
            try:
                CONFIG["font_size"] = int(font_entry.get())
            except ValueError:
                pass
            try:
                CONFIG["silence_duration"] = float(silence_entry.get())
            except ValueError:
                pass
            CONFIG["system_prompt"] = prompt_box.get("0.0", "end").strip()
            
            save_config(CONFIG)
            settings_win.destroy()
            
        ctk.CTkButton(scroll, text="Speichern", command=save_and_close, fg_color="#007799", hover_color="#005577").pack(pady=20)

    def set_orb_state(self, state):
        if state == "idle":
            self.orb_canvas.itemconfig(self.glow2, fill="#1a1a1a")
            self.orb_canvas.itemconfig(self.glow1, fill="#252525")
            self.orb_canvas.itemconfig(self.core, fill="#444444")
        elif state == "listening":
            self.orb_canvas.itemconfig(self.glow2, fill="#003344")
            self.orb_canvas.itemconfig(self.glow1, fill="#007799")
            self.orb_canvas.itemconfig(self.core, fill="#00FFFF")
        elif state == "processing":
            self.orb_canvas.itemconfig(self.glow2, fill="#330033")
            self.orb_canvas.itemconfig(self.glow1, fill="#770077")
            self.orb_canvas.itemconfig(self.core, fill="#FF00FF")
        elif state == "speaking":
            self.orb_canvas.itemconfig(self.glow2, fill="#003311")
            self.orb_canvas.itemconfig(self.glow1, fill="#008833")
            self.orb_canvas.itemconfig(self.core, fill="#00FF66")

    def show_screenshot_popup(self, pil_image):
        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        
        x = self.winfo_screenwidth() - 320
        y = 50
        popup.geometry(f"300x200+{x}+{y}")
        
        img_resized = pil_image.resize((290, 190))
        ctk_img = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(290, 190))
        lbl = ctk.CTkLabel(popup, image=ctk_img, text="")
        lbl.pack(padx=5, pady=5)
        
        self.after(3000, popup.destroy)

    def process_ui_queue(self):
        while not ui_queue.empty():
            try:
                msg = ui_queue.get_nowait()
                cmd = msg[0]
                
                if cmd == "STATE":
                    self.set_orb_state(msg[1])
                    if msg[1] == "idle":
                        self.transcription_var.set("Warte auf 'Hey Jarvis'...")
                    elif msg[1] == "listening":
                        self.transcription_var.set("Ich höre...")
                        self.jarvis_response_textbox.configure(state="normal")
                        self.jarvis_response_textbox.delete("0.0", "end")
                        self.jarvis_response_textbox.configure(state="disabled")
                    elif msg[1] == "processing":
                        self.transcription_var.set("Verarbeite...")
                
                elif cmd == "TRANSCRIPTION":
                    self.transcription_var.set(f"Du: {msg[1]}")
                    
                elif cmd == "JARVIS_SAYS":
                    self.jarvis_response_textbox.configure(state="normal")
                    self.jarvis_response_textbox.delete("0.0", "end")
                    self.jarvis_response_textbox.insert("end", msg[1])
                    self.jarvis_response_textbox.see("end")
                    self.jarvis_response_textbox.configure(state="disabled")
                    
                elif cmd == "TPS":
                    self.lbl_tps.configure(text=msg[1])
                    
                elif cmd == "QUIT":
                    self.on_closing()
                    
                elif cmd == "TIMER_START":
                    tid, secs = msg[1], msg[2]
                    lbl = ctk.CTkLabel(self.top_frame, text=f"⏳ Timer: {secs}s", font=self.font_main, text_color="#FFA500")
                    lbl.pack(side="top", pady=2)
                    self.timers[tid] = lbl
                    
                elif cmd == "TIMER_TICK":
                    tid, remaining = msg[1], msg[2]
                    if tid in self.timers:
                        self.timers[tid].configure(text=f"⏳ Timer: {remaining}s")
                        
                elif cmd == "TIMER_END" or cmd == "TIMER_CANCEL":
                    tid = msg[1]
                    if tid in self.timers:
                        self.timers[tid].destroy()
                        del self.timers[tid]
                        
                elif cmd == "ALARM_START":
                    aid, t_time = msg[1], msg[2]
                    lbl = ctk.CTkLabel(self.top_frame, text=f"⏰ Wecker: {t_time}", font=self.font_main, text_color="#FF4444")
                    lbl.pack(side="top", pady=2)
                    self.alarms[aid] = lbl
                    
                elif cmd == "ALARM_END" or cmd == "ALARM_CANCEL":
                    aid = msg[1]
                    if aid in self.alarms:
                        self.alarms[aid].destroy()
                        del self.alarms[aid]
                        
                elif cmd == "CODE_START":
                    self.code_frame.pack(fill="both", expand=True, padx=10, pady=10)
                    self.code_textbox.delete("0.0", "end")
                    self.code_textbox.insert("end", "> Initialisiere Coding-Agent...\n")
                    
                elif cmd == "CODE_LOG":
                    self.code_textbox.insert("end", msg[1])
                    self.code_textbox.see("end")
                    
                elif cmd == "CODE_END":
                    self.code_frame.pack_forget()
                    
                elif cmd == "SCREENSHOT_PREVIEW":
                    self.show_screenshot_popup(msg[1])
                    
            except queue.Empty:
                break
                
        self.after(100, self.process_ui_queue)

if __name__ == "__main__":
    app = JarvisGUI()
    app.mainloop()
