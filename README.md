# TriTrack Studio — 3-Output High-Fidelity Windows Stereo Audio Recorder

**TriTrack Studio** is a native Windows desktop audio recorder built for creators, podcasters, streamers, and engineers who need **three sample-locked, high-fidelity stereo recordings simultaneously**:

| Output | File Suffix | Description |
| :--- | :--- | :--- |
| **Output 1** | `*_1_mic.wav` / `.flac` | Isolated **Microphone** recording (stereo, 24-bit PCM) |
| **Output 2** | `*_2_system.wav` / `.flac` | Isolated **System Audio** via native **Windows WASAPI Loopback** (stereo, 24-bit PCM) |
| **Output 3** | `*_3_combined.wav` / `.flac` | Real-time **Combined Mix** of Microphone + System Audio with optional soft-knee peak limiter |

---

## Key Features

- **Native Windows WASAPI Loopback (No Virtual Audio Cables Needed):** Captures any Windows speaker, headphone, DAC, or monitor output directly via `PyAudioWPatch` — no Voicemeeter or VB-Cable required.
- **Zero-Drift Silent Keepalive Clocking:** Uses an inaudible digital-zero WASAPI render keepalive stream alongside a master-clock mixer loop so Windows continuously clocks loopback packets even during complete system silence. All 3 output tracks finish with the **exact same frame count down to the single sample**.
- **True Stereo High-Fidelity Recording:**
  - **48,000 Hz / 96,000 Hz** stereo capture (44,100 Hz also supported)
  - **24-bit PCM Uncompressed WAV** (`PCM_24`) or **32-bit Float WAV** (`FLOAT`)
  - **24-bit Lossless FLAC** (`PCM_24`) — or **Dual Export (WAV + FLAC)** simultaneously
  - Automatic **ITU-R BS.775 stereo fold-down** for 5.1/7.1 Windows playback devices and clean stereo upmix for mono USB/XLR microphones
  - **Overlap-save polyphase resampling** for click-free synchronization when mic and system audio run at different native sample rates (e.g., 44.1 kHz mic + 48 kHz speakers)
- **Studio Desktop GUI (PySide6 / Qt 6):**
  - Live pre-record monitoring with 30 FPS dual-channel **L/R dBFS stereo meters**, peak-hold markers, and clip LEDs for all 3 outputs
  - Independent gain sliders (`-24 dB` to `+18 dB`) and mute buttons for Microphone and System Audio
  - Transparent **stereo-linked soft-knee limiter** (`-1.0 dBFS` knee / `-0.1 dBFS` ceiling) to prevent clipping on Output 3 while preserving dynamic range
  - Pause & resume recording, customizable filename prefix, persistent settings, and one-click output folder access

---

## Quick Start (Windows 10 / 11)

### Option 1: One-Click Launcher (`run.bat`)
1. Install **Python 3.10+** (check **"Add Python to PATH"** during setup).
2. Clone or download this repository.
3. Double-click **`run.bat`** — it automatically creates `.venv`, installs dependencies, and launches TriTrack Studio.

### Option 2: Command Line
```powershell
git clone https://github.com/J2wa/triaudiorec.git
cd triaudiorec
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m tritrack
```

### Option 3: Build Standalone `TriTrackStudio.exe`
Double-click **`build_exe.bat`** on Windows (or download the pre-built artifact from the GitHub Actions **Test & Build Windows Executable** workflow). The compiled executable will be at `dist\TriTrackStudio.exe`.

### Demo Mode (Non-Windows / Testing UI without Audio Hardware)
```bash
python -m tritrack --demo
```

---

## Architecture Overview

```
Microphone (WASAPI Input)          System Speakers (WASAPI Loopback + Silent Keepalive)
          │                                                    │
          ▼                                                    ▼
   ensure_stereo()                                      ensure_stereo()
   (Mono->Stereo)                                  (5.1/7.1 ITU Fold-Down)
          │                                                    │
          ▼                                                    ▼
 StreamingResampler                                   StreamingResampler
(Polyphase -> 48/96k)                                (Polyphase -> 48/96k)
          │                                                    │
          ▼                                                    ▼
  StereoRingBuffer ──────────┐            ┌────────── StereoRingBuffer
                             ▼            ▼
                    Master-Clock Mixer Loop (20 ms)
                     ├──► Output 1: *_1_mic.wav / .flac
                     ├──► Output 2: *_2_system.wav / .flac
                     └──► Soft-Knee Limiter ──► Output 3: *_3_combined.wav / .flac
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

---

## License

MIT License — see [LICENSE](LICENSE).
