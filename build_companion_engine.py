import os
import sys
import shutil
import subprocess
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
OUTPUT_DIR = os.path.join(DIST_DIR, "ShortBot-Engine")

def find_pyinstaller():
    venv_pyinstaller = os.path.join(BASE_DIR, ".venv", "Scripts", "pyinstaller.exe")
    if os.path.isfile(venv_pyinstaller):
        return venv_pyinstaller
    which_py = shutil.which("pyinstaller")
    if which_py:
        return which_py
    raise RuntimeError("PyInstaller not found in .venv or PATH!")

def find_system_ffmpeg_dir():
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return os.path.dirname(ffmpeg_exe)
    return None

def build():
    pyinstaller = find_pyinstaller()
    print("=" * 60)
    print("BUILDING SHORTBOT COMPANION ENGINE (STANDALONE WINDOWS)")
    print("Using PyInstaller:", pyinstaller)
    print("=" * 60)

    # Clean previous build artifacts
    if os.path.exists(OUTPUT_DIR):
        print(f"Cleaning previous build: {OUTPUT_DIR}...")
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    os.makedirs(DIST_DIR, exist_ok=True)

    # 1. Build backend service into onedir
    print("\n[1/5] Compiling backend service into standalone executable...")
    cmd_backend = [
        pyinstaller,
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "ShortBot-Engine",
        "--distpath", DIST_DIR,
        "--add-data", f"{os.path.join(BASE_DIR, 'ui')};ui",
        "--hidden-import", "requests",
        "--hidden-import", "yt_dlp",
        "--hidden-import", "flask",
        "--hidden-import", "ai_engine",
        "--hidden-import", "agent",
        "--hidden-import", "request_parser",
        "--hidden-import", "classifier",
        os.path.join(BASE_DIR, "backend.py")
    ]
    subprocess.run(cmd_backend, cwd=BASE_DIR, check=True)

    # Rename ShortBot-Engine.exe to shortbot-engine.exe if needed
    main_exe = os.path.join(OUTPUT_DIR, "ShortBot-Engine.exe")
    canonical_exe = os.path.join(OUTPUT_DIR, "shortbot-engine.exe")
    if os.path.isfile(main_exe) and not os.path.isfile(canonical_exe):
        shutil.copy2(main_exe, canonical_exe)

    # 2. Build native_host.exe into single file directly inside OUTPUT_DIR
    print("\n[2/5] Compiling native messaging host executable...")
    cmd_host = [
        pyinstaller,
        "--noconfirm",
        "--onefile",
        "--console",
        "--name", "native_host",
        "--distpath", OUTPUT_DIR,
        os.path.join(BASE_DIR, "native_host.py")
    ]
    subprocess.run(cmd_host, cwd=BASE_DIR, check=True)

    # 3. Bundle FFmpeg and FFprobe binaries
    print("\n[3/5] Bundling FFmpeg binaries...")
    ffmpeg_dir = find_system_ffmpeg_dir()
    if ffmpeg_dir:
        bin_target = os.path.join(OUTPUT_DIR, "bin")
        os.makedirs(bin_target, exist_ok=True)
        # Copy ffmpeg.exe, ffprobe.exe and shared DLLs
        for fname in os.listdir(ffmpeg_dir):
            if fname.lower().endswith((".exe", ".dll")):
                src = os.path.join(ffmpeg_dir, fname)
                dst = os.path.join(bin_target, fname)
                shutil.copy2(src, dst)
        print(f"  + Bundled FFmpeg files from {ffmpeg_dir} to {bin_target}")
    else:
        print("  ! Warning: System FFmpeg not found.")

    # 4. Generate 1-Click Installer Script inside OUTPUT_DIR
    print("\n[4/5] Generating 1-Click Windows registration installer...")
    install_bat = os.path.join(OUTPUT_DIR, "Install-ShortBot.bat")
    with open(install_bat, "w", encoding="utf-8") as f:
        f.write("""@echo off
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "HOST_EXE=%APP_DIR%\\native_host.exe"
set "HOST_EXE_ESC=%HOST_EXE:\\=\\\\%"

echo ============================================================
echo   Installing ShortBot Desktop Companion Engine
echo ============================================================
echo Directory: %APP_DIR%
echo.

:: 1. Write Firefox Native Host Manifest
(
    echo {
    echo   "name": "com.shortbot.backend",
    echo   "description": "ShortBot Native Messaging Host",
    echo   "path": "%HOST_EXE_ESC%",
    echo   "type": "stdio",
    echo   "allowed_extensions": [
    echo     "shortbot@curator.app"
    echo   ]
    echo }
) > "%APP_DIR%\\com.shortbot.backend.firefox.json"

:: 2. Write Chrome / Edge Native Host Manifest
(
    echo {
    echo   "name": "com.shortbot.backend",
    echo   "description": "ShortBot Native Messaging Host",
    echo   "path": "%HOST_EXE_ESC%",
    echo   "type": "stdio",
    echo   "allowed_origins": [
    echo     "extension://gfoaiibpnmjdgkkfpbkdgodljmepondo/",
    echo     "chrome-extension://gfoaiibpnmjdgkkfpbkdgodljmepondo/"
    echo   ]
    echo }
) > "%APP_DIR%\\com.shortbot.backend.json"

:: 3. Register in Mozilla Firefox
reg add "HKCU\\Software\\Mozilla\\NativeMessagingHosts\\com.shortbot.backend" /ve /t REG_SZ /d "%APP_DIR%\\com.shortbot.backend.firefox.json" /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Registered with Mozilla Firefox.
)

:: 4. Register in Microsoft Edge and Google Chrome
reg add "HKCU\\Software\\Microsoft\\Edge\\NativeMessagingHosts\\com.shortbot.backend" /ve /t REG_SZ /d "%APP_DIR%\\com.shortbot.backend.json" /f >nul 2>&1
reg add "HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.shortbot.backend" /ve /t REG_SZ /d "%APP_DIR%\\com.shortbot.backend.json" /f >nul 2>&1
echo [OK] Registered with Edge and Chrome.

:: 5. Start engine silently
if exist "%APP_DIR%\\shortbot-engine.exe" (
    start "" "%APP_DIR%\\shortbot-engine.exe"
) else (
    start "" "%APP_DIR%\\ShortBot-Engine.exe"
)

echo.
echo ============================================================
echo   Installation Complete!
echo   Open Firefox or Edge to start using ShortBot.
echo ============================================================
ping -n 3 127.0.0.1 >nul

""")

    # 5. Create Distribution Zip
    print("\n[5/5] Creating final release zip: ShortBot-Engine-Windows.zip...")
    zip_path = os.path.join(DIST_DIR, "ShortBot-Engine-Windows.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for file in files:
                abs_p = os.path.join(root, file)
                rel_p = os.path.relpath(abs_p, DIST_DIR)
                z.write(abs_p, rel_p)

    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print("\n" + "=" * 60)
    print("[SUCCESS] Standalone Companion Package Complete!")
    print(f"Folder: {OUTPUT_DIR}")
    print(f"Zip:    {zip_path} ({zip_size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    build()
