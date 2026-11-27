@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [TriTrack Studio] Creating virtual environment...
    python -m venv .venv
)

echo [TriTrack Studio] Installing runtime and build dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip.exe install -r requirements-dev.txt
.venv\Scripts\pip.exe install -e .

echo [TriTrack Studio] Building standalone Windows executable...
.venv\Scripts\pyinstaller.exe ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name "TriTrackStudio" ^
    --paths src ^
    --collect-all soundfile ^
    --collect-all _soundfile_data ^
    --hidden-import pyaudiowpatch ^
    src/tritrack/__main__.py

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo.
echo [TriTrack Studio] Build complete: dist\TriTrackStudio.exe
pause
