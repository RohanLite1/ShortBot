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
from agent import find_shorts
import subprocess
import uuid
import glob
import shutil
import threading
import time
import re
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

def get_video_duration(file_path):
    dur, _ = probe_media_info(file_path)
    return dur


def probe_media_info(file_path):
    """Probes media duration and checks if audio stream exists."""
    try:
        probe = FFPROBE_PATH or shutil.which("ffprobe") or "ffprobe"
        cmd = [
            probe,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "json",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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



def find_ffmpeg_binary(name):
    # 1. Check local bin/
    p = os.path.join(BASE_DIR, "bin", f"{name}.exe")
    if os.path.isfile(p):
        return p
    # 2. Check local directory
    p = os.path.join(BASE_DIR, f"{name}.exe")
    if os.path.isfile(p):
        return p
    # 3. Check system PATH
    found = shutil.which(name)
    if found:
        return found
    # 4. Check WinGet packages directory in LocalAppData
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pkgs = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_pkgs):
            for root, dirs, files in os.walk(winget_pkgs):
                for f in files:
                    if f.lower() == f"{name.lower()}.exe":
                        return os.path.join(root, f)
    # 5. Common installation locations
    for common_dir in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
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

_FAST_ENCODER_OPTS = None

def get_fast_h264_encoder():
    """Returns the fastest available H.264 video encoder options.
    Prefers NVIDIA NVENC hardware acceleration with fallback to ultrafast libx264."""
    global _FAST_ENCODER_OPTS
    if _FAST_ENCODER_OPTS is not None:
        return _FAST_ENCODER_OPTS

    ffmpeg = FFMPEG_PATH or "ffmpeg"
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
            timeout=5
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
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return ("", 204)
    from ai_engine import get_gemini_api_key
    gemini_key = get_gemini_api_key()
    return jsonify({
        "success": True,
        "status": "online",
        "ffmpeg": bool(FFMPEG_PATH),
        "ai_mode": "gemini_cloud" if gemini_key else "local_nlp",
        "has_gemini_key": bool(gemini_key)
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

    if not user_request:
        return jsonify({
            "success": False,
            "error": "Please enter what Shorts you are looking for."
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
            quantity
        )

        return jsonify({
            "success": True,
            "results": results
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
        command = [
            FFMPEG_PATH,
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
            universal_newlines=True
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
        detail="Connecting to YouTube..."
    )

    print()
    print("=" * 60)
    print("DOWNLOADING SHORT")
    print("=" * 60)
    print("URL:", video_url)

    if watermark:
        print("Watermark:", watermark)
    else:
        print("Watermark: NONE")

    print()

    if not FFMPEG_PATH:

        update_task_progress(task_id, 0.0, "Failed", detail="FFmpeg not found", status="error")
        return jsonify({
            "success": False,
            "error": "FFmpeg was not found."
        }), 500

    def get_url_file_id(v_url):
        m = re.search(r"(?:shorts/|v=|youtu\.be/)([a-zA-Z0-9_-]{11})", v_url)
        if m:
            return m.group(1)
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

    # Client strategies to bypass YouTube 429 and bot verification challenges
    client_strategies = [
        "android,ios,web",
        "android,ios",
        "web,ios,android"
    ]

    success = False
    last_error_details = ""
    scale = 0.70 if watermark else 0.90

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
        for strat_idx, client_strat in enumerate(client_strategies):
            if strat_idx > 0:
                print(f"Retrying download with strategy {strat_idx + 1} ({client_strat})...")
                update_task_progress(
                    task_id,
                    10.0,
                    "Retrying download...",
                    detail=f"Bypassing YouTube verification with {client_strat}..."
                )

            print(f"Running yt-dlp in-process (strategy: {client_strat})...")

            ydl_opts = {
                "outtmpl": output_template,
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bestvideo*+bestaudio/best",
                "merge_output_format": "mp4",
                "ffmpeg_location": FFMPEG_PATH,
                "noplaylist": True,
                "progress_hooks": [ydl_progress_hook],
                "extractor_args": {
                    "youtube": {
                        "player_client": client_strat.split(",")
                    }
                },
                "quiet": True,
                "no_warnings": True,
            }
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
                if not is_bot_error:
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
# COMPILE SELECTED SHORTS
# ============================================================

@app.route("/compile", methods=["POST"])
def compile_shorts():

    print()
    print("=" * 60)
    print("COMPILING SHORTS")
    print("=" * 60)
    print()

    if not FFMPEG_PATH:

        return jsonify({
            "success": False,
            "error": "FFmpeg was not found."
        }), 500

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "success": False,
            "error": "Invalid request."
        }), 400

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
            FFMPEG_PATH,
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
            universal_newlines=True
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

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )