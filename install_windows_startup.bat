@echo off
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP_FOLDER%\ShortBotBackend.vbs"

echo ============================================================
echo ShortBot: Installing to Windows Startup
echo ============================================================
echo Copying silent launcher to:
echo %TARGET%
echo.

copy /y "%~dp0start_backend_silent.vbs" "%TARGET%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo Successfully installed to Windows Startup!
    echo ShortBot backend will start silently when Windows logs in.
) else (
    echo.
    echo Failed to copy shortcut.
)
echo ============================================================
pause
