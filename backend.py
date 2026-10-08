import sys
import os

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
    INTERNAL_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(INTERNAL_DIR, "ui")):
        UI_DIR = os.path.join(INTERNAL_DIR, "ui")
    elif os.path.isdir(os.path.join(EXE_DIR, "ui")):
        UI_DIR = os.path.join(EXE_DIR, "ui")
    else:
        UI_DIR = os.path.join(INTERNAL_DIR, "ui")
    DOWNLOAD_DIR = os.path.join(EXE_DIR, "downloads")
    LOG_FILE = os.path.join(EXE_DIR, "backend.log")
    BASE_DIR = INTERNAL_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UI_DIR = os.path.join(BASE_DIR, "ui")
    DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
    LOG_FILE = os.path.join(BASE_DIR, "backend.log")

# Ensure UTF-8 output handling on Windows or log to file if running headless/pythonw
try:
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    elif sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    elif sys.platform == "win32" and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, request, jsonify, send_from_directory, send_file
from agent import find_shorts, is_valid_url_for_platform
import subprocess
import uuid
import glob
import shutil
import threading
import time
import re
import urllib.request
import zipfile
import io
import yt_dlp

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Flask(__name__)


# ============================================================
# TASK PROGRESS TRACKER
# ============================================================

TASK_PROGRESS = {}
TASK_PROGRESS_LOCK = threading.Lock()

def update_task_progress(task_id, percent, stage, speed="", eta="", detail="", status="running"):
    if not task_id:
        return
    with TASK_PROGRESS_LOCK:
        now = time.time()
        # Clean tasks older than 30 minutes
        to_del = [tid for tid, data in TASK_PROGRESS.items() if now - data.get("updated_at", now) > 1800]
        for tid in to_del:
            del TASK_PROGRESS[tid]
            
        TASK_PROGRESS[task_id] = {
            "percent": float(percent),
            "stage": str(stage),
            "speed": str(speed),
            "eta": str(eta),
            "detail": str(detail),
            "status": str(status),
            "updated_at": now
        }

@app.route("/progress/<task_id>", methods=["GET"])
def get_task_progress_route(task_id):
    with TASK_PROGRESS_LOCK:
        prog = TASK_PROGRESS.get(task_id)
    if not prog:
        return jsonify({"success": False, "error": "Task not found"}), 404
    return jsonify({"success": True, "progress": prog})

def get_no_window_kwargs():
    """Returns subprocess kwargs that completely prevent console/CMD windows on Windows."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def get_video_duration(file_path):
    dur, _ = probe_media_info(file_path)
    return dur


def probe_media_info(file_path):
    """Probes media duration and checks if audio stream exists."""
    try:
        probe = get_ffprobe_path() or shutil.which("ffprobe") or "ffprobe"
        cmd = [
            probe,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "json",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **get_no_window_kwargs())
        import json
        info = json.loads(res.stdout) if res.stdout else {}
        dur = float(info.get("format", {}).get("duration", 0.0))
        streams = info.get("streams", [])
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        return max(0.1, dur), has_audio
    except Exception:
        return 0.0, False


# ============================================================
# FIREFOX / EXTENSION CORS & PREFLIGHT
# ============================================================

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return ("", 204)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Range, Authorization, X-Requested-With"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length, Content-Range, X-Filename"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, HEAD, PUT, DELETE"
    return response


# ============================================================
# FFMPEG & MEDIA ENGINE AUTO-PROVISIONING
# ============================================================

def find_ffmpeg_binary(name):
    # 1. If frozen executable, check EXE_DIR/bin and EXE_DIR
    if getattr(sys, "frozen", False):
        exe_real_dir = os.path.dirname(sys.executable)
        exe_dir = getattr(sys, "_MEIPASS", None)
        for d in (exe_real_dir, exe_dir):
            if d:
                p = os.path.join(d, "bin", f"{name}.exe")
                if os.path.isfile(p):
                    return p
                p = os.path.join(d, f"{name}.exe")
                if os.path.isfile(p):
                    return p

    # 2. Check local bin/
    p = os.path.join(BASE_DIR, "bin", f"{name}.exe")
    if os.path.isfile(p):
        return p
    # 3. Check local directory
    p = os.path.join(BASE_DIR, f"{name}.exe")
    if os.path.isfile(p):
        return p

    # 4. Check ShortBot installation directory in LocalAppData (%LOCALAPPDATA%\ShortBot\bin)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        p = os.path.join(local_app_data, "ShortBot", "bin", f"{name}.exe")
        if os.path.isfile(p):
            return p
        p = os.path.join(local_app_data, "ShortBot", f"{name}.exe")
        if os.path.isfile(p):
            return p

    # 5. Check user home .shortbot/bin
    user_home = os.path.expanduser("~")
    p = os.path.join(user_home, ".shortbot", "bin", f"{name}.exe")
    if os.path.isfile(p):
        return p

    # 6. Check system PATH
    found = shutil.which(name)
    if found:
        return found

    # 7. Check WinGet packages directory in LocalAppData
    if local_app_data:
        winget_pkgs = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_pkgs):
            for root, dirs, files in os.walk(winget_pkgs):
                for f in files:
                    if f.lower() == f"{name.lower()}.exe":
                        return os.path.join(root, f)

    # 8. Common installation locations
    for common_dir in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin", r"C:\Program Files (x86)\ffmpeg\bin"):
        p = os.path.join(common_dir, f"{name}.exe")
        if os.path.isfile(p):
            return p
    return None

FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
FFPROBE_PATH = find_ffmpeg_binary("ffprobe")

if FFMPEG_PATH:
    print()
    print("FFmpeg found:", FFMPEG_PATH)
    print("FFprobe found:", FFPROBE_PATH)
    print()

def get_ffmpeg_path():
    global FFMPEG_PATH
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        return FFMPEG_PATH
    FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
    return FFMPEG_PATH

def get_ffprobe_path():
    global FFPROBE_PATH
    if FFPROBE_PATH and os.path.isfile(FFPROBE_PATH):
        return FFPROBE_PATH
    FFPROBE_PATH = find_ffmpeg_binary("ffprobe")
    return FFPROBE_PATH

_ffmpeg_download_lock = threading.Lock()
_ffmpeg_download_thread = None
_ffmpeg_download_status = {
    "state": "idle",       # "idle", "downloading", "completed", "error"
    "percent": 0,
    "detail": "",
    "error": None
}

def get_target_bin_dir():
    candidates = []
    if getattr(sys, "frozen", False):
        exe_real_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_real_dir, "bin"))
    candidates.append(os.path.join(BASE_DIR, "bin"))
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "ShortBot", "bin"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".shortbot", "bin"))

    for c in candidates:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            test_file = os.path.join(c, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return c
        except Exception:
            continue
    return os.path.join(BASE_DIR, "bin")

def _download_and_extract_file(url, target_file, expected_name, on_progress=None):
    """Downloads a zip from url and extracts expected_name into target_file."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShortBot/1.1"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        chunks = []
        downloaded = 0
        while True:
            chunk = resp.read(131072)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if on_progress and total > 0:
                pct = min(99, int((downloaded / total) * 100))
                on_progress(pct)
        raw_data = b"".join(chunks)
        with zipfile.ZipFile(io.BytesIO(raw_data)) as z:
            for info in z.infolist():
                if os.path.basename(info.filename).lower() == expected_name.lower():
                    with z.open(info) as src, open(target_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    return True
    return False

def _do_download_ffmpeg():
    global FFMPEG_PATH, FFPROBE_PATH
    target_dir = get_target_bin_dir()
    os.makedirs(target_dir, exist_ok=True)
    target_ffmpeg = os.path.join(target_dir, "ffmpeg.exe")
    target_ffprobe = os.path.join(target_dir, "ffprobe.exe")

    _ffmpeg_download_status["state"] = "downloading"
    _ffmpeg_download_status["percent"] = 5
    _ffmpeg_download_status["detail"] = "Connecting to media engine repository..."

    print()
    print("=" * 60)
    print(f"[ShortBot] Auto-provisioning portable FFmpeg into: {target_dir}")
    print("=" * 60)

    # 1. Download ffmpeg.exe if missing
    if not (os.path.isfile(target_ffmpeg) and os.path.getsize(target_ffmpeg) > 1000000):
        try:
            _ffmpeg_download_status["detail"] = "Downloading portable FFmpeg (0%)..."
            def progress_ffmpeg(pct):
                _ffmpeg_download_status["percent"] = int(pct * 0.7)  # 0-70%
                _ffmpeg_download_status["detail"] = f"Downloading portable FFmpeg ({pct}%)..."

            url = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffmpeg-6.1-win-64.zip"
            success = _download_and_extract_file(url, target_ffmpeg, "ffmpeg.exe", progress_ffmpeg)
            if not success or not os.path.isfile(target_ffmpeg):
                raise RuntimeError("Failed to extract ffmpeg.exe from primary mirror.")
        except Exception as e:
            print("[ShortBot] Primary mirror failed for ffmpeg, trying Gyan essentials fallback...", e)
            try:
                url_gyan = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                _download_and_extract_file(url_gyan, target_ffmpeg, "ffmpeg.exe")
            except Exception as e2:
                print("[ShortBot] Gyan mirror also failed:", e2)

    # 2. Download ffprobe.exe if missing
    if not (os.path.isfile(target_ffprobe) and os.path.getsize(target_ffprobe) > 1000000):
        try:
            _ffmpeg_download_status["detail"] = "Downloading portable FFprobe (0%)..."
            def progress_ffprobe(pct):
                _ffmpeg_download_status["percent"] = 70 + int(pct * 0.28)  # 70-98%
                _ffmpeg_download_status["detail"] = f"Downloading portable FFprobe ({pct}%)..."

            url_probe = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffprobe-6.1-win-64.zip"
            _download_and_extract_file(url_probe, target_ffprobe, "ffprobe.exe", progress_ffprobe)
        except Exception as e:
            print("[ShortBot] ffprobe download warning:", e)

    # Re-evaluate
    FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
    FFPROBE_PATH = find_ffmpeg_binary("ffprobe")

    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        _ffmpeg_download_status["state"] = "completed"
        _ffmpeg_download_status["percent"] = 100
        _ffmpeg_download_status["detail"] = "FFmpeg ready!"
        print("[ShortBot] FFmpeg successfully installed and active:", FFMPEG_PATH)
        return True
    else:
        # Fallback to WinGet if available
        try:
            print("[ShortBot] Attempting winget fallback installation...")
            subprocess.run(
                ["winget", "install", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements", "--silent"],
                capture_output=True,
                timeout=120,
                **get_no_window_kwargs()
            )
            FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
            FFPROBE_PATH = find_ffmpeg_binary("ffprobe")
            if FFMPEG_PATH:
                _ffmpeg_download_status["state"] = "completed"
                _ffmpeg_download_status["percent"] = 100
                _ffmpeg_download_status["detail"] = "FFmpeg ready!"
                return True
        except Exception:
            pass

        _ffmpeg_download_status["state"] = "error"
        _ffmpeg_download_status["error"] = "Could not automatically download FFmpeg. Please check your internet connection."
        return False

def start_ffmpeg_download_in_background():
    global _ffmpeg_download_thread
    with _ffmpeg_download_lock:
        if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
            return
        if _ffmpeg_download_status.get("state") == "downloading":
            return
        _ffmpeg_download_status["state"] = "downloading"
        _ffmpeg_download_status["percent"] = 5
        _ffmpeg_download_thread = threading.Thread(target=_do_download_ffmpeg, daemon=True)
        _ffmpeg_download_thread.start()

def ensure_ffmpeg(task_id=None, timeout=90):
    global FFMPEG_PATH, FFPROBE_PATH
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        return FFMPEG_PATH

    FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
    FFPROBE_PATH = find_ffmpeg_binary("ffprobe")
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        return FFMPEG_PATH

    start_ffmpeg_download_in_background()

    start_time = time.time()
    while time.time() - start_time < timeout:
        if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
            return FFMPEG_PATH

        st = _ffmpeg_download_status.get("state")
        pct = _ffmpeg_download_status.get("percent", 0)
        detail = _ffmpeg_download_status.get("detail", "Downloading FFmpeg...")

        if st == "completed":
            FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
            FFPROBE_PATH = find_ffmpeg_binary("ffprobe")
            return FFMPEG_PATH
        if st == "error":
            break

        if task_id:
            # Map download 0-100% to progress bar 5-30%
            task_pct = min(30.0, 5.0 + (pct * 0.25))
            update_task_progress(
                task_id,
                round(task_pct, 1),
                "Setting up media processing engine...",
                detail=detail
            )

        time.sleep(0.5)

    FFMPEG_PATH = find_ffmpeg_binary("ffmpeg")
    return FFMPEG_PATH

_FAST_ENCODER_OPTS = None

def get_fast_h264_encoder():
    """Returns the fastest available H.264 video encoder options.
    Prefers NVIDIA NVENC hardware acceleration with fallback to ultrafast libx264."""
    global _FAST_ENCODER_OPTS
    if _FAST_ENCODER_OPTS is not None:
        return _FAST_ENCODER_OPTS

    ffmpeg = get_ffmpeg_path() or "ffmpeg"
    try:
        test_cmd = [
            ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", "color=c=black:s=256x256:d=0.1",
            "-c:v", "h264_nvenc",
            "-preset", "p1",
            "-f", "null",
            "-"
        ]
        res = subprocess.run(
            test_cmd,
            capture_output=True,
            timeout=5,
            **get_no_window_kwargs()
        )
        if res.returncode == 0:
            print()
            print("Hardware video acceleration enabled: NVIDIA NVENC (h264_nvenc)")
            print()
            _FAST_ENCODER_OPTS = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "24"]
            return _FAST_ENCODER_OPTS
    except Exception as e:
        print("NVENC probe failed, falling back to CPU encoder:", e)

    print()
    print("Using CPU video encoder: libx264 (ultrafast)")
    print()
    _FAST_ENCODER_OPTS = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-threads", "0"]
    return _FAST_ENCODER_OPTS



# ============================================================
# HEALTH CHECK & MEDIA ENGINE STATUS
# ============================================================

@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return ("", 204)
    from ai_engine import get_gemini_api_key
    gemini_key = get_gemini_api_key()
    ffmpeg_p = get_ffmpeg_path()
    dl_status = _ffmpeg_download_status
    state = "ready" if ffmpeg_p else dl_status.get("state", "missing")
    return jsonify({
        "success": True,
        "status": "online",
        "ffmpeg": bool(ffmpeg_p),
        "ffmpeg_status": state,
        "ffmpeg_progress": dl_status.get("percent", 0),
        "ffmpeg_path": ffmpeg_p or "",
        "ai_mode": "gemini_cloud" if gemini_key else "local_nlp",
        "has_gemini_key": bool(gemini_key)
    })


@app.route("/ffmpeg/install", methods=["GET", "POST", "OPTIONS"])
def install_ffmpeg_route():
    if request.method == "OPTIONS":
        return ("", 204)
    ffmpeg_p = get_ffmpeg_path()
    if ffmpeg_p:
        return jsonify({
            "success": True,
            "status": "ready",
            "ffmpeg": True,
            "path": ffmpeg_p
        })
    start_ffmpeg_download_in_background()
    return jsonify({
        "success": True,
        "status": _ffmpeg_download_status.get("state", "downloading"),
        "percent": _ffmpeg_download_status.get("percent", 0),
        "ffmpeg": False
    })


@app.route("/config/ai", methods=["GET", "POST", "OPTIONS"])
def config_ai():
    if request.method == "OPTIONS":
        return ("", 204)
    from ai_engine import get_gemini_api_key, load_config, save_config
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        key = data.get("gemini_api_key", "").strip()
        cfg = load_config()
        cfg["gemini_api_key"] = key
        save_config(cfg)
        return jsonify({"success": True, "has_gemini_key": bool(key), "ai_mode": "gemini_cloud" if key else "local_nlp"})
    key = get_gemini_api_key()
    return jsonify({"success": True, "has_gemini_key": bool(key), "ai_mode": "gemini_cloud" if key else "local_nlp"})



# ============================================================
# SEARCH
# ============================================================

@app.route("/search", methods=["POST", "OPTIONS"])
def search():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "error": "Invalid request."
        }), 400

    user_request = str(
        data.get("request", data.get("query", ""))
    ).strip()

    quantity = data.get("quantity")
    platform = str(data.get("platform", "youtube")).strip().lower() or "youtube"
    exclude_urls = data.get("exclude_urls", [])
    refresh = bool(data.get("refresh", False))

    if not isinstance(exclude_urls, list):
        exclude_urls = []

    if not user_request:
        return jsonify({
            "success": False,
            "error": "Please enter what videos you are looking for, or paste links to compile."
        }), 400

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Quantity must be a number."
        }), 400

    if quantity < 1:
        return jsonify({
            "success": False,
            "error": "Quantity must be greater than 0."
        }), 400

    try:
        results = find_shorts(
            user_request,
            quantity,
            platform=platform,
            exclude_urls=exclude_urls,
            refresh=refresh
        )

        filtered_results = [
            r for r in results
            if isinstance(r, dict) and is_valid_url_for_platform(r.get("url", ""), platform)
        ]
        for r in filtered_results:
            r["platform"] = platform

        return jsonify({
            "success": True,
            "platform": platform,
            "results": filtered_results
        })

    except Exception as e:
        print()
        print("=" * 60)
        print("SEARCH ERROR")
        print("=" * 60)
        print(e)
        print()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# CREATE WATERMARKED VIDEO
# ============================================================

def apply_watermark(
    input_file,
    output_file,
    watermark,
    task_id=None,
    base_percent=50.0,
    max_percent=95.0
):

    if not watermark:
        return False

    watermark_file = os.path.join(
        DOWNLOAD_DIR,
        f"watermark_{uuid.uuid4().hex[:8]}.txt"
    )

    try:

        with open(
            watermark_file,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(watermark)

        watermark_path = watermark_file.replace(
            "\\",
            "/"
        )

        if (
            len(watermark_path) >= 2
            and watermark_path[1] == ":"
        ):

            watermark_path = (
                watermark_path[0]
                + "\\:"
                + watermark_path[2:]
            )

        filter_complex = (
            "drawtext="
            "textfile='"
            + watermark_path
            + "':"
            "fontfile='C\\:/Windows/Fonts/arial.ttf':"
            "fontsize=48:"
            "fontcolor=white:"
            "box=1:"
            "boxcolor=black@0.55:"
            "boxborderw=12:"
            "x=w-tw-30:"
            "y=h-th-30"
        )

        encoder_args = get_fast_h264_encoder()
        ffmpeg_bin = get_ffmpeg_path() or "ffmpeg"
        command = [
            ffmpeg_bin,
            "-y",
            "-i",
            input_file,
            "-vf",
            filter_complex,
            *encoder_args,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            output_file
        ]

        print()
        print("Applying watermark:", watermark)
        print()

        total_duration = get_video_duration(input_file)

        update_task_progress(
            task_id,
            base_percent,
            f"Applying watermark '{watermark}'...",
            detail="Encoding frames with FFmpeg..."
        )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            **get_no_window_kwargs()
        )

        recent_lines = []
        for line in iter(process.stdout.readline, ''):
            recent_lines.append(line)
            if len(recent_lines) > 50:
                recent_lines.pop(0)
            if "out_time_us=" in line:
                match = re.search(r"out_time_us=(\d+)", line)
                if match and total_duration > 0:
                    current_sec = int(match.group(1)) / 1_000_000.0
                    fraction = min(1.0, current_sec / total_duration)
                    prog = base_percent + fraction * (max_percent - base_percent)
                    update_task_progress(
                        task_id,
                        round(prog, 1),
                        f"Applying watermark '{watermark}' ({prog:.0f}%)...",
                        detail=f"{current_sec:.1f}s / {total_duration:.1f}s processed"
                    )

        process.wait(timeout=600)

        if process.returncode != 0:
            stderr_out = "".join(recent_lines)
            raise RuntimeError(
                "FFmpeg could not apply the watermark.\n"
                + stderr_out[-3000:]
            )

        if not os.path.exists(output_file):

            raise RuntimeError(
                "Watermarked video was not created."
            )

        return True

    finally:

        if os.path.exists(watermark_file):

            try:
                os.remove(watermark_file)
            except OSError:
                pass


# ============================================================
# DOWNLOAD ONE SHORT
# ============================================================

@app.route("/download", methods=["POST"])
def download():

    data = request.get_json(silent=True)

    if not data:

        return jsonify({
            "success": False,
            "error": "Invalid request."
        }), 400

    video_url = str(
        data.get("url", "")
    ).strip()

    watermark = str(
        data.get("watermark", "")
    ).strip()

    # Firefox extension can ask the backend to keep the downloaded
    # MP4 in the server workspace without streaming it through the
    # popup. This makes user-selected Firefox download locations
    # reliable. Existing callers keep the original behavior.
    server_only = bool(data.get("server_only", False))
    task_id = str(data.get("task_id", "")).strip() or None
    direct_media_url = str(data.get("direct_media_url", "")).strip() or None

    if not video_url:

        return jsonify({
            "success": False,
            "error": "No video URL provided."
        }), 400

    if len(watermark) > 50:

        return jsonify({
            "success": False,
            "error": "Watermark is too long."
        }), 400

    update_task_progress(
        task_id,
        5.0,
        "Starting download...",
        detail="Connecting to stream..."
    )

    print()
    print("=" * 60)
    print("DOWNLOADING MEDIA")
    print("=" * 60)
    print("URL:", video_url)
    if direct_media_url:
        print("Direct Media URL:", direct_media_url[:90] + "...")

    if watermark:
        print("Watermark:", watermark)
    else:
        print("Watermark: NONE")

    print()

    # Ensure FFmpeg is available; auto-provision in background/on-demand if needed
    ffmpeg_bin = ensure_ffmpeg(task_id=task_id)
    if not ffmpeg_bin:
        if watermark:
            update_task_progress(
                task_id,
                0.0,
                "Failed",
                detail="FFmpeg offline (needed for watermark)",
                status="error"
            )
            return jsonify({
                "success": False,
                "error": "FFmpeg is offline or not installed. Please connect to the internet to complete automatic setup, or uncheck watermark."
            }), 500
        else:
            print("[ShortBot] FFmpeg not found, falling back to pre-merged stream download...")

    def get_url_file_id(v_url):
        m = re.search(r"(?:shorts/|v=|youtu\.be/)([a-zA-Z0-9_-]{11})", v_url)
        if m:
            return m.group(1)
        m_ig = re.search(r"instagram\.com/(?:reel|reels|p)/([a-zA-Z0-9_-]+)", v_url)
        if m_ig:
            return f"ig_{m_ig.group(1)}"
        m_x = re.search(r"(?:twitter|x)\.com/[^/]+/status/(\d+)", v_url)
        if m_x:
            return f"x_{m_x.group(1)}"
        m_red = re.search(r"reddit\.com/r/[^/]+/comments/([a-zA-Z0-9]+)", v_url)
        if m_red:
            return f"red_{m_red.group(1)}"
        import hashlib
        return hashlib.sha256(v_url.strip().encode("utf-8")).hexdigest()[:10]

    file_id = get_url_file_id(video_url)
    cached_file = os.path.join(DOWNLOAD_DIR, f"short_{file_id}.mp4")

    # Instant return if already downloaded and valid (when no watermark is needed)
    if os.path.isfile(cached_file) and os.path.getsize(cached_file) > 10000 and not watermark:
        update_task_progress(task_id, 100.0, "Ready from cache!", detail=f"short_{file_id}.mp4", status="completed")
        if server_only:
            return jsonify({
                "success": True,
                "filename": f"short_{file_id}.mp4"
            })
        resp = send_file(
            cached_file,
            as_attachment=True,
            download_name=f"short_{file_id}.mp4",
            mimetype="video/mp4"
        )
        resp.headers["X-Filename"] = f"short_{file_id}.mp4"
        return resp

    output_template = os.path.join(
        DOWNLOAD_DIR,
        f"short_{file_id}.%(ext)s"
    )

    node_path = shutil.which("node")
    cookies_file = os.path.join(BASE_DIR, "cookies.txt")
    cookies_param = cookies_file if os.path.isfile(cookies_file) else None

    is_youtube = ("youtube.com" in video_url.lower() or "youtu.be" in video_url.lower())
    if is_youtube:
        client_strategies = [
            "android,ios,web",
            "android,ios",
            "web,ios,android"
        ]
    else:
        client_strategies = ["default"]

    success = False
    last_error_details = ""
    scale = 0.70 if watermark else 0.90

    # 1. Attempt direct media stream download first if provided (bypasses login walls for active browser tabs)
    if direct_media_url and direct_media_url.startswith("http"):
        try:
            print(f"[ShortBot] Direct media stream detected: {direct_media_url[:80]}...")
            update_task_progress(task_id, 20.0, "Downloading media stream...", detail="Direct stream found")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Referer": video_url or "https://www.instagram.com/"
            }
            tmp_direct_file = os.path.join(DOWNLOAD_DIR, f"short_{file_id}.mp4")
            with requests.get(direct_media_url, headers=headers, stream=True, timeout=35) as r:
                r.raise_for_status()
                total_len = int(r.headers.get("content-length", 0))
                dl_bytes = 0
                with open(tmp_direct_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
                            dl_bytes += len(chunk)
                            if total_len > 0:
                                pct = min(85.0, 20.0 + (dl_bytes / total_len) * 65.0)
                                update_task_progress(
                                    task_id,
                                    round(pct, 1),
                                    f"Downloading stream ({int(dl_bytes * 100 / total_len)}%)...",
                                    detail=f"{dl_bytes // 1024} KB / {total_len // 1024} KB"
                                )
            if os.path.isfile(tmp_direct_file) and os.path.getsize(tmp_direct_file) > 1000:
                print(f"[ShortBot] Direct stream downloaded successfully ({dl_bytes} bytes)")
                success = True
        except Exception as direct_err:
            print(f"[ShortBot] Direct stream download failed ({direct_err}), falling back to yt-dlp...")
            success = False

    def ydl_progress_hook(d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            speed = d.get("speed")
            eta = d.get("eta")

            speed_str = ""
            if speed:
                if speed > 1024 * 1024:
                    speed_str = f"{speed / (1024 * 1024):.1f} MiB/s"
                else:
                    speed_str = f"{speed / 1024:.1f} KiB/s"

            eta_str = ""
            if eta is not None:
                mins, secs = divmod(int(eta), 60)
                eta_str = f"{mins:02d}:{secs:02d}"

            raw_pct = (downloaded / total * 100.0) if total > 0 else 0.0
            calc_pct = min(scale * 100.0, 5.0 + raw_pct * scale * 0.95)

            update_task_progress(
                task_id,
                round(calc_pct, 1),
                f"Downloading video ({raw_pct:.0f}%)...",
                speed=speed_str,
                eta=eta_str,
                detail=f"{speed_str} • ETA: {eta_str}" if speed_str else "Downloading stream..."
            )
        elif status == "finished":
            update_task_progress(
                task_id,
                88.0 if not watermark else 68.0,
                "Merging video & audio streams...",
                detail="Combining formats with FFmpeg..."
            )

    try:
        if not success:
            for strat_idx, client_strat in enumerate(client_strategies):
                if strat_idx > 0:
                    print(f"Retrying download with strategy {strat_idx + 1} ({client_strat})...")
                    update_task_progress(
                        task_id,
                        10.0,
                        "Retrying download...",
                        detail=f"Bypassing verification with {client_strat}..."
                    )

                print(f"Running yt-dlp in-process (strategy: {client_strat})...")

                if ffmpeg_bin:
                    format_spec = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bestvideo*+bestaudio/best"
                    merge_fmt = "mp4"
                else:
                    format_spec = "b[ext=mp4]/b/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
                    merge_fmt = None

                ydl_opts = {
                    "outtmpl": output_template,
                    "format": format_spec,
                    "noplaylist": True,
                    "progress_hooks": [ydl_progress_hook],
                    "quiet": True,
                    "no_warnings": True,
                }
                if is_youtube:
                    ydl_opts["extractor_args"] = {
                        "youtube": {
                            "player_client": client_strat.split(",")
                        }
                    }
                elif "instagram.com" in video_url.lower():
                    ydl_opts["http_headers"] = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        "Referer": "https://www.instagram.com/"
                    }
                if merge_fmt:
                    ydl_opts["merge_output_format"] = merge_fmt
                if ffmpeg_bin:
                    ydl_opts["ffmpeg_location"] = ffmpeg_bin
                if cookies_param:
                    ydl_opts["cookiefile"] = cookies_param
                if node_path:
                    ydl_opts["js_runtimes"] = {"node": {"path": node_path}}

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([video_url])
                    success = True
                    break
                except Exception as e:
                    last_error_details = str(e)
                    print(f"yt-dlp error: {e}")
                    is_bot_error = any(
                        phrase in last_error_details
                        for phrase in [
                            "Sign in to confirm you’re not a bot",
                            "Sign in to confirm you're not a bot",
                            "HTTP Error 429",
                            "429: Too Many Requests",
                            "Missing required Visitor Data",
                            "GVS PO Token"
                        ]
                    )
                    if not is_bot_error or not is_youtube:
                        break

        if not success:
            update_task_progress(task_id, 0.0, "Download failed", detail=last_error_details[:200], status="error")
            return jsonify({
                "success": False,
                "error": "Download failed.",
                "details": last_error_details
            }), 500

        original_file = os.path.join(
            DOWNLOAD_DIR,
            f"short_{file_id}.mp4"
        )

        print()
        print("Looking for final MP4:")
        print(original_file)
        print()

        if not os.path.exists(original_file):

            possible_files = glob.glob(
                os.path.join(
                    DOWNLOAD_DIR,
                    f"short_{file_id}.*"
                )
            )

            print("Files produced:")

            for file in possible_files:
                print(file)

            update_task_progress(task_id, 0.0, "File not found", detail="Final MP4 was not produced", status="error")
            return jsonify({
                "success": False,
                "error": "Download completed, but the final MP4 was not found.",
                "files": possible_files
            }), 500

        # ----------------------------------------------------
        # NO WATERMARK
        # ----------------------------------------------------

        if not watermark:

            final_file = original_file

        # ----------------------------------------------------
        # WATERMARK ENABLED
        # ----------------------------------------------------

        else:

            watermarked_file = os.path.join(
                DOWNLOAD_DIR,
                f"short_{file_id}_watermarked.mp4"
            )

            apply_watermark(
                original_file,
                watermarked_file,
                watermark,
                task_id=task_id,
                base_percent=70.0,
                max_percent=98.0
            )

            # Replace the original downloaded file with
            # the watermarked version so the file tracked
            # by the frontend is the final version.

            os.remove(original_file)

            os.replace(
                watermarked_file,
                original_file
            )

            final_file = original_file

        update_task_progress(
            task_id,
            100.0,
            "Download complete!",
            detail=f"short_{file_id}.mp4",
            status="completed"
        )

        print()
        print("=" * 60)
        print("DOWNLOAD SUCCESSFUL")
        print("=" * 60)
        print()

        print("Final MP4:")
        print(final_file)
        print()

        if server_only:
            return jsonify({
                "success": True,
                "filename": f"short_{file_id}.mp4"
            })

        response = send_file(
            final_file,
            as_attachment=True,
            download_name=f"short_{file_id}.mp4",
            mimetype="video/mp4"
        )
        response.headers["X-Filename"] = f"short_{file_id}.mp4"
        return response

    except subprocess.TimeoutExpired:

        return jsonify({
            "success": False,
            "error": "Download timed out."
        }), 500

    except Exception as e:

        print()
        print("=" * 60)
        print("DOWNLOAD ERROR")
        print("=" * 60)
        print(e)
        print()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# SERVE A SERVER-WORKSPACE MP4 TO FIREFOX
# ============================================================

@app.route("/file/<path:filename>", methods=["GET"])
def serve_shortbot_file(filename):

    safe_name = os.path.basename(filename)

    if safe_name != filename:
        return jsonify({
            "success": False,
            "error": "Invalid filename."
        }), 400

    if not safe_name.lower().endswith(".mp4"):
        return jsonify({
            "success": False,
            "error": "Only MP4 files are allowed."
        }), 400

    if not (
        safe_name.lower().startswith("short_")
        or safe_name.lower().startswith("compilation_")
    ):
        return jsonify({
            "success": False,
            "error": "Invalid ShortBot file."
        }), 400

    full_path = os.path.join(
        DOWNLOAD_DIR,
        safe_name
    )

    if not os.path.isfile(full_path):
        return jsonify({
            "success": False,
            "error": "File not found."
        }), 404

    download_name = (
        "shortbot_compilation.mp4"
        if safe_name.lower().startswith("compilation_")
        else safe_name
    )

    return send_file(
        full_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="video/mp4"
    )


# ============================================================
# LIST DOWNLOADED SHORTS
# ============================================================

@app.route("/downloads", methods=["GET"])
def list_downloads():

    files = []

    try:

        for filename in os.listdir(
            DOWNLOAD_DIR
        ):

            if not filename.lower().endswith(".mp4"):
                continue

            if not filename.lower().startswith("short_"):
                continue

            files.append(filename)

        files.sort()

        return jsonify({
            "success": True,
            "files": files
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# NATIVE WINDOWS SAVE AS DIALOG & FILE EXPLORER
# ============================================================

@app.route("/save-dialog", methods=["POST", "OPTIONS"])
def save_file_dialog():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}
    source_filename = data.get("filename")
    suggested_name = data.get("suggested_name", "shortbot_compilation.mp4")

    if not source_filename:
        return jsonify({"success": False, "error": "No filename provided."}), 400

    source_path = os.path.join(DOWNLOAD_DIR, os.path.basename(source_filename))
    if not os.path.isfile(source_path):
        return jsonify({"success": False, "error": f"File {source_filename} not found on server."}), 404

    if sys.platform != "win32":
        return jsonify({
            "success": False,
            "error": "Native OS dialog only available on Windows.",
            "fallback_browser": True
        })

    try:
        import base64

        clean_suggested = re.sub(r'[\r\n\'"]', "", suggested_name) or "shortbot_compilation.mp4"
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$dlg = New-Object System.Windows.Forms.SaveFileDialog
$dlg.Title = "ShortBot - Save Compilation As"
$dlg.Filter = "MP4 Video (*.mp4)|*.mp4|All Files (*.*)|*.*"
$dlg.FileName = "{clean_suggested}"
$dlg.RestoreDirectory = $true
$res = $dlg.ShowDialog($form)
if ($res -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output "SAVED:$($dlg.FileName)"
}} else {{
    Write-Output "CANCELLED"
}}
"""
        encoded = base64.b64encode(ps_script.strip().encode("utf-16le")).decode("ascii")
        proc = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=180,
            **get_no_window_kwargs()
        )

        stdout = proc.stdout.strip()
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        saved_line = next((l for l in lines if l.startswith("SAVED:")), None)
        cancelled = any("CANCELLED" in l for l in lines)

        if saved_line:
            target_path = saved_line[len("SAVED:"):].strip()
            target_dir = os.path.dirname(target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(source_path, target_path)
            print(f"[ShortBot] Saved compilation to: {target_path}")
            return jsonify({
                "success": True,
                "saved_path": target_path,
                "filename": os.path.basename(target_path)
            })
        elif cancelled:
            return jsonify({
                "success": False,
                "cancelled": True,
                "message": "Save dialog cancelled by user."
            })
        else:
            return jsonify({
                "success": False,
                "error": "Dialog did not return a valid file path.",
                "details": proc.stderr.strip() or stdout,
                "fallback_browser": True
            })

    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Save dialog timed out."}), 504
    except Exception as e:
        print(f"[ShortBot] save_file_dialog error: {e}")
        return jsonify({"success": False, "error": str(e), "fallback_browser": True}), 500


@app.route("/open-folder", methods=["POST", "OPTIONS"])
def open_folder():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}
    path = data.get("path")
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": "Path does not exist."}), 404

    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(path)}"], **get_no_window_kwargs())
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# COMPILE SELECTED SHORTS
# ============================================================

@app.route("/compile", methods=["POST"])
def compile_shorts():

    print()
    print("=" * 60)
    print("COMPILING SHORTS")
    print("=" * 60)
    print()

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({
            "success": False,
            "error": "Invalid request."
        }), 400

    task_id = str(data.get("task_id", "")).strip() or None
    ffmpeg_bin = ensure_ffmpeg(task_id=task_id)
    if not ffmpeg_bin:
        update_task_progress(task_id, 0.0, "Compilation failed", detail="FFmpeg offline or not installed", status="error")
        return jsonify({
            "success": False,
            "error": "FFmpeg is offline or not installed. Please connect to the internet to complete automatic setup, or install FFmpeg."
        }), 500

    files = data.get(
        "files",
        []
    )

    watermark = str(
        data.get(
            "watermark",
            ""
        )
    ).strip()

    # Firefox extension uses JSON metadata, then asks Firefox itself
    # to download the finished MP4. This avoids popup/blob download
    # failures and gives Firefox full control of the save location.
    return_json = bool(data.get("return_json", False))

    if not isinstance(
        files,
        list
    ):

        return jsonify({
            "success": False,
            "error": "Files must be a list."
        }), 400

    if len(watermark) > 50:

        return jsonify({
            "success": False,
            "error": "Watermark is too long."
        }), 400

    valid_files = []

    for filename in files:

        filename = str(
            filename
        ).strip()

        if not filename:
            continue

        safe_name = os.path.basename(
            filename
        )

        if safe_name != filename:
            continue

        if not safe_name.lower().endswith(
            ".mp4"
        ):
            continue

        if not safe_name.lower().startswith(
            "short_"
        ):
            continue

        full_path = os.path.join(
            DOWNLOAD_DIR,
            safe_name
        )

        if os.path.isfile(
            full_path
        ):

            valid_files.append(
                full_path
            )

    task_id = str(data.get("task_id", "")).strip() or None

    if len(valid_files) < 2:

        return jsonify({
            "success": False,
            "error": "Download at least 2 Shorts before compiling."
        }), 400

    total_duration = sum(get_video_duration(f) for f in valid_files)

    update_task_progress(
        task_id,
        10.0,
        f"Preparing {len(valid_files)} video clips...",
        detail="Creating concatenation manifest..."
    )

    # Probe each input clip
    durations = []
    has_audios = []
    for f in valid_files:
        dur, has_audio = probe_media_info(f)
        durations.append(dur)
        has_audios.append(has_audio)

    total_duration = sum(durations)

    update_task_progress(
        task_id,
        12.0,
        f"Preparing {len(valid_files)} video clips...",
        detail="Normalizing and building compilation pipeline..."
    )

    print("Files to compile:")
    for file in valid_files:
        print(file)
    print()

    if watermark:
        print("Watermark:", watermark)
    else:
        print("Watermark: NONE")
    print()

    compile_id = uuid.uuid4().hex[:8]

    watermark_file = os.path.join(
        DOWNLOAD_DIR,
        f"watermark_{compile_id}.txt"
    )

    output_file = os.path.join(
        DOWNLOAD_DIR,
        f"compilation_{compile_id}.mp4"
    )

    try:
        # Build multi-input normalization & concatenation filter
        input_args = []
        filter_parts = []
        for i, f in enumerate(valid_files):
            input_args.extend(["-i", f])
            # Normalize video to 1080x1920 (9:16 vertical), 30 fps
            filter_parts.append(
                f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
            )
            # Normalize audio to 48000Hz stereo AAC (synthesize silence if clip has no audio)
            if has_audios[i]:
                filter_parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
            else:
                filter_parts.append(f"aevalsrc=0:d={durations[i]}:s=48000:c=stereo[a{i}]")

        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(valid_files)))
        filter_parts.append(f"{concat_inputs}concat=n={len(valid_files)}:v=1:a=1[vconcat][aout]")

        out_v = "[vconcat]"
        if watermark:
            with open(watermark_file, "w", encoding="utf-8") as f:
                f.write(watermark)

            wm_path = watermark_file.replace("\\", "/")
            if len(wm_path) >= 2 and wm_path[1] == ":":
                wm_path = wm_path[0] + "\\:" + wm_path[2:]

            font_clause = "fontfile='C\\:/Windows/Fonts/arial.ttf':" if os.path.isfile(r"C:\Windows\Fonts\arial.ttf") else "font='Arial':"

            drawtext = (
                f"drawtext=textfile='{wm_path}':"
                f"{font_clause}"
                "fontsize=48:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=12:"
                "x=w-tw-30:y=h-th-30"
            )
            filter_parts.append(f"[vconcat]{drawtext}[vout]")
            out_v = "[vout]"

        full_filter = ";".join(filter_parts)
        encoder_args = get_fast_h264_encoder()

        command = [
            ffmpeg_bin,
            "-y",
            *input_args,
            "-filter_complex", full_filter,
            "-map", out_v,
            "-map", "[aout]",
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            output_file
        ]

        wm_label = f" with watermark '{watermark}'" if watermark else ""
        update_task_progress(
            task_id,
            18.0,
            f"Compiling {len(valid_files)} Shorts{wm_label}...",
            detail="Encoding normalized compilation..."
        )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            **get_no_window_kwargs()
        )

        recent_lines = []
        for line in iter(process.stdout.readline, ''):
            recent_lines.append(line)
            if len(recent_lines) > 50:
                recent_lines.pop(0)
            if "out_time_us=" in line:
                match = re.search(r"out_time_us=(\d+)", line)
                if match and total_duration > 0:
                    current_sec = int(match.group(1)) / 1_000_000.0
                    fraction = min(1.0, current_sec / total_duration)
                    prog = 18.0 + fraction * 78.0
                    update_task_progress(
                        task_id,
                        round(prog, 1),
                        f"Compiling Shorts{wm_label} ({prog:.0f}%)...",
                        detail=f"{current_sec:.1f}s / {total_duration:.1f}s processed"
                    )

        process.wait(timeout=1200)

        if process.returncode != 0:
            stderr_out = "".join(recent_lines)
            update_task_progress(task_id, 0.0, "Compilation failed", detail=stderr_out[:200], status="error")
            return jsonify({
                "success": False,
                "error": "FFmpeg could not compile the Shorts.",
                "details": stderr_out[-3000:]
            }), 500

        update_task_progress(
            task_id,
            100.0,
            "Compilation complete!",
            detail=f"compilation_{compile_id}.mp4",
            status="completed"
        )

        if not os.path.exists(output_file):
            return jsonify({
                "success": False,
                "error": "Compilation finished, but the output MP4 was not found."
            }), 500

        print()
        print("=" * 60)
        if watermark:
            print("COMPILATION + WATERMARK SUCCESSFUL")
        else:
            print("COMPILATION SUCCESSFUL")
        print("=" * 60)
        print()
        print("Final compilation:")
        print(output_file)
        print()

        # Clean up individual source shorts that were merged into the compilation
        deleted_files = []
        for src_path in valid_files:
            try:
                if os.path.isfile(src_path):
                    os.remove(src_path)
                    deleted_files.append(os.path.basename(src_path))
                    print(f"Deleted source short after compilation: {src_path}")
                # Also delete any temporary watermarked variant of this clip
                wm_variant = src_path.replace(".mp4", "_watermarked.mp4")
                if os.path.isfile(wm_variant):
                    os.remove(wm_variant)
            except Exception as del_err:
                print(f"Warning: could not delete {src_path}: {del_err}")

        if return_json:
            return jsonify({
                "success": True,
                "filename": f"compilation_{compile_id}.mp4",
                "download_url": f"/file/compilation_{compile_id}.mp4",
                "deleted_files": deleted_files
            })

        return send_file(
            output_file,
            as_attachment=True,
            download_name="shortbot_compilation.mp4",
            mimetype="video/mp4"
        )

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Compilation timed out."
        }), 500

    except Exception as e:
        print()
        print("=" * 60)
        print("COMPILATION ERROR")
        print("=" * 60)
        print(e)
        print()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:
        if os.path.exists(watermark_file):
            try:
                os.remove(watermark_file)
            except OSError:
                pass


# ============================================================
# WEBSITE
# ============================================================

@app.route("/")
def index():

    return send_from_directory(
        UI_DIR,
        "index.html"
    )


@app.route("/<path:path>")
def static_files(path):

    return send_from_directory(
        UI_DIR,
        path
    )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("SHORTBOT")
    print("=" * 60)
    print()

    print("Website:")
    print(
        "http://127.0.0.1:5000"
    )

    print()

    print("Downloads:")
    print(
        DOWNLOAD_DIR
    )

    print()

    print("Press CTRL+C to stop.")
    print()

    if not get_ffmpeg_path():
        print("[ShortBot] FFmpeg not found on startup. Initiating automatic background provisioning...")
        start_ffmpeg_download_in_background()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )