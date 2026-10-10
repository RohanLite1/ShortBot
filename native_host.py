import sys
import json
import struct
import os
import subprocess
import urllib.request
import urllib.error
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_SCRIPT = os.path.join(BASE_DIR, "backend.py")
HEALTH_URL = "http://127.0.0.1:5000/health"


def is_backend_running():
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "ShortBotNativeHost"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


_last_start_attempt = 0


def start_backend():
    global _last_start_attempt
    if is_backend_running():
        return True, "already_running"

    # Debounce if start was initiated less than 4 seconds ago
    if time.time() - _last_start_attempt < 4.0:
        return True, "starting"
    _last_start_attempt = time.time()

    # 1. Check for standalone compiled executable
    standalone_exe = os.path.join(BASE_DIR, "shortbot-engine.exe")
    if not os.path.isfile(standalone_exe):
        standalone_exe = os.path.join(BASE_DIR, "ShortBot-Engine.exe")
    if not os.path.isfile(standalone_exe):
        standalone_exe = os.path.join(BASE_DIR, "backend.exe")

    if os.path.isfile(standalone_exe):
        try:
            ps_cmd = f"Start-Process -FilePath '{standalone_exe}' -WorkingDirectory '{BASE_DIR}' -WindowStyle Hidden"
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                cwd=BASE_DIR,
                creationflags=0x08000000,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            try:
                subprocess.Popen(
                    [standalone_exe],
                    cwd=BASE_DIR,
                    creationflags=0x08000000 | 0x00000008 | 0x01000000,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                return False, str(e)
    else:
        # 2. Python development mode
        vbs_script = os.path.join(BASE_DIR, "start_backend_silent.vbs")
        if os.path.isfile(vbs_script):
            try:
                subprocess.Popen(
                    ["wscript.exe", vbs_script],
                    cwd=BASE_DIR,
                    creationflags=0x08000000,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        else:
            venv_pythonw = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
            if os.path.isfile(venv_pythonw):
                pythonw_exe = venv_pythonw
            else:
                python_exe = sys.executable
                pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
                if not os.path.exists(pythonw_exe):
                    pythonw_exe = python_exe
            try:
                subprocess.Popen(
                    [pythonw_exe, BACKEND_SCRIPT, "--silent"],
                    cwd=BASE_DIR,
                    creationflags=0x08000000 | 0x00000008 | 0x01000000,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                return False, str(e)

    # Wait up to 3 seconds for backend to become available
    for _ in range(15):
        time.sleep(0.2)
        if is_backend_running():
            return True, "started"

    return True, "starting"


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    message_length = struct.unpack("@I", raw_length)[0]
    message_bytes = sys.stdin.buffer.read(message_length)
    return json.loads(message_bytes.decode("utf-8"))


def send_message(message):
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main():
    while True:
        try:
            msg = read_message()
            if msg is None:
                break

            action = msg.get("action", "status")

            if action in ("start", "ensure_running"):
                success, detail = start_backend()
                send_message({
                    "success": success,
                    "status": detail,
                    "running": is_backend_running(),
                    "port": 5000
                })
            elif action == "status":
                running = is_backend_running()
                send_message({
                    "success": True,
                    "running": running,
                    "port": 5000
                })
            elif action == "ping":
                send_message({
                    "success": True,
                    "pong": True,
                    "running": is_backend_running()
                })
            else:
                send_message({
                    "success": False,
                    "error": f"Unknown action: {action}"
                })
        except Exception as e:
            send_message({"success": False, "error": str(e)})
            break


if __name__ == "__main__":
    main()
