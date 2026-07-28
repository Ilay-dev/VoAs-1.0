
# Jarvis AI - Desktop Sprachassistent

Ein lokaler, offline-fähiger und sprachgesteuerter KI-Assistent für Windows. Jarvis nutzt OpenWakeWord für die Aktivierung, Faster-Whisper für die Spracherkennung und verbindet sich über LM Studio mit lokalen Large Language Models (LLMs), um Aufgaben auf dem Desktop auszuführen, Code zu schreiben und Fragen zu beantworten.

## Inhaltsverzeichnis
1. Überblick
2. Hauptfunktionen
3. Voraussetzungen
4. Installation
5. Verwendung
6. Verfügbare Sprachbefehle
7. Einstellungen

## Überblick
Jarvis läuft im Hintergrund und hört auf das Wake-Word "Hey Jarvis". Sobald er aktiviert wird, nimmt er Sprachbefehle entgegen, verarbeitet diese über ein lokales Sprachmodell und antwortet per Text-to-Speech. Das System verfügt über eine Benutzeroberfläche, die je nach Bildschirmgröße im Hoch- oder Quermodus betrieben werden kann.

## Hauptfunktionen

- Sprachsteuerung & Wake-Word: Nahtlose Aktivierung durch "Hey Jarvis" ohne Tastendruck.
- Lokale Code-Generierung: Ein spezialisierter Coder-Agent kann Skripte (.py, .html, .js, .cpp) direkt generieren, speichern und bei Bedarf überarbeiten oder überschreiben.
- Vision (Bildschirmanalyse): Jarvis kann auf Befehl Screenshots vom aktiven Monitor machen und den Bildschirminhalt analysieren.
- Dateien lesen: Durchsucht das lokale Verzeichnis nach Dateinamen und liest deren Inhalt als Kontext für die KI ein.
- Langzeitgedächtnis: Wichtige Fakten über den Nutzer werden in einer SQLite-Datenbank gespeichert und kontextbasiert wieder abgerufen.
- Systemsteuerung: Steuerung von Lautstärke, Medien, Fenster-Management, Öffnen von Programmen und Herunterfahren des PCs.
- Automatisierung: Automatisierte Web-Recherche, YouTube-Suchen im Browser und Wetterabfragen.
- Timer & Wecker: Visuelle und akustische Timer und Alarme direkt in der Benutzeroberfläche integriert.

## Voraussetzungen

- Betriebssystem: Windows 10 oder 11
- Python: Version 3.10 oder neuer
- LM Studio: Muss installiert sein (für das lokale LLM, Standard-Port: 1234)
- Mikrofon & Lautsprecher

## Installation

1. Repositorium klonen oder herunterladen und in das Projektverzeichnis wechseln.
2. Pakete installieren:
   ```bash
   pip install requests numpy sounddevice pygame edge-tts mss pyautogui pyperclip Pillow openai customtkinter keyboard duckduckgo-search openwakeword pywin32 faster-whisper torch
   ```
3. LM Studio konfigurieren:
   - Lade ein Standard-Modell herunter (z.B. ministral-3-3b).
   - Lade ein Coder-Modell herunter (z.B. qwopus3.5-9b-coder).
   - Starte den lokalen Server in LM Studio auf Port 1234.
4. Skript starten:
   ```bash
   python main.py
   ```

## Verwendung

Sobald das Skript gestartet wurde, erscheint die Benutzeroberfläche. Jarvis befindet sich im Leerlauf. Sprich das Aktivierungswort "Hey Jarvis" deutlich in das Mikrofon. Ein kurzer Ton signalisiert die Aktivierung. Nun kannst du deinen Befehl einsprechen. 

Ein Klick auf den Stop-Button oben links bricht laufende Text- und Audioausgaben sofort ab. Die Tastenkombination "x" erfüllt denselben Zweck.

## Sprachbefehle

Jarvis unterstützt natürliche Sprache. Einige Trigger-Wörter aktivieren spezifische Funktionen:

- Programme öffnen: "Öffne Blender" oder "Starte Taschenrechner"
- Bildschirm analysieren: "Was siehst du auf dem Bildschirm?"
- Wetter abfragen: "Wie wird das Wetter in Berlin?" (Ohne Ortsangabe wird standardmäßig München gewählt)
- Web-Suche: "Suche nach dem höchsten Berg der Welt"
- YouTube-Suche: "Suche auf YouTube nach Python Tutorials"
- Timer & Wecker: "Stelle einen Timer auf 60 Sekunden", "Stelle einen Wecker auf 18:30 Uhr"
- Timer löschen: "Lösche alle Timer" oder "Stoppe den Wecker"
- Systemsteuerung: "Mache den Ton lauter", "Nächster Song", "Minimiere alle Fenster"
- Dateien lesen: "Schau dir meine Datei script an"
- Programmieren: "Schreibe ein Python Skript für einen Taschenrechner" oder "Verbessere den Code von meiner test.py"
- Gedächtnis: "Merke dir, dass mein Name Max ist"
- Beenden / Herunterfahren: "Jarvis, beende dich" oder "Fahre meinen PC herunter"

## Einstellungen

Oben links in der Anwendung befindet sich ein Einstellungen-Button. Dort können folgende Parameter dauerhaft in der jarvis_config.json gespeichert werden:

- Lautstärke: Zwischen 0.0 und 1.0 skalierbar.
- TTS Geschwindigkeit: Anpassen der Sprechgeschwindigkeit.
- Quermodus: Wechselt das Layout zu einem breiten Format für kleine Bildschirme.
- Schriftgröße: Basis-Schriftgröße anpassen.
- Stille vor Antwort: Zeit in Sekunden, bevor Jarvis die Aufnahme stoppt.
- System Prompt: Der grundlegende Prompt, der definiert, wie sich Jarvis verhält.
