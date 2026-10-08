@echo off
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%native_host.py" %*
) else (
    python "%SCRIPT_DIR%native_host.py" %*
)
