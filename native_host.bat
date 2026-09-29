@echo off
if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" "%~dp0native_host.py" %*
) else (
    python "%~dp0native_host.py" %*
)

