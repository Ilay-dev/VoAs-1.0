# Voice-Controlled Local AI Assistant 🎙️

A blazing-fast, privacy-friendly voice assistant that runs entirely on your local machine. It combines local Speech-to-Text (Faster-Whisper), local LLMs (via LM Studio), and ultra-fast Text-to-Speech (Edge-TTS). 

It doesn't just talk – it interacts with your computer! It can open apps, search the web (in Chrome, Opera, etc.), read your clipboard, look at your screen, and control your system volume.

## ✨ Features

* **⚡ Ultra-Fast Voice Interaction:** Uses VAD (Voice Activity Detection) to stop recording the moment you stop speaking.
* **🧠 Local AI (Privacy First):** Connects to LM Studio to run models entirely offline.
* **🌐 Background Web Search (RAG):** If you ask for current events or the weather, it invisibly queries DuckDuckGo, feeds the facts to the AI, and reads the summary to you.
* **🖥️ PC Control:** Opens any program on your Windows/Mac system via voice.
* **🔊 Volume Control:** Adjust system volume using natural voice commands (Mute, Up, Down).
* **📋 Clipboard Reading:** Ask the AI to "explain the copied text" and it will read your clipboard.
* **👁️ Vision / Screen Capture:** Ask "What is on my screen?" to let the AI take a screenshot and analyze it (requires a multimodal Vision-LLM).
* **🔎 Browser Web Search:** Tell the AI to "Search for cats in Chrome" or "Search for Python in Opera", and it will automatically open the browser, type the query, and hit enter.

## 🚀 Installation & Setup

**1. Install Python 3.10+**  
Make sure Python is installed and added to your system PATH.

**2. Install dependencies**  
Run this command in your terminal to install all required libraries:
```bash
pip install numpy sounddevice pygame edge-tts mss pyautogui pyperclip pillow openai duckduckgo-search faster-whisper
