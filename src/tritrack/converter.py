"""Batch-friendly export of WAV and FLAC recordings as compact copies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import numpy as np
import soundfile as sf

from .dsp import StreamingResampler, apply_gain, soft_limit_stereo


@dataclass(frozen=True)
class ConversionPreset:
    label: str
    suffix: str
    format: str
    subtype: str
    bitrate_kbps: int | None = None
    sample_rate: int | None = None


CONVERSION_PRESETS = (
    ConversionPreset("MP3 · 192 kbps · General use", "192kbps", "MP3", "MPEG_LAYER_III", 192),
    ConversionPreset("MP3 · 96 kbps · Smallest", "96kbps", "MP3", "MPEG_LAYER_III", 96),
    ConversionPreset("MP3 · 128 kbps · Smaller", "128kbps", "MP3", "MPEG_LAYER_III", 128),
    ConversionPreset("MP3 · 256 kbps · High quality", "256kbps", "MP3", "MPEG_LAYER_III", 256),
    ConversionPreset("MP3 · 320 kbps · Highest quality", "320kbps", "MP3", "MPEG_LAYER_III", 320),
    ConversionPreset("WAV · 16-bit PCM · 44.1 kHz", "16bit_44k1", "WAV", "PCM_16", sample_rate=44100),
    ConversionPreset("WAV · 16-bit PCM · 48 kHz", "16bit_48k", "WAV", "PCM_16", sample_rate=48000),
    ConversionPreset("FLAC · 24-bit · Original sample rate", "24bit", "FLAC", "PCM_24"),
)


def _reserve_destination(source: Path, preset: ConversionPreset) -> Path:
    stem = f"{source.stem}_{preset.suffix}"
    extension = preset.format.lower()
    for copy_number in count(1):
        name = stem if copy_number == 1 else f"{stem}_{copy_number}"
        destination = source.with_name(f"{name}.{extension}")
        try:
            destination.touch(exist_ok=False)
        except FileExistsError:
            continue
        return destination


def convert_recording(
    source: Path,
    preset: ConversionPreset,
    gain_db: float = 0.0,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Stream one recording to a separate file beside its source."""
    if not -24.0 <= gain_db <= 24.0:
        raise ValueError("Volume adjustment must be between -24 and +24 dB.")

    def check_cancelled() -> None:
        if cancelled is not None and cancelled():
            raise InterruptedError("Conversion cancelled.")

    with sf.SoundFile(source) as recording:
        if recording.format not in ("WAV", "WAVEX", "RF64", "FLAC"):
            raise ValueError("Choose a WAV or FLAC recording.")
        if recording.channels not in (1, 2) or recording.frames == 0:
            raise ValueError("Choose a non-empty mono or stereo recording.")

        codec_options = {}
        sample_rate = preset.sample_rate or recording.samplerate
        if preset.bitrate_kbps is not None:
            # MPEG-1 supports all of our CBR presets at 32, 44.1, and 48 kHz.
            sample_rate = min((32000, 44100, 48000), key=lambda rate: abs(rate - sample_rate))
            if recording.samplerate == 88200:
                sample_rate = 44100
            # libsndfile maps [0, 1] to [320, 32] kbps in MPEG-1 CBR mode.
            codec_options = {
                "bitrate_mode": "CONSTANT",
                "compression_level": (320 - preset.bitrate_kbps) / 288,
            }

        resampler = None
        if recording.samplerate != sample_rate:
            resampler = StreamingResampler(recording.samplerate, sample_rate)

        def write_audio(output: sf.SoundFile, frames: np.ndarray) -> None:
            # The stereo resampler duplicates mono input. Write only its first channel.
            audio = frames[:, :recording.channels]
            if gain_db != 0.0:
                audio = apply_gain(audio, gain_db)
            if gain_db > 0.0:
                audio = soft_limit_stereo(audio)
            output.write(np.clip(audio, -1.0, 1.0))

        check_cancelled()
        destination = _reserve_destination(source, preset)
        try:
            with sf.SoundFile(
                destination,
                mode="w",
                samplerate=sample_rate,
                channels=recording.channels,
                format=preset.format,
                subtype=preset.subtype,
                **codec_options,
            ) as output:
                for frames in recording.blocks(blocksize=65536, dtype="float32", always_2d=True):
                    check_cancelled()
                    write_audio(output, resampler.process(frames) if resampler else frames)
                if resampler is not None:
                    write_audio(output, resampler.flush())
            check_cancelled()
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination
