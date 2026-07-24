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
import numpy as np
import sounddevice as sd
import pygame
import edge_tts
import mss
import pyautogui
import pyperclip
from PIL import Image
from openai import OpenAI
from duckduckgo_search import DDGS  # NEU: Für die Hintergrund-Suche

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
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.020
SILENCE_DURATION = 0.60

# NEU: Variable für die Sprachgeschwindigkeit (Default ist +0% für aktuell)
TTS_RATE = "+0%"  

SCREENSHOT_TRIGGERS = ["schau", "siehst du", "bildschirm", "zeig", "guck", "look", "screen"]
TIME_TRIGGERS = ["uhrzeit", "wie viel uhr", "wie spät", "uhr ist es", "welche uhrzeit", "welcher tag", "datum"]
CLIPBOARD_TRIGGERS = ["zwischenablage", "zwischenspeicher", "kopierten text", "erklär den text"]

def ensure_lm_studio_running():
    print("🔍 Prüfe, ob LM Studio läuft...")
    try:
        with socket.create_connection(("localhost", 1234), timeout=1):
            print("✅ LM Studio ist bereits aktiv!")
            return
    except OSError:
        print("⏳ LM Studio läuft nicht. Versuche Auto-Start mit 'llmmistralai/ministral-3-3b'...")
        try:
            subprocess.Popen(
                "lms server start llmmistralai/ministral-3-3b",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            for _ in range(20):
                time.sleep(1)
                try:
                    with socket.create_connection(("localhost", 1234), timeout=1):
                        print("🚀 LM Studio erfolgreich gestartet!")
                        return
                except OSError:
                    pass
            print("⚠️ Warnung: Auto-Start dauert ungewöhnlich lange. Bitte prüfen, ob die 'lms' CLI installiert ist.")
        except Exception as e:
            print(f"❌ Fehler beim Starten von LM Studio: {e}")
            input("Drücke ENTER, sobald du LM Studio manuell gestartet hast...")

ensure_lm_studio_running()
pygame.mixer.init()

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
    # Filtert alle System-Tags heraus, damit sie nicht vorgelesen werden
    text = re.sub(r'\[OPEN:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[SEARCH:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[DDG:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[VOLUME:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[.*?\]', '', text) 

    text = re.sub(r'(\d{1,2}):(\d{2})', r'\1 Uhr \2', text)
    text = re.sub(r'[*_#~`>\[\]]', '', text)
    text = re.sub(r'^\s*[-+•]\s*', '', text)
    text = text.replace(',', '')
    return text.strip()

def get_current_time():
    now = datetime.datetime.now()
    return now.strftime("Es ist %H Uhr %M am %d.%m.%Y.")

def capture_main_screen_base64():
    with mss.MSS() as sct:
        main_monitor = sct.monitors[1]
        sct_img = sct.grab(main_monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

def execute_system_commands(ai_response):
    """Sucht nach Tags in der KI-Antwort und führt sie lokal aus."""

    # 1. Programm öffnen
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

    # 2. Web-Suche in Opera anzeigen (Expliziter Wunsch des Nutzers)
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

    # 3. Lautstärke steuern
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
# 4. FAST RECORDING & VAD
# =========================================================

def record_audio_until_silence():
    print("\n🎙️ Höre zu...")
    audio_data = []
    silent_chunks = 0
    chunk_size = int(SAMPLE_RATE * 0.05)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32') as stream:
        has_started_speaking = False
        
        while True:
            chunk, _ = stream.read(chunk_size)
            amplitude = np.max(np.abs(chunk))
            
            if amplitude > SILENCE_THRESHOLD:
                has_started_speaking = True
                silent_chunks = 0
            elif has_started_speaking:
                silent_chunks += 1
                
            if has_started_speaking:
                audio_data.append(chunk)
                
            if has_started_speaking and (silent_chunks * 0.05) >= SILENCE_DURATION:
                break
                
    return np.concatenate(audio_data, axis=0).flatten()

# =========================================================
# 5. WORKER THREADS
# =========================================================

def monitor_keyboard_input(stop_ev):
    while not stop_ev.is_set():
        if sys.platform == "win32" and msvcrt.kbhit():
            key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
            if key == 'x':
                print("\n🛑 [Unterbrechung per Taste 'X'!]")
                stop_ev.set()
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                break
        time.sleep(0.05)

async def generate_tts_stream(t_queue, p_queue, stop_ev):
    while not stop_ev.is_set():
        try:
            text = await asyncio.to_thread(t_queue.get)
        except Exception:
            break

        if text is None:
            p_queue.put(None)
            t_queue.task_done()
            break
            
        if stop_ev.is_set():
            t_queue.task_done()
            break
            
        try:
            text_cleaned = clean_text_for_tts(text)
            if text_cleaned and not stop_ev.is_set():
                # HIER IST NUMMER 3: Nutzt die konfigurierte Geschwindigkeits-Variable
                communicate = edge_tts.Communicate(text_cleaned, "de-DE-KillianNeural", rate=TTS_RATE)
                audio_bytes = io.BytesIO()
                
                async for chunk in communicate.stream():
                    if stop_ev.is_set():
                        break
                    if chunk["type"] == "audio":
                        audio_bytes.write(chunk["data"])
                
                if not stop_ev.is_set():
                    audio_bytes.seek(0)
                    p_queue.put(audio_bytes)
        except Exception:
            pass
        finally:
            t_queue.task_done()

def start_tts_worker(t_queue, p_queue, stop_ev):
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(generate_tts_stream(t_queue, p_queue, stop_ev))
        except Exception:
            pass
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except Exception:
                pass
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

def audio_player_worker(p_queue, stop_ev):
    while not stop_ev.is_set():
        try:
            audio_bytes = p_queue.get()
        except Exception:
            break

        if audio_bytes is None:
            p_queue.task_done()
            break
            
        if stop_ev.is_set():
            p_queue.task_done()
            break
            
        try:
            pygame.mixer.music.load(audio_bytes)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if stop_ev.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(60)
            pygame.mixer.music.unload()
        except Exception:
            pass
        finally:
            p_queue.task_done()

# =========================================================
# 6. MAIN BOT LOOP
# =========================================================

def run_voice_bot():
    print("\n🚀 Sprachbot startklar!")
    print("💡 Drücke im Terminal jederzeit 'x', um das Sprechen der KI abzubrechen.")

    messages = [
        {
            "role": "system", 
            "content": (
                "Du bist ein extrem schneller, präziser Sprachassistent. "
                "Antworte auf Deutsch in maximal 1-2 kurzen Sätzen. "
                "Verwende keine Sternchen (*), Rautenzeichen (#) oder Unterstriche (_). "
                "Schreibe Uhrzeiten IMMER als Wort (z.B. '14 Uhr 30').\n\n"
                "=== SYSTEM-BEFEHLE ===\n"
                "Setze folgende Befehle ans Ende deiner Antwort, falls nötig:\n"
                "1. [OPEN: appname] (Öffnet ein Programm am PC)\n"
                "2. [SEARCH: suchbegriff] (Nutze dies NUR, wenn der Nutzer EXPLIZIT sagt 'Zeige mir Suchergebnisse für...' oder 'Such das in Opera')\n"
                "3. [VOLUME: up/down/mute] (Lautstärke anpassen)\n\n"
                "=== INTERNET HINTERGRUND-SUCHE (WICHTIG) ===\n"
                "Wenn der Nutzer dich nach Fakten, dem Wetter, Nachrichten oder Dingen fragt, die du ohne Internet nicht sicher weißt, "
                "antworte als ALLERERSTES mit dem Tag [DDG: suchbegriff] (z.B. [DDG: Wetter Berlin]). "
                "Wir machen dann im Hintergrund eine Google-Suche für dich und du kannst danach antworten."
            )
        }
    ]

    while True:
        try:
            audio = record_audio_until_silence()
        except KeyboardInterrupt:
            print("\n👋 Bot beendet.")
            sys.exit(0)
        
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
            
        print(f"\n👤 Du: {user_text}")
        text_lower = user_text.lower()

        is_time_req = any(t in text_lower for t in TIME_TRIGGERS)
        is_screen_req = any(s in text_lower for s in SCREENSHOT_TRIGGERS)
        is_clip_req = any(c in text_lower for c in CLIPBOARD_TRIGGERS)

        user_content = []
        prompt_text = user_text
        
        if is_time_req:
            prompt_text = f"[System-Info: {get_current_time()}]\n{prompt_text}"

        # NEU: Zwischenablage auslesen, wenn getriggert (Nummer 2)
        if is_clip_req:
            try:
                clip_text = pyperclip.paste()
                if clip_text:
                    print("📋 [System] Lese Zwischenablage aus...")
                    prompt_text += f"\n[Inhalt der Zwischenablage: {clip_text}]"
            except Exception:
                pass

        user_content.append({"type": "text", "text": prompt_text})

        if is_screen_req:
            print("📸 [System] Screenshot wird erstellt...")
            img_b64 = capture_main_screen_base64()
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        messages.append({"role": "user", "content": user_content})
        
        # --- RAG SCHLEIFE (Maximal 2 Durchläufe) ---
        needs_rag_search = False
        rag_query = ""
        full_response = ""
        
        for attempt in range(2):
            current_stop_event = threading.Event()
            current_tts_queue = queue.Queue()
            current_playback_queue = queue.Queue()

            if attempt == 0:
                print("🤖 Bot: ", end="", flush=True)
                
            start_tts_worker(current_tts_queue, current_playback_queue, current_stop_event)
            threading.Thread(target=audio_player_worker, args=(current_playback_queue, current_stop_event), daemon=True).start()
            threading.Thread(target=monitor_keyboard_input, args=(current_stop_event,), daemon=True).start()
            
            sentence_buffer = ""
            full_response = ""
            
            try:
                response_stream = llm_client.chat.completions.create(
                    model="local-model",
                    messages=messages,
                    stream=True,
                    temperature=0.3,
                    max_tokens=150
                )

                for chunk in response_stream:
                    if current_stop_event.is_set():
                        break

                    raw_token = chunk.choices[0].delta.content or ""
                    print(raw_token, end="", flush=True)
                    
                    sentence_buffer += raw_token
                    full_response += raw_token
                    
                    # RAG-Erkennung im Stream (Nummer 1: DuckDuckGo)
                    match = re.search(r'\[DDG:\s*(.*?)\]', full_response, re.IGNORECASE)
                    if match:
                        rag_query = match.group(1).strip()
                        needs_rag_search = True
                        break  # Bricht den Stream ab, damit gesucht werden kann!
                        
                    # Standard TTS-Verarbeitung (nur wenn keine offene Klammer da ist, die auf ein Tag hindeutet)
                    if re.search(r'[.!?]\s*$', sentence_buffer):
                        if '[' not in sentence_buffer or ']' in sentence_buffer:
                            clean_chunk = clean_text_for_tts(sentence_buffer)
                            if clean_chunk and not current_stop_event.is_set():
                                current_tts_queue.put(clean_chunk)
                            sentence_buffer = ""
                            
                # Letzten Satz in den TTS packen, falls kein RAG ausgelöst wurde
                if not needs_rag_search and sentence_buffer.strip() and not current_stop_event.is_set():
                    current_tts_queue.put(clean_text_for_tts(sentence_buffer))
                    
            except KeyboardInterrupt:
                print("\n👋 Bot abgebrochen.")
                sys.exit(0)
            except Exception as e:
                print(f"\n⚠️ Verbindungsfehler: {e}")
                
            # Threads für diesen Versuch beenden
            if not current_stop_event.is_set():
                current_tts_queue.put(None)
                current_tts_queue.join()
                current_playback_queue.join()

            current_stop_event.set()
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
                
            # --- HINTERGRUND-SUCHE AUSFÜHREN ---
            if needs_rag_search:
                print(f"\n🔍 [Hintergrund-Suche] Hole aktuelle Daten für '{rag_query}'...")
                try:
                    ddg_results = DDGS().text(rag_query, max_results=3)
                    context_text = "\n".join([f"- {res['title']}: {res['body']}" for res in ddg_results])
                    print("✅ Ergebnisse gefunden. Generiere Antwort...")
                    
                    # KI bekommt die neuen Daten angehängt
                    messages.append({"role": "assistant", "content": f"[DDG: {rag_query}]"})
                    messages.append({
                        "role": "user", 
                        "content": f"Hier sind die aktuellen Web-Ergebnisse dazu:\n{context_text}\nBitte beantworte meine Frage basierend auf diesen Fakten."
                    })
                    needs_rag_search = False
                    continue  # Startet Attempt 2 mit den neuen Kontext-Daten
                except Exception as e:
                    print(f"\n⚠️ Fehler bei Web-Suche: {e}")
                    messages.append({"role": "assistant", "content": f"[DDG: {rag_query}]"})
                    messages.append({"role": "user", "content": "Die Webrecherche ist fehlgeschlagen. Sag mir einfach kurz, dass du die Daten gerade nicht abrufen kannst."})
                    needs_rag_search = False
                    continue

            # Wenn keine DDG-Suche nötig war (Attempt 1 fertig) oder Attempt 2 (nach Suche) beendet ist:
            break 

        execute_system_commands(full_response)
        messages.append({"role": "assistant", "content": full_response})

if __name__ == "__main__":
    try:
        run_voice_bot()
    except KeyboardInterrupt:
        print("\n👋 Tschüss!")
        sys.exit(0)