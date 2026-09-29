# ShortBot

> AI-Powered YouTube Shorts Curator, Downloader, and Video Compiler.  
> Built as a modern Firefox WebExtension backed by a zero-dependency Windows Desktop Companion Engine.

---

## Features

- **Dual AI Curation Engine**:
  - **Cloud Mode**: Direct integration with Google Gemini Flash API for high-level semantic filtering and reasoning.
  - **Offline NLP Engine**: Built-in, zero-dependency tokenization, semantic scoring, and relevance classification that works 100% offline.
  - **No Ollama Required**: Runs on any PC without local LLM downloads or GPU requirements.
- **Fast In-Process Downloads**:
  - Embedded stream resolver with real-time percentage, speed, and ETA hooks.
  - Automatic multi-client fallback strategies (android, ios, web) to bypass rate limits and bot challenges.
- **Custom Watermarking and Branding**:
  - Dynamically brand downloaded shorts with customizable text and styling using bundled FFmpeg.
- **Direct Video URL Downloader**:
  - Paste any YouTube video or Shorts URL to download immediately with one click.
- **One-Click Compilation**:
  - Merge multiple curated shorts into a single video with normalized aspect ratios, frame rates, and audio streams.
- **Native Firefox and Chromium Support**:
  - Manifest V3 WebExtension supporting Mozilla Firefox (Promises/browser.runtime) and Chromium (chrome.runtime).
  - Native Messaging Host bridges browser extension requests directly to the companion engine with silent auto-launch.
- **Dark Mode UI**:
  - Sleek dark theme styled in Century Gothic typography.

---


---

## Repository Structure

```
ShortBot/
├── ui/                              # Firefox & WebExtension MV3 Source
│   ├── app.js                       # Extension logic and native messaging bridge
│   ├── index.html                   # Dark Mode UI
│   ├── style.css                    # Century Gothic styling
│   ├── manifest.json                # WebExtension manifest (v1.1.0)
│   └── icons/                       # Extension icons
├── docs/                            # Documentation and benchmarks
│   └── TIMINGS_AND_BENCHMARKS.md    # Performance benchmarks
├── backend.py                       # Local Flask engine & stream processing
├── agent.py                         # Curation orchestration pipeline
├── ai_engine.py                     # Gemini Flash API & local NLP classifier
├── classifier.py                    # Multi-factor relevance scoring
├── request_parser.py                # Query intent parser
├── native_host.py                   # Native messaging stdio protocol bridge
├── build_companion_engine.py        # PyInstaller companion packaging script
├── package_firefox_extension.py     # Firefox XPI and ZIP packager
├── register_native_host.bat         # Native host registration utility
├── installer.iss                    # Inno Setup compiler configuration
└── requirements.txt                 # Python developer dependencies
```

---

## Quick Start (For Users)

### 1. Run the Desktop Companion Engine
1. Extract `ShortBot-Engine-Windows.zip` or open the `ShortBot-Engine` folder.
2. Double-click `Install-ShortBot.bat`.
   - This automatically registers the native host for Firefox, Edge, and Chrome, and starts the companion engine silently.

### 2. Load the Firefox Extension
1. Open Mozilla Firefox and go to `about:debugging#/runtime/this-firefox`.
2. Click "Load Temporary Add-on...".
3. Select `shortbot-firefox.xpi` (or `ui/manifest.json`).
4. Click the ShortBot icon in your toolbar and start curating Shorts.

---

### Step-by-Step Instructions:

1. **Send the two files to your friend**:
   - `ShortBot-Engine-Windows.zip` (the standalone engine)
   - `shortbot-firefox.xpi` (the Firefox extension)

2. **On your friend's PC**:
   - **Step A: Extract Engine**
     - Right-click `ShortBot-Engine-Windows.zip` and select **Extract All**.
     - Open the extracted folder and double-click `Install-ShortBot.bat`.
     - A terminal window will open, register the native host in their Windows registry for Firefox/Chrome/Edge, start the engine silently in the background, and close automatically.
   - **Step B: Load Extension in Firefox**
     - Open Firefox and navigate to: `about:debugging#/runtime/this-firefox`.
     - Click **Load Temporary Add-on...**.
     - Select the `shortbot-firefox.xpi` file.
   - **Step C: Test Download & Curation**
     - Click the ShortBot icon in the Firefox toolbar.
     - The status badge in the top right will show **Backend Online** with a green dot.
     - Paste any YouTube Shorts URL into the "Download by URL" box and click Download, or type a topic in "What Shorts are you looking for?" and click "Find Shorts".
     - The video will download and save directly to their standard Downloads folder.

---

## Developer Guide

### Prerequisites
- Python 3.10+
- FFmpeg (optional in dev, auto-bundled in production build)

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

## Configuration & AI Modes

ShortBot works out-of-the-box in **Offline NLP Mode** with zero configuration required.

To enable advanced Gemini Cloud AI:
1. Open the ShortBot extension popup.
2. Open Settings and enter your Google Gemini API Key.
3. ShortBot will automatically leverage Gemini 2.5/1.5 Flash for deep semantic reasoning while keeping the offline engine as an instant fallback.
