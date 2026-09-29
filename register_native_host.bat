@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "JSON_PATH=%SCRIPT_DIR%\com.shortbot.backend.json"
set "JSON_PATH_FF=%SCRIPT_DIR%\com.shortbot.backend.firefox.json"
set "BAT_PATH=%SCRIPT_DIR%\native_host.bat"
set "BAT_PATH_ESC=%BAT_PATH:\=\\%"

:: Firefox Extension ID defined in manifest.json Gecko settings
set "FF_EXT_ID=shortbot@curator.app"

:: Chromium / Edge Extension ID (optional override)
set "EXT_ID=%~1"
if "%EXT_ID%"=="" set "EXT_ID=gfoaiibpnmjdgkkfpbkdgodljmepondo"

echo ============================================================
echo ShortBot: Registering Native Messaging Host (Firefox + Edge)
echo ============================================================
echo Directory: %SCRIPT_DIR%
echo Firefox Extension ID: %FF_EXT_ID%
echo Chromium Extension ID: %EXT_ID%
echo.

:: 1. Generate Firefox Native Host Manifest
(
    echo {
    echo   "name": "com.shortbot.backend",
    echo   "description": "ShortBot Native Messaging Host",
    echo   "path": "%BAT_PATH_ESC%",
    echo   "type": "stdio",
    echo   "allowed_extensions": [
    echo     "%FF_EXT_ID%"
    echo   ]
    echo }
) > "%JSON_PATH_FF%"
echo Created Firefox manifest: %JSON_PATH_FF%

:: 2. Register in Mozilla Firefox
echo Registering in Mozilla Firefox registry...
reg add "HKCU\Software\Mozilla\NativeMessagingHosts\com.shortbot.backend" /ve /t REG_SZ /d "%JSON_PATH_FF%" /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Registered for Mozilla Firefox HKCU\Software\Mozilla\NativeMessagingHosts\com.shortbot.backend
) else (
    echo [WARN] Failed to register Mozilla Firefox key.
)

:: 3. Generate Chrome/Edge Native Host Manifest
(
    echo {
    echo   "name": "com.shortbot.backend",
    echo   "description": "ShortBot Native Messaging Host",
    echo   "path": "%BAT_PATH_ESC%",
    echo   "type": "stdio",
    echo   "allowed_origins": [
    echo     "extension://%EXT_ID%/",
    echo     "chrome-extension://%EXT_ID%/"
    echo   ]
    echo }
) > "%JSON_PATH%"
echo Created Chromium manifest: %JSON_PATH%

:: 4. Register in Edge & Chrome
echo Registering in Microsoft Edge and Google Chrome...
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.shortbot.backend" /ve /t REG_SZ /d "%JSON_PATH%" /f >nul 2>&1
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.shortbot.backend" /ve /t REG_SZ /d "%JSON_PATH%" /f >nul 2>&1
echo [OK] Registered for Edge and Chrome.

echo.
echo ============================================================
echo Native Messaging Host registered successfully for all browsers!
echo Firefox and Edge can now automatically launch the ShortBot backend.
echo ============================================================
