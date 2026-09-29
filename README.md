# ShortBot ⚡

> **AI-Powered YouTube Shorts Curator, Downloader, and Video Compiler.**  
> Built as a modern **Firefox WebExtension** backed by a **zero-dependency Windows Desktop Companion Engine**.

---

## ✨ Features

- **🧠 Dual AI Curation Engine**:
  - **Cloud Mode**: Direct integration with Google Gemini Flash API for high-level semantic filtering and reasoning.
  - **Offline NLP Engine**: Built-in, zero-dependency tokenization, semantic scoring, and relevance classification that works 100% offline.
  - **No Ollama Required**: Runs smoothly on any PC without heavy local LLMs or gigabytes of VRAM.
- **⚡ Blazing Fast In-Process Downloads**:
  - Embedded `yt-dlp` stream resolver with real-time percentage, speed, and ETA hooks.
  - Automatic multi-client fallback strategies (`android`, `ios`, `web`) to bypass 429 rate limits and bot challenges.
- **🎨 Custom Watermarking & Branding**:
  - Dynamically brand downloaded shorts with customizable text, positioning, and styling using bundled FFmpeg.
- **🎬 One-Click Compilation**:
  - Seamlessly merge multiple curated shorts into a single video with normalized aspect ratios, frame rates, and audio streams.
- **🦊 Native Firefox & Chromium Support**:
  - Manifest V3 WebExtension supporting Mozilla Firefox (Promises/`browser.runtime`) and Chromium (`chrome.runtime`).
  - Native Messaging Host bridges browser extension requests directly to the companion engine with silent auto-launch.

---

## 🏗️ Architecture

```
┌─────────────────────────────────┐
│     Mozilla Firefox Add-on      │
│  (Modern MV3 Glassmorphism UI)  │
└────────────────┬────────────────┘
                 │ Native Messaging / HTTP
                 ▼
┌─────────────────────────────────┐
│   ShortBot Companion Engine     │
│   (Standalone Windows Binary)   │
├────────────────┬────────────────┤
│  Native Host   │  Bundled FFmpeg│
│  (stdio bridge)│  (watermark &  │
│                │   compilation) │
├────────────────┴────────────────┤
│       Dual AI Curator           │
│  Gemini Flash API + Offline NLP │
└─────────────────────────────────┘
```

---

## 🚀 Quick Start (For Users)

### 1. Run the Desktop Companion Engine
1. Extract `ShortBot-Engine-Windows.zip` or open the `ShortBot-Engine` folder.
2. Double-click **`Install-ShortBot.bat`**.
   - This automatically registers the native host for Firefox, Edge, and Chrome, and starts the companion engine silently.

### 2. Load the Firefox Extension
1. Open **Mozilla Firefox** and go to `about:debugging#/runtime/this-firefox`.
2. Click **"Load Temporary Add-on..."**.
3. Select `shortbot-firefox.xpi` (or `ui/manifest.json`).
4. Click the ShortBot icon in your toolbar and start curating Shorts!

---

## 🛠️ Developer Guide

### Prerequisites
- Python 3.10+
- FFmpeg (optional in dev, auto-bundled in production build)
- Node.js (optional for enhanced signature decryption)

### Running Locally
```powershell
# 1. Clone repository
git clone https://github.com/bigmanrohan12/ShortBot.git
cd ShortBot

# 2. Set up virtual environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Register native host for local dev
.\register_native_host.bat

# 4. Start local backend
python backend.py
```

### Packaging Builds

#### Build Firefox Extension
```powershell
python package_firefox_extension.py
# Outputs: dist/shortbot-firefox.xpi and dist/shortbot-firefox.zip
```

#### Build Standalone Windows Engine (Zero-Dependency)
```powershell
python build_companion_engine.py
# Packages complete executable, bundled FFmpeg, native host, and release zip:
# dist/ShortBot-Engine/
# dist/ShortBot-Engine-Windows.zip
```

---

## ⚙️ Configuration & AI Modes

ShortBot works out-of-the box in **Offline NLP Mode** with zero configuration required.

To enable advanced Gemini Cloud AI:
1. Open the ShortBot extension popup.
2. Open Settings and enter your **Google Gemini API Key**.
3. ShortBot will automatically leverage Gemini 2.5/1.5 Flash for deep semantic reasoning while keeping the offline engine as an instant fallback.

---

## 📄 License

MIT License. Built for creators and developers.
