"""End-to-end integration tests for RecordingEngine synchronized 3-output capture."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import soundfile as sf

from tritrack.backends.simulated import SimulatedBackend
from tritrack.config import BitDepth, OutputFormat, RecorderConfig
from tritrack.engine import EngineState, RecordingEngine


def test_engine_records_3_synchronized_stereo_outputs(tmp_path: Path) -> None:
    backend = SimulatedBackend(mic_rate=48000, mic_channels=2, system_rate=48000, system_channels=2)
    cfg = RecorderConfig(
        output_dir=str(tmp_path),
        session_prefix="sync_test",
        sample_rate=48000,
        output_format=OutputFormat.WAV,
        bit_depth=BitDepth.PCM_24,
        mic_device_id=101,
        system_device_id=201,
    )
    engine = RecordingEngine(backend=backend, config=cfg)

    try:
        engine.start_monitoring()
        assert engine.state is EngineState.MONITORING
        time.sleep(0.08)

        engine.start_recording()
        assert engine.state is EngineState.RECORDING
        time.sleep(0.35)

        snap = engine.get_snapshot()
        assert snap.state is EngineState.RECORDING
        assert snap.elapsed_seconds > 0.15
        assert snap.mic_active and snap.system_active

        summary = engine.stop_recording()
        assert summary is not None
        assert engine.state is EngineState.MONITORING
        assert len(summary.files) == 3
        assert summary.total_frames >= 4800

        mic_path = summary.files_for_track("mic")[0].path
        sys_path = summary.files_for_track("system")[0].path
        comb_path = summary.files_for_track("combined")[0].path

        mic_data, sr1 = sf.read(str(mic_path), dtype="float32")
        sys_data, sr2 = sf.read(str(sys_path), dtype="float32")
        comb_data, sr3 = sf.read(str(comb_path), dtype="float32")

        # All 3 files share exact sample rate, stereo shape, and frame count
        assert sr1 == sr2 == sr3 == 48000
        assert mic_data.shape == sys_data.shape == comb_data.shape
        assert mic_data.shape[1] == 2

        # All 3 outputs contain real non-silent audio
        assert float(np.max(np.abs(mic_data))) > 0.05
        assert float(np.max(np.abs(sys_data))) > 0.05
        assert float(np.max(np.abs(comb_data))) > 0.05

        # Combined output matches mic + system closely (signals are well under limiter threshold)
        diff = np.max(np.abs(comb_data - (mic_data + sys_data)))
        assert float(diff) < 1e-4
    finally:
        engine.shutdown()


def test_engine_mismatched_rates_and_silence_dropouts_stay_sample_locked(tmp_path: Path) -> None:
    # 44.1 kHz mono mic + 96 kHz stereo system with periodic WASAPI silence gaps -> 48 kHz stereo FLAC
    backend = SimulatedBackend(
        mic_rate=44100,
        mic_channels=1,
        system_rate=96000,
        system_channels=2,
        system_dropout_every_n=3,
    )
    cfg = RecorderConfig(
        output_dir=str(tmp_path),
        session_prefix="mismatch",
        sample_rate=48000,
        output_format=OutputFormat.FLAC,
        bit_depth=BitDepth.PCM_24,
        mic_device_id=102,  # 44.1kHz mono
        system_device_id=202,  # 96kHz stereo
    )
    engine = RecordingEngine(backend=backend, config=cfg)

    try:
        engine.start_recording()
        time.sleep(0.35)
        summary = engine.stop_recording()
        assert summary is not None
        assert len(summary.files) == 3

        infos = [sf.info(str(f.path)) for f in summary.files]
        assert all(i.format == "FLAC" and i.subtype == "PCM_24" for i in infos)
        assert all(i.samplerate == 48000 and i.channels == 2 for i in infos)
        # Exact frame-count equality across all 3 outputs despite rate mismatch & dropouts
        assert infos[0].frames == infos[1].frames == infos[2].frames
        assert infos[0].frames >= 4800
    finally:
        engine.shutdown()


def test_engine_pause_resume_and_live_mute(tmp_path: Path) -> None:
    backend = SimulatedBackend()
    cfg = RecorderConfig(
        output_dir=str(tmp_path),
        session_prefix="mute_pause",
        sample_rate=48000,
        output_format=OutputFormat.BOTH,
        mic_device_id=101,
        system_device_id=201,
        mic_muted=True,
    )
    engine = RecordingEngine(backend=backend, config=cfg)

    try:
        engine.start_recording()
        time.sleep(0.15)
        engine.pause_recording()
        assert engine.state is EngineState.PAUSED
        paused_frames = engine.get_snapshot().elapsed_seconds
        time.sleep(0.12)
        # Elapsed recording time freezes while paused
        assert abs(engine.get_snapshot().elapsed_seconds - paused_frames) < 0.025

        engine.resume_recording()
        assert engine.state is EngineState.RECORDING
        time.sleep(0.15)

        summary = engine.stop_recording()
        assert summary is not None
        assert len(summary.files) == 6  # 3 WAV + 3 FLAC

        mic_wav = [f for f in summary.files_for_track("mic") if f.audio_format == "WAV"][0].path
        sys_wav = [f for f in summary.files_for_track("system") if f.audio_format == "WAV"][0].path
        comb_wav = [f for f in summary.files_for_track("combined") if f.audio_format == "WAV"][0].path

        mic_data, _ = sf.read(str(mic_wav), dtype="float32")
        sys_data, _ = sf.read(str(sys_wav), dtype="float32")
        comb_data, _ = sf.read(str(comb_wav), dtype="float32")

        # Mic was muted -> Output 1 is exact digital silence; Output 3 equals Output 2
        assert float(np.max(np.abs(mic_data))) == 0.0
        assert float(np.max(np.abs(sys_data))) > 0.05
        assert float(np.max(np.abs(comb_data - sys_data))) < 1e-4
    finally:
        engine.shutdown()
