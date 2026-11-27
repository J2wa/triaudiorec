"""Configuration models and JSON persistence for TriTrack Studio."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class OutputFormat(str, Enum):
    """Supported lossless high-fidelity audio output formats."""

    WAV = "wav"
    FLAC = "flac"
    BOTH = "both"

    @property
    def label(self) -> str:
        labels = {
            OutputFormat.WAV: "WAV (24-bit Uncompressed PCM)",
            OutputFormat.FLAC: "FLAC (24-bit Lossless)",
            OutputFormat.BOTH: "WAV + FLAC (Dual Export)",
        }
        return labels[self]


class BitDepth(str, Enum):
    """Supported sample bit depth / encoding subtypes."""

    PCM_24 = "PCM_24"
    FLOAT_32 = "FLOAT"

    @property
    def label(self) -> str:
        if self is BitDepth.PCM_24:
            return "24-bit PCM (Studio Hi-Fi)"
        return "32-bit Float (WAV) / 24-bit (FLAC)"


def default_output_dir() -> Path:
    """Return the default recordings output directory."""
    home = Path.home()
    music_dir = home / "Music"
    if music_dir.exists():
        return music_dir / "TriTrack Recordings"
    return home / "TriTrack Recordings"


def default_config_path() -> Path:
    """Return platform-appropriate path for persisting user settings."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "TriTrackStudio" / "settings.json"


@dataclass
class RecorderConfig:
    """Complete configuration for a 3-output stereo recording session."""

    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    session_prefix: str = "session"
    sample_rate: int = 48000
    channels: int = 2
    output_format: OutputFormat = OutputFormat.WAV
    bit_depth: BitDepth = BitDepth.PCM_24

    mic_device_id: Optional[int] = None
    system_device_id: Optional[int] = None

    mic_gain_db: float = 0.0
    system_gain_db: float = 0.0
    mic_muted: bool = False
    system_muted: bool = False
    limiter_enabled: bool = True

    def validate(self) -> None:
        """Validate configuration invariants."""
        if self.channels != 2:
            raise ValueError("TriTrack Studio operates exclusively in stereo mode (channels=2).")
        if self.sample_rate not in (44100, 48000, 88200, 96000):
            raise ValueError(f"Unsupported sample rate: {self.sample_rate} Hz")
        if not -48.0 <= self.mic_gain_db <= 24.0:
            raise ValueError(f"mic_gain_db out of range: {self.mic_gain_db}")
        if not -48.0 <= self.system_gain_db <= 24.0:
            raise ValueError(f"system_gain_db out of range: {self.system_gain_db}")

    def save(self, path: Optional[Path] = None) -> Path:
        """Persist settings to disk as JSON."""
        target = path or default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["output_format"] = self.output_format.value
        payload["bit_depth"] = self.bit_depth.value
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "RecorderConfig":
        """Load settings from JSON, falling back cleanly to defaults."""
        target = path or default_config_path()
        if not target.exists():
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            cfg = cls(
                output_dir=str(data.get("output_dir", default_output_dir())),
                session_prefix=str(data.get("session_prefix", "session")),
                sample_rate=int(data.get("sample_rate", 48000)),
                channels=2,
                output_format=OutputFormat(data.get("output_format", OutputFormat.WAV.value)),
                bit_depth=BitDepth(data.get("bit_depth", BitDepth.PCM_24.value)),
                mic_device_id=data.get("mic_device_id"),
                system_device_id=data.get("system_device_id"),
                mic_gain_db=float(data.get("mic_gain_db", 0.0)),
                system_gain_db=float(data.get("system_gain_db", 0.0)),
                mic_muted=bool(data.get("mic_muted", False)),
                system_muted=bool(data.get("system_muted", False)),
                limiter_enabled=bool(data.get("limiter_enabled", True)),
            )
            cfg.validate()
            return cfg
        except Exception:
            return cls()
