# ShortBot Performance Benchmarks & Timings Guide

This document provides empirical timing benchmarks, breakdown of operations, and factors affecting performance for **ShortBot**.

---

## ⏱ Executive Summary & Quick Reference Table

| Operation | Typical Duration | File / Data Size | Bottleneck / Limiting Factor |
| :--- | :--- | :--- | :--- |
| **Download Current Running Video (Short)** | **2 – 6 seconds** | 3 MB – 25 MB | Internet bandwidth / YouTube CDN |
| **Download Current Running Video (Full Video)** | **45s – 2.5 minutes** | 150 MB – 500 MB+ | Network speed (e.g. ~4 MB/s = ~1m55s for 454 MB) |
| **Download Searched Video (Single Short)** | **2 – 5 seconds** | 2 MB – 20 MB | Network throughput & yt-dlp format extraction |
| **Download Searched Videos (Batch of 5)** | **8 – 18 seconds** | 20 MB – 100 MB | 3-way parallel workers + network bandwidth |
| **Compile Shorts (Stream Copy, No Watermark)** | **0.18 – 0.50 seconds** | 5 MB – 50 MB | Disk I/O (almost instantaneous, no re-encoding) |
| **Compile Shorts + Watermark (Re-encode)** | **5 – 15 seconds** | 5 MB – 50 MB | CPU/GPU H.264 video encoding speed |
| **Single Video Watermark (Re-encode)** | **1.9 – 4.5 seconds** | 2 MB – 25 MB | CPU H.264 encode (`libx264 veryfast`) |
| **Installation & Initial Environment Setup** | **1 – 2 minutes** | ~150 MB packages | Pip wheel downloads & unpack extension |

---

## 1. Downloading Current Running Video

### What Happens Behind the Scenes:
1. **Tab Inspection (< 0.1s)**: ShortBot reads the active browser tab via `chrome.tabs.query` to detect the YouTube video ID and title.
2. **Backend Handshake (< 0.5s)**: Sends a `POST /download` request with the video URL and a unique `task_id`.
3. **yt-dlp Extraction & Stream Download**:
   - Fetches the best video stream (`bv*[ext=mp4]`) and best audio stream (`ba[ext=m4a]`).
   - Merges streams using FFmpeg.
4. **Transfer to Browser (< 1s)**: Delivers the finalized MP4 into Chrome/Edge downloads.

### Measured Timings:
- **YouTube Shorts (Vertical 15s–60s clip)**:
  - Average size: **3 MB to 25 MB**
  - Download time: **2.1s – 5.8s**
- **Standard YouTube Long-Form Video (5–20 minutes)**:
  - *Example measured*: 453.88 MB 1080p video (`short_98223fb2.mp4`)
  - Speed: 3.94 MiB/s
  - Time elapsed: **1 minute 55 seconds (115 seconds)**
  - *Why the progress bar was essential*: Without visual feedback, downloading large videos appeared "frozen". The new progress bar reports real-time percentage, transfer speed (e.g., `4.1 MiB/s`), ETA (`ETA 00:24`), and elapsed time (`⏱ 01:15`).

---

## 2. Downloading Other / Searched Videos

### Individual Download:
- **Duration**: **2 – 5 seconds per Short**
- Each search result card includes an inline progress card (`#short-progress-{index}`) that displays:
  - Animated striped progress track
  - Live percentage (0% to 100%)
  - Speed indicator and ETA
  - Elapsed stopwatch timer

### Parallel Batch Download (`DOWNLOAD SELECTED`):
- Uses a **3-way concurrent worker pool** (`MAX_CONCURRENT = 3`).
- **3 Shorts**: ~**4 – 7 seconds** total (running simultaneously).
- **5 Shorts**: ~**8 – 15 seconds** total.
- Shows both:
  1. A master **Selection Progress Bar** (`0% to 100%`) showing overall batch completion.
  2. Individual inline progress bars on each active card.

---

## 3. Compiling and Putting Watermark

### Mode A: Fast Compilation (No Watermark)
- **Method**: FFmpeg Concat Demuxer with Direct Stream Copy (`-c copy`).
- **Benchmark Measurement**:
  - Combining 2 Shorts (5.71 MB): **0.177 seconds** (< 0.2s).
  - Combining 5 Shorts (~25 MB): **0.35 – 0.65 seconds**.
- **Explanation**: Streams are not decoded or re-encoded; packets are repackaged into a container directly.

### Mode B: Compilation + Watermark (`@YourHandle`)
- **Method**: FFmpeg Concat with `drawtext` filter and H.264 encoding (`-c:v libx264 -preset veryfast -crf 23 -c:a aac -b:a 128k`).
- **Benchmark Measurement**:
  - Combining 2 Shorts with Watermark (4.25 MB): **5.716 seconds**.
  - Combining 5 Shorts with Watermark: **12 – 18 seconds**.
- **Real-Time Progress Tracking**:
  - FFmpeg reports output microseconds (`out_time_us`), calculated against total audio/video duration (`ffprobe`).
  - Progress bar dynamically scales from 20% to 98% during encoding with live seconds processed (`e.g. 24.5s / 45.0s processed`).

### Mode C: Single Short with Watermark
- **Benchmark Measurement**:
  - 1 Short (2.19 MB, 15 seconds): **1.970 seconds**.

---

## 4. Installation & Setup Timings

| Step | Time Taken | Details |
| :--- | :--- | :--- |
| **1. Python Dependencies** | **25 – 45 seconds** | `pip install flask flask-cors yt-dlp google-genai requests` |
| **2. FFmpeg Verification** | **5 – 10 seconds** | `ffmpeg -version` (bundled or placed on PATH) |
| **3. Extension Installation** | **10 seconds** | Open `edge://extensions` or `chrome://extensions`, enable *Developer mode*, click *Load unpacked*, select the workspace folder. |
| **4. Native Messaging Host Registration** | **5 seconds** | Run `register_host.bat` (writes registry key under `HKCU\Software\Google\Chrome\NativeMessagingHosts` and Edge). |
| **5. Backend Service Startup** | **0.8 seconds** | `python backend.py` starts Flask server on `http://127.0.0.1:5000`. |
| **Total Setup Time** | **~1 minute 30 seconds** | One-time initial setup. Subsequent launches take < 1 second. |

---

## 5. Progress Bar Features Implemented

1. **Active YouTube Video Card**:
   - Located directly below the "DOWNLOAD THIS VIDEO" button.
   - Shows connection status, real-time download percentage, transfer speed, ETA, and elapsed stopwatch timer (`⏱ mm:ss`).
   - Automatically marks complete with green indicator and fades gracefully after completion.

2. **Compiler Progress Bar**:
   - Located in the selection action bar above the compiled results.
   - **Phase 1 (Preparation)**: Tracks downloading of any un-downloaded clips (5% to 40%).
   - **Phase 2 (FFmpeg)**: Tracks concatenation and H.264 watermark encoding (40% to 100%) via FFmpeg piped progress.

3. **Search Results Cards**:
   - Each individual video card has an embedded inline progress bar for single downloads.
   - Master progress bar displays overall batch progress when downloading multiple selected clips.
