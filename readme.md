# ⚙️ SAM — Smart Autonomous Mechanism
### The Next-Generation Personal AI Assistant & Autonomous OS Companion
**Engineered by [Nemaan Shaikh](https://github.com/Nemo1506)**

[![Python Version](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-CC%20BY--NC%204.0-orange.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()
[![Voice](https://img.shields.io/badge/Voice-Faster--Whisper%20%7C%20Edge--TTS-green.svg)]()
[![Model](https://img.shields.io/badge/AI%20Brain-Google%20Gemini%20Flash-8E75C4.svg)]()

> *"SAM is where the assistant stops being a basic tool and starts being a true digital presence. It remembers your projects, guards your system, builds software while you sleep, and reaches out when it has something meaningful to say."*

---

## 🌟 Overview

**SAM** is a real-time, autonomous, voice-activated AI companion capable of hearing, seeing, writing code, and controlling your entire operating system. Built on Google Gemini's flagship multimodal intelligence and powered by on-device Whisper voice detection, SAM provides zero-subscription, local-first control of your digital life.

Whether you need an assistant to manage your PC files, an empathetic companion to look after your health, an automated calling agent that rings your phone when a job is done, or an autonomous software architect to build an entire project overnight &mdash; **SAM does it all.**

---

## ⚡ Core Capabilities

### 1. 🎙️ Natural Voice & On-Device Wake Word
- **"Hey Sam" Activation**: Continuous low-latency on-device speech detection via `Faster-Whisper` (CPU/int8 optimized &mdash; no missing CUDA DLL dependencies).
- **Optional Clap-to-Wake**: Energy transient detector wakes SAM on double-clap.
- **Multilingual Mastery**: Fully fluent in **English**, **Hindi / Hinglish**, and **Turkish** (*"efendim"*).
- **Adaptive Speech**: Neural text-to-speech with natural cadence and instant spoken acknowledgements for long tasks.

### 2. 🌙 Autonomous Overnight Project Builder (`dev_agent` & `autonomous_task`)
- **Unattended Execution**: Tell SAM *"build me a full-stack dashboard project with tests by tomorrow morning"* &mdash; SAM generates architectural blueprints, writes every source file, executes self-healing syntax checks, runs tests, and saves completed deliverables into `projects/`.
- **Fault-Tolerant Checkpoints**: Saves atomic progress states to disk. If your PC restarts or shuts down mid-build, SAM resumes right where it left off.
- **Milestone Monitor**: Query *"How is the overnight project coming along?"* anytime for detailed task breakdowns.

### 3. 📱 Mobile Phone Integration & Outbound Voice Calling (`phone_notifier`)
- **Direct Phone Connectivity**: Pair your mobile device via Twilio Voice API or Windows Phone Link.
- **Automated Alerts**: SAM can place an outbound voice call or send SMS/WhatsApp notifications to your personal cell phone the moment an overnight build finishes or if critical attention is required.

### 4. 💖 Full Spectrum Emotional Intelligence & SAM Care (`emotional_support`)
- **Human Emotional Resonance**: Responds with genuine empathy and authentic human connection across all emotional states—celebrates wins and shared happiness enthusiastically, provides soothing presence during sadness, offers non-judgmental listening during anger, and grounds you during anxiety.
- **Mood-Lifting & De-Stressing**: Lights up your mood with cheerful humor, guided 4-7-8 breathing exercises, and instant relaxing/celebration soundtrack playback via YouTube.
- **Mood & Wellness Tracking**: Logs emotional check-ins, tracks mood history over time, and provides wellness trends on demand.
- **Supportive Desktop Routines**: Offers to dim display brightness, set restful stretch/hydration reminders, or take over PC chores so you can pause and recharge.

### 5. 🗄️ Full PC Data Mastery & File Operations (`file_controller`)
- **Deep Drive Access**: Scan, search, read, write, move, organize, and summarize files across all local drives (`C:`, `D:`, etc.).
- **Smart Attachment Reader**: Directly inspects PDFs, Word documents (`.docx`), presentations (`.pptx`), source code (`.py`, `.ts`, `.json`), and images with built-in privacy safeguards.

### 6. 📊 Real-Time Hardware Telemetry (`system_status` & `system_monitor`)
- **Live Diagnostics**: Speaks or logs live CPU utilization, core counts, RAM memory pressure, disk storage availability, battery health, and uptime.
- **Proactive Thermal Protection**: Background hardware monitoring alerts you if high thermal limits or critical memory exhaustion occur.

### 7. 👁️ Multimodal Screen & Webcam Vision (`screen_processor`)
- **Real-Time Vision**: Analyzes your current display or active webcam stream in real-time using Gemini multimodal vision.
- **Hardware Camera Discovery**: Automatically probes and initializes connected camera peripherals (with DirectShow backend on Windows).

### 8. 🌐 Deep Browser & Web Automation (`browser_control` & `web_search`)
- **Playwright Automation**: Navigate websites, search information, manage Gmail inboxes, draft emails, and inspect GitHub PRs/issues using your native browser session.
- **Parallel News & Grounded Search**: Dual-thread retrieval combining Gemini Grounded Search and live DuckDuckGo feeds.

### 9. 🌐 Encrypted Web Dashboard & Mathematical Formatting (`dashboard/`)
- **Real-Time Web Interface**: Access SAM from any browser on your local network (mobile, tablet, or secondary PC) with live WebSockets.
- **Pure CSS Math Typesetting (`math.css`)**: Native, responsive mathematical rendering for fractions, summations with limits, powers, square roots, and LaTeX-style display equations without heavy external JavaScript libraries.
- **Application-Layer Encryption**: Secured with AES-256-CBC session encryption.
- **Media & Camera Tools**: Live camera snapshots, video recording with audio, voice memos, and document uploads.

### 10. 🦙 Ollama & Local LLM Offline Fallback (`llm_client`)
- **Local Model Routing**: Dynamic routing between Google Gemini and local LLMs (Ollama with `deepseek-r1` or `hermes3`, LM Studio, LocalAI) for full offline privacy.
- **Persistent Chat Archive**: Query, search, or review previous conversations and session summaries with `"what did we discuss earlier?"`

---

## 🖥️ PyQt6 Sci-Fi Desktop HUD

SAM features an animated holographic desktop interface built with PyQt6:
- **Reactive Waveform Visualizer**: Animates in real-time as SAM listens, thinks, and speaks.
- **Status Badges**: Visual indicators for `LISTENING`, `THINKING`, `SPEAKING`, and `COMMAND` modes.
- **Telemetry Console**: Clean real-time log of system events, fast intent resolutions, and hardware alerts.
- **Interactive Controls**: Instant microphone mute/unmute, emergency interrupt button, and camera preview window.

---

## 🗂️ Project Architecture

```
SAM-ThePersonalAssistant/
├── main.py                     # Main orchestrator: UI, voice listener, & intent dispatcher
├── ui.py                       # PyQt6 Sci-Fi holographic HUD interface
├── run_sam.bat                 # One-click Windows desktop launcher
├── validate.py                 # Automated release validation suite
├── requirements.txt            # Python dependencies
├── actions/                    # Autonomous capability modules
│   ├── autonomous_task.py      # Overnight autonomous agent engine
│   ├── dev_agent.py            # Complete project architect & code generator
│   ├── background_monitor.py   # Long-term task milestone & news monitor
│   ├── phone_notifier.py       # Cell phone pairing & outbound calling
│   ├── reminder.py             # Timers, health check-ins, & OS notifications
│   ├── emotional_support.py    # Empathy, stress-relief, & wellness check-ins
│   ├── chat_history.py         # Previous chats querying & search archive
│   ├── system_status.py        # Hardware telemetry (CPU, RAM, GPU, Disk, Battery)
│   ├── system_monitor.py       # Background hardware threshold watcher
│   ├── file_controller.py      # Deep file system reading, writing, & searching
│   ├── file_processor.py       # Document parsing (PDF, DOCX, PPTX, XLSX)
│   ├── computer_settings.py    # Volume, brightness, WiFi, & power management
│   ├── computer_control.py     # Windows control, keystrokes, & shortcuts
│   ├── screen_processor.py     # Multimodal screen & webcam vision
│   ├── browser_control.py      # Playwright browser, Gmail, & GitHub automation
│   ├── web_search.py           # Gemini Grounded + DDG search engine
│   ├── open_app.py             # System application launcher
│   ├── proactive.py            # Context-aware proactive assistant check-ins
│   ├── weather_report.py       # Live weather updates
│   ├── youtube_video.py        # Voice-controlled YouTube playback
│   └── game_updater.py         # Steam & Epic Games update checker
├── dashboard/                  # Encrypted web dashboard & assets
│   ├── server.py               # FastAPI & WebSockets local dashboard server
│   └── static/
│       ├── app.html            # Real-time web companion application
│       ├── login.html          # Session login & AES authorization
│       ├── math.css            # Pure CSS mathematical typesetting system
│       └── crypto-js.min.js    # Client-side AES encryption library
├── core/                       # Cognitive foundations
│   ├── brain_router.py         # Fast tool routing & LLM dispatch
│   ├── intent_analyzer.py      # Zero-latency local regex intent engine
│   ├── llm_client.py           # Gemini & local Ollama / LM Studio client
│   ├── stt.py                  # Faster-Whisper on-device speech-to-text
│   ├── tts.py                  # Neural text-to-speech player
│   └── prompt.txt              # SAM core protocol & identity directives
├── config/                     # Configuration files (API keys gitignored)
│   ├── api_keys.example.json   # Template for API keys & model endpoints
│   ├── api_keys.json           # Active credentials (local only)
│   └── sam.ico                 # SAM application icon
├── memory/                     # Long-term persistence
│   ├── memory_manager.py       # Profile, context, and language store
│   └── long_term.json          # Persistent cross-session user memories
└── tests/                      # Automated test suite
    └── run_tests.py            # Unit test runner
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python**: Version `3.11`, `3.12`, or `3.13` installed.
- **Operating System**: Windows 10/11, macOS, or Linux (Windows recommended for full OS integration).
- **Microphone**: Working microphone for voice interaction.
- **Google Gemini API Key**: Free key from [Google AI Studio](https://aistudio.google.com/).

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Nemo1506/SAM-ThePersonalAssistant.git
   cd SAM-ThePersonalAssistant
   ```

2. **Create and activate a virtual environment (recommended)**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure your API key**:
   Copy the example config:
   ```bash
   copy config\api_keys.example.json config\api_keys.json    # Windows
   cp config/api_keys.example.json config/api_keys.json      # Linux/macOS
   ```
   Open `config/api_keys.json` and insert your Gemini API key:
   ```json
   {
       "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
       "os_system": "windows",
       "assistant_name": "SAM",
       "wake_word_enabled": true
   }
   ```

5. **Verify the installation**:
   ```bash
   python validate.py
   python tests/run_tests.py
   ```

6. **Launch SAM**:
   - Double-click [`run_sam.bat`](run_sam.bat) or run:
   ```bash
   python main.py
   ```

---

## 🗣️ Voice Commands & Example Queries

| Intent | Say to SAM |
|---|---|
| **Wake Word** | *"Hey Sam"* or *"Hey Sam, how are you today?"* |
| **Overnight Project** | *"Hey Sam, build me an overnight project: a FastAPI REST API for book management with SQLite and unit tests."* |
| **Project Status** | *"Hey Sam, how is my overnight project coming along?"* |
| **PC Health & Telemetry** | *"Hey Sam, what's my CPU and RAM usage right now?"* |
| **File Operations** | *"Hey Sam, find all PDF files in my Downloads folder modified this week."* |
| **Emotional Support (Sad/Stress)** | *"Hey Sam, I had a really exhausting and stressful day."* |
| **Celebrating Success & Joy** | *"Hey Sam, I got the job! I'm so happy!"* |
| **Mood Lightener & Humor** | *"Hey Sam, light up my mood with something cheerful."* |
| **Guided Breathing** | *"Hey Sam, help me relax with a breathing exercise."* |
| **Mood Wellness History** | *"Hey Sam, how has my mood been lately?"* |
| **Wellness Reminders** | *"Hey Sam, remind me to drink water and take a stretch in 45 minutes."* |
| **Phone Call Alerts** | *"Hey Sam, test my phone connection and call my cell phone when the project finishes."* |
| **Screen Perception** | *"Hey Sam, take a look at my screen and explain what's in this diagram."* |
| **Webcam Vision** | *"Hey Sam, look through my camera and tell me what you see."* |
| **System Settings** | *"Hey Sam, set volume to 40% and open Spotify."* |

---

## 🔒 Security & Privacy

- **On-Device Speech Processing**: Continuous wake word listening runs locally on your CPU using Faster-Whisper. Audio is never continuously streamed to cloud servers.
- **Privacy Safeguard for Files**: Sensitive local files and attachments are analyzed locally or strictly with explicit user consent.
- **Git Protection**: Your `config/api_keys.json`, SSL certificates, session logs, and checkpoints are strictly ignored in `.gitignore`. Never commit API keys.

---

## 📄 License

This project is licensed under **[Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/)**.
Free for personal and educational use.

---

## 👤 Author & Acknowledgements

Created with passion by **Nemaan Shaikh**
- GitHub: [@Nemo1506](https://github.com/Nemo1506)

*SAM &mdash; Always ready, always listening, always building.*