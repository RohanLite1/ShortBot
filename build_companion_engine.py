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
    # 1. System PATH
    ffmpeg_exe = shutil.which("ffmpeg")
    if ffmpeg_exe:
        return os.path.dirname(ffmpeg_exe)

    # 2. Local workspace bin/
    local_bin = os.path.join(BASE_DIR, "bin", "ffmpeg.exe")
    if os.path.isfile(local_bin):
        return os.path.dirname(local_bin)

    # 3. Check WinGet packages directory in LocalAppData
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        shortbot_bin = os.path.join(local_app_data, "ShortBot", "bin", "ffmpeg.exe")
        if os.path.isfile(shortbot_bin):
            return os.path.dirname(shortbot_bin)
        winget_pkgs = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_pkgs):
            for root, dirs, files in os.walk(winget_pkgs):
                for f in files:
                    if f.lower() == "ffmpeg.exe":
                        return root

    # 4. Common installation locations
    for common_dir in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin", r"C:\Program Files (x86)\ffmpeg\bin"):
        if os.path.isfile(os.path.join(common_dir, "ffmpeg.exe")):
            return common_dir

    return None

def find_iscc():
    candidates = [
        shutil.which("iscc"),
        shutil.which("ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        r"C:\Users\bigma\AppData\Local\Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata and os.path.isdir(local_appdata):
        for root, dirs, files in os.walk(local_appdata):
            if "ISCC.exe" in files:
                return os.path.join(root, "ISCC.exe")
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
        "--add-data", f"{os.path.join(BASE_DIR, 'browser_search.js')};.",
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

    # Copy browser_search.js directly into output folder as well
    src_js = os.path.join(BASE_DIR, "browser_search.js")
    if os.path.isfile(src_js):
        shutil.copy2(src_js, os.path.join(OUTPUT_DIR, "browser_search.js"))

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
    print("\n[3/5] Bundling FFmpeg binaries (optimized)...")
    ffmpeg_dir = find_system_ffmpeg_dir()
    UNNEEDED_BINARIES = {"ffplay.exe", "avdevice-63.dll", "avdevice.dll"}
    if ffmpeg_dir:
        bin_target = os.path.join(OUTPUT_DIR, "bin")
        os.makedirs(bin_target, exist_ok=True)
        # Copy ffmpeg.exe, ffprobe.exe and shared DLLs
        for fname in os.listdir(ffmpeg_dir):
            if fname.lower().endswith((".exe", ".dll")) and fname.lower() not in UNNEEDED_BINARIES:
                src = os.path.join(ffmpeg_dir, fname)
                dst = os.path.join(bin_target, fname)
                shutil.copy2(src, dst)
        print(f"  + Bundled optimized FFmpeg files from {ffmpeg_dir} to {bin_target}")
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

:: Check for FFmpeg
if not exist "%APP_DIR%\\bin\\ffmpeg.exe" (
    where ffmpeg >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        where winget >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo [ShortBot] Setting up media processing engine via WinGet...
            winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements --silent >nul 2>&1
        )
    )
)

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

:: 5. Register in Windows Autostart (Startup on boot)
reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "ShortBotEngine" /t REG_SZ /d "\"%APP_DIR%\\ShortBot-Engine.exe\" --autostart" /f >nul 2>&1
echo [OK] Registered in Windows Startup (Autostarts on boot).

:: 6. Start engine
if exist "%APP_DIR%\\shortbot-engine.exe" (
    start "" "%APP_DIR%\\shortbot-engine.exe"
) else (
    start "" "%APP_DIR%\\ShortBot-Engine.exe"
)

echo.
echo ============================================================
echo   Installation Complete!
echo   ShortBot is now registered and will start automatically with Windows.
echo   Open Firefox, Chrome, or Edge to start using ShortBot.
echo ============================================================
ping -n 3 127.0.0.1 >nul

""")

    # 4. Clean temporary downloads and log artifacts
    downloads_dir = os.path.join(OUTPUT_DIR, "downloads")
    if os.path.isdir(downloads_dir):
        shutil.rmtree(downloads_dir, ignore_errors=True)
    os.makedirs(downloads_dir, exist_ok=True)

    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            if f.lower().endswith((".mp4", ".mkv", ".webm", ".part", ".ytdl", ".log")):
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass

    # 5. Compile Native Inno Setup Windows Installers (.exe)
    print("\n[4/5] Compiling native Windows Setup wizards...")
    iscc = find_iscc()
    setup_full = os.path.join(DIST_DIR, "ShortBot-Setup.exe")
    setup_lite = os.path.join(DIST_DIR, "ShortBot-Setup-Lite.exe")

    if iscc:
        iss_path = os.path.join(BASE_DIR, "installer.iss")
        print(f"  + Found Inno Setup Compiler: {iscc}")

        # Build Lite installer (~26 MB)
        print("  -> Compiling ShortBot-Setup-Lite.exe (ultra-compact, ~26MB)...")
        subprocess.run([iscc, "/Q", "/DMyAppFlavor=Lite", iss_path], cwd=BASE_DIR)

        # Build Full installer (~81 MB)
        print("  -> Compiling ShortBot-Setup.exe (full offline bundle with FFmpeg)...")
        subprocess.run([iscc, "/Q", "/DMyAppFlavor=Full", iss_path], cwd=BASE_DIR)

        if os.path.isfile(setup_lite):
            print(f"  + SUCCESS (Lite): {setup_lite} ({os.path.getsize(setup_lite)/(1024*1024):.1f} MB)")
        if os.path.isfile(setup_full):
            setup_alias = os.path.join(DIST_DIR, "ShortBot-Engine-Setup.exe")
            shutil.copy2(setup_full, setup_alias)
            print(f"  + SUCCESS (Full): {setup_full} ({os.path.getsize(setup_full)/(1024*1024):.1f} MB)")
            print(f"  + ALIAS CREATED:  {setup_alias}")
    else:
        print("  ! Note: ISCC.exe not found. Setup wizard not compiled.")

    # 6. Create Release Distribution Packages (.zip)
    print("\n[5/5] Creating release distribution packages...")
    
    # 6a. Lightweight release (~29MB - Recommended for GitHub)
    zip_light = os.path.join(DIST_DIR, "ShortBot-Engine-Windows.zip")
    with zipfile.ZipFile(zip_light, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            parts = root.split(os.sep)
            if "bin" in parts or "downloads" in parts:
                continue
            for file in files:
                abs_p = os.path.join(root, file)
                rel_p = os.path.relpath(abs_p, DIST_DIR)
                z.write(abs_p, rel_p)

    # 6b. Full offline release (with bundled FFmpeg)
    zip_full = os.path.join(DIST_DIR, "ShortBot-Engine-Windows-Full.zip")
    with zipfile.ZipFile(zip_full, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            if "downloads" in root.split(os.sep):
                continue
            for file in files:
                abs_p = os.path.join(root, file)
                rel_p = os.path.relpath(abs_p, DIST_DIR)
                z.write(abs_p, rel_p)

    # Also update organized release folders
    installers_dir = os.path.join(DIST_DIR, "installers")
    portable_dir = os.path.join(DIST_DIR, "portable")
    os.makedirs(installers_dir, exist_ok=True)
    os.makedirs(portable_dir, exist_ok=True)
    if os.path.isfile(setup_full):
        shutil.copy2(setup_full, os.path.join(installers_dir, "ShortBot-v1.2.1-Setup-Full.exe"))
    if os.path.isfile(setup_lite):
        shutil.copy2(setup_lite, os.path.join(installers_dir, "ShortBot-v1.2.1-Setup-Lite.exe"))
    if os.path.isfile(zip_full):
        shutil.copy2(zip_full, os.path.join(portable_dir, "ShortBot-v1.2.1-Portable-Full.zip"))
    if os.path.isfile(zip_light):
        shutil.copy2(zip_light, os.path.join(portable_dir, "ShortBot-v1.2.1-Portable-Lite.zip"))

    size_light_mb = os.path.getsize(zip_light) / (1024 * 1024)
    size_full_mb = os.path.getsize(zip_full) / (1024 * 1024)
    print("\n" + "=" * 60)
    print("[SUCCESS] Standalone Companion Packages Complete!")
    print(f"Folder:       {OUTPUT_DIR}")
    if os.path.isfile(setup_lite):
        print(f"Lite Setup:   {setup_lite} ({os.path.getsize(setup_lite)/(1024*1024):.1f} MB) -> ULTRA-COMPACT 1-CLICK INSTALLER")
    if os.path.isfile(setup_full):
        print(f"Full Setup:   {setup_full} ({os.path.getsize(setup_full)/(1024*1024):.1f} MB) -> ALL CODECS INCLUDED")
    print(f"Lightweight:  {zip_light} ({size_light_mb:.1f} MB) -> FAST DOWNLOAD ZIP")
    print(f"Full Offline: {zip_full} ({size_full_mb:.1f} MB) -> ALL CODECS ZIP")
    print("=" * 60)

if __name__ == "__main__":
    build()
