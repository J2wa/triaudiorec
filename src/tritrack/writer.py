"""Simultaneous 3-output high-fidelity stereo audio writer (WAV 24-bit/32f & FLAC 24-bit)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf

from .config import BitDepth, OutputFormat


@dataclass(frozen=True)
class OutputFileInfo:
    """Metadata for a single written audio output file."""

    track_id: str  # "mic", "system", "combined"
    track_label: str
    audio_format: str  # "WAV" or "FLAC"
    subtype: str  # "PCM_24" or "FLOAT"
    path: Path
    size_bytes: int


@dataclass(frozen=True)
class RecordingSummary:
    """Complete summary returned after finishing a 3-output recording session."""

    session_name: str
    output_dir: Path
    sample_rate: int
    channels: int
    total_frames: int
    duration_seconds: float
    files: List[OutputFileInfo] = field(default_factory=list)

    def files_for_track(self, track_id: str) -> List[OutputFileInfo]:
        return [f for f in self.files if f.track_id == track_id]


def sanitize_prefix(prefix: str) -> str:
    """Sanitize a user-supplied filename prefix for safe Windows/POSIX paths."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", prefix.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or "recording"


class TriTrackWriter:
    """Streams synchronized stereo blocks simultaneously to Output 1, 2, and 3 files.

    Output 1: Microphone stereo recording (`*_1_mic.<ext>`)
    Output 2: System audio stereo recording (`*_2_system.<ext>`)
    Output 3: Combined mic + system stereo recording (`*_3_combined.<ext>`)
    """

    TRACK_SPECS = (
        ("mic", "1_mic", "Output 1: Microphone"),
        ("system", "2_system", "Output 2: System Audio"),
        ("combined", "3_combined", "Output 3: Combined Mix"),
    )

    def __init__(
        self,
        output_dir: Path,
        session_prefix: str = "session",
        sample_rate: int = 48000,
        output_format: OutputFormat = OutputFormat.WAV,
        bit_depth: BitDepth = BitDepth.PCM_24,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.sample_rate = int(sample_rate)
        self.channels = 2
        self.output_format = output_format
        self.bit_depth = bit_depth

        ts = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
        safe_prefix = sanitize_prefix(session_prefix)
        self.session_name = f"{safe_prefix}_{ts}"

        self._handles: Dict[str, List[tuple[sf.SoundFile, str, str, str, Path]]] = {
            "mic": [],
            "system": [],
            "combined": [],
        }
        self._total_frames: int = 0
        self._closed: bool = False
        self._open_files()

    def _target_formats(self) -> List[tuple[str, str, str]]:
        """Return list of (extension, sf_format, sf_subtype) tuples to write."""
        formats: List[tuple[str, str, str]] = []
        if self.output_format in (OutputFormat.WAV, OutputFormat.BOTH):
            wav_subtype = (
                "FLOAT" if self.bit_depth is BitDepth.FLOAT_32 else "PCM_24"
            )
            formats.append(("wav", "WAV", wav_subtype))
        if self.output_format in (OutputFormat.FLAC, OutputFormat.BOTH):
            # FLAC supports up to 24-bit lossless integer PCM
            formats.append(("flac", "FLAC", "PCM_24"))
        return formats

    def _open_files(self) -> None:
        target_formats = self._target_formats()
        try:
            for track_id, suffix, label in self.TRACK_SPECS:
                for ext, sf_fmt, subtype in target_formats:
                    path = self.output_dir / f"{self.session_name}_{suffix}.{ext}"
                    handle = sf.SoundFile(
                        str(path),
                        mode="w",
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        subtype=subtype,
                        format=sf_fmt,
                    )
                    self._handles[track_id].append((handle, label, sf_fmt, subtype, path))
        except Exception:
            self.close()
            raise

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def duration_seconds(self) -> float:
        return self._total_frames / float(self.sample_rate)

    def write_block(
        self,
        mic_stereo: np.ndarray,
        system_stereo: np.ndarray,
        combined_stereo: np.ndarray,
    ) -> None:
        """Write one synchronized stereo block across all 3 outputs."""
        if self._closed:
            raise RuntimeError("Cannot write to a closed TriTrackWriter.")

        n_frames = mic_stereo.shape[0]
        if n_frames == 0:
            return
        if system_stereo.shape != (n_frames, 2) or combined_stereo.shape != (n_frames, 2):
            raise ValueError(
                "All 3 outputs must have identical stereo (N, 2) shape for sample-accurate sync."
            )

        blocks = {
            "mic": np.clip(mic_stereo, -1.0, 1.0),
            "system": np.clip(system_stereo, -1.0, 1.0),
            "combined": np.clip(combined_stereo, -1.0, 1.0),
        }
        for track_id, data in blocks.items():
            for handle, _, _, _, _ in self._handles[track_id]:
                handle.write(data)

        self._total_frames += n_frames

    def close(self) -> RecordingSummary:
        """Flush and finalize all open audio files and return a RecordingSummary."""
        file_infos: List[OutputFileInfo] = []
        if not self._closed:
            self._closed = True
            for track_id in ("mic", "system", "combined"):
                for handle, label, sf_fmt, subtype, path in self._handles[track_id]:
                    try:
                        handle.flush()
                    finally:
                        handle.close()
                    size = path.stat().st_size if path.exists() else 0
                    file_infos.append(
                        OutputFileInfo(
                            track_id=track_id,
                            track_label=label,
                            audio_format=sf_fmt,
                            subtype=subtype,
                            path=path,
                            size_bytes=size,
                        )
                    )

        return RecordingSummary(
            session_name=self.session_name,
            output_dir=self.output_dir,
            sample_rate=self.sample_rate,
            channels=self.channels,
            total_frames=self._total_frames,
            duration_seconds=self.duration_seconds,
            files=file_infos,
        )
