@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [TriTrack Studio] Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Python 3.10+ is required. Install from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [TriTrack Studio] Installing dependencies...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -r requirements.txt
    .venv\Scripts\pip.exe install -e .
)

echo [TriTrack Studio] Launching application...
start "" ".venv\Scripts\pythonw.exe" -m tritrack %*
