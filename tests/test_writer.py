"""Unit tests for TriTrackWriter WAV/FLAC 24-bit stereo file output and config persistence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from tritrack.config import BitDepth, OutputFormat, RecorderConfig
from tritrack.writer import TriTrackWriter


def _make_stereo_sine(freq_l: float, freq_r: float, sr: int, frames: int) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / sr
    left = (0.3 * np.sin(2.0 * np.pi * freq_l * t)).astype(np.float32)
    right = (0.3 * np.sin(2.0 * np.pi * freq_r * t)).astype(np.float32)
    return np.column_stack((left, right))


def test_writer_creates_3_hifi_24bit_stereo_wav_files(tmp_path: Path) -> None:
    sr = 48000
    frames = 4800  # 100 ms
    mic = _make_stereo_sine(440.0, 440.0, sr, frames)
    sys_audio = _make_stereo_sine(261.63, 392.0, sr, frames)
    combined = mic + sys_audio

    writer = TriTrackWriter(
        output_dir=tmp_path,
        session_prefix="studio test!",
        sample_rate=sr,
        output_format=OutputFormat.WAV,
        bit_depth=BitDepth.PCM_24,
        timestamp=datetime(2026, 11, 26, 12, 0, 0),
    )
    writer.write_block(mic, sys_audio, combined)
    summary = writer.close()

    assert summary.sample_rate == 48000
    assert summary.channels == 2
    assert summary.total_frames == frames
    assert len(summary.files) == 3

    expected_suffixes = ["_1_mic.wav", "_2_system.wav", "_3_combined.wav"]
    for info, suffix in zip(summary.files, expected_suffixes):
        assert info.path.exists()
        assert info.path.name.endswith(suffix)
        sf_info = sf.info(str(info.path))
        assert sf_info.samplerate == 48000
        assert sf_info.channels == 2
        assert sf_info.format == "WAV"
        assert sf_info.subtype == "PCM_24"
        assert sf_info.frames == frames

    # Verify high-fidelity 24-bit accuracy against original float32 signal
    read_comb, read_sr = sf.read(str(summary.files_for_track("combined")[0].path), dtype="float32")
    assert read_sr == sr
    max_err = float(np.max(np.abs(read_comb - combined)))
    assert max_err < 1e-6


def test_writer_flac_24bit_lossless_stereo(tmp_path: Path) -> None:
    sr = 48000
    frames = 9600
    mic = _make_stereo_sine(330.0, 660.0, sr, frames)
    sys_audio = _make_stereo_sine(500.0, 1000.0, sr, frames)
    combined = mic + sys_audio

    writer = TriTrackWriter(
        output_dir=tmp_path,
        session_prefix="lossless",
        sample_rate=sr,
        output_format=OutputFormat.FLAC,
        bit_depth=BitDepth.PCM_24,
    )
    writer.write_block(mic, sys_audio, combined)
    summary = writer.close()

    assert len(summary.files) == 3
    for info in summary.files:
        assert info.path.suffix == ".flac"
        sf_info = sf.info(str(info.path))
        assert sf_info.format == "FLAC"
        assert sf_info.subtype == "PCM_24"
        assert sf_info.channels == 2
        assert sf_info.samplerate == 48000
        assert sf_info.frames == frames


def test_writer_dual_wav_and_flac_96khz(tmp_path: Path) -> None:
    sr = 96000
    frames = 4800
    mic = _make_stereo_sine(440.0, 880.0, sr, frames)
    sys_audio = _make_stereo_sine(220.0, 330.0, sr, frames)
    combined = mic + sys_audio

    writer = TriTrackWriter(
        output_dir=tmp_path,
        session_prefix="hires",
        sample_rate=sr,
        output_format=OutputFormat.BOTH,
        bit_depth=BitDepth.FLOAT_32,
    )
    writer.write_block(mic, sys_audio, combined)
    summary = writer.close()

    assert len(summary.files) == 6
    wavs = [f for f in summary.files if f.audio_format == "WAV"]
    flacs = [f for f in summary.files if f.audio_format == "FLAC"]
    assert len(wavs) == 3
    assert len(flacs) == 3

    for w in wavs:
        info = sf.info(str(w.path))
        assert info.samplerate == 96000
        assert info.subtype == "FLOAT"
        assert info.channels == 2
    for fl in flacs:
        info = sf.info(str(fl.path))
        assert info.samplerate == 96000
        assert info.subtype == "PCM_24"
        assert info.channels == 2


def test_config_json_persistence(tmp_path: Path) -> None:
    cfg_path = tmp_path / "settings.json"
    cfg = RecorderConfig(
        output_dir=str(tmp_path / "out"),
        session_prefix="podcast",
        sample_rate=96000,
        output_format=OutputFormat.BOTH,
        bit_depth=BitDepth.PCM_24,
        mic_gain_db=3.5,
        system_gain_db=-4.0,
        limiter_enabled=False,
    )
    cfg.save(cfg_path)
    loaded = RecorderConfig.load(cfg_path)
    assert loaded == cfg


def test_writer_preserves_an_earlier_take_with_the_same_timestamp(tmp_path: Path) -> None:
    timestamp = datetime(2026, 11, 26, 12, 0, 0)
    first = TriTrackWriter(tmp_path, timestamp=timestamp, output_format=OutputFormat.BOTH)
    audio = _make_stereo_sine(440.0, 880.0, 48000, 480)
    first.write_block(audio, audio, audio)
    first_summary = first.close()
    original_files = {info.path: info.path.read_bytes() for info in first_summary.files}

    second = TriTrackWriter(tmp_path, timestamp=timestamp, output_format=OutputFormat.BOTH)
    second_summary = second.close()

    assert len(second_summary.files) == len(original_files) == 6
    assert all(info.path not in original_files for info in second_summary.files)
    assert all(path.read_bytes() == original for path, original in original_files.items())
