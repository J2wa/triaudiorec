"""Core real-time RecordingEngine synchronizing Mic, System WASAPI Loopback, and Combined stereo outputs."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

import numpy as np

from .backends.base import ActiveStream, AudioBackend, AudioDeviceInfo
from .config import RecorderConfig
from .dsp import (
    StereoLevel,
    StereoRingBuffer,
    StreamingResampler,
    apply_gain,
    compute_stereo_levels,
    ensure_stereo,
    mix_stereo,
)
from .writer import RecordingSummary, TriTrackWriter

logger = logging.getLogger(__name__)


class EngineState(str, Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    RECORDING = "recording"
    PAUSED = "paused"


@dataclass(frozen=True)
class EngineSnapshot:
    """Thread-safe telemetry snapshot polled by the GUI at high frame rate."""

    state: EngineState
    elapsed_seconds: float
    mic_level: StereoLevel
    system_level: StereoLevel
    combined_level: StereoLevel
    sample_rate: int
    mic_active: bool
    system_active: bool
    last_error: Optional[str] = None


class RecordingEngine:
    """Coordinates live monitoring and sample-locked 3-output stereo recording.

    All three outputs share a single master mixer clock:
    - Output 1 (`*_1_mic`): Processed stereo Microphone feed
    - Output 2 (`*_2_system`): Processed stereo System Audio (WASAPI Loopback) feed
    - Output 3 (`*_3_combined`): Stereo mix of Output 1 + Output 2 with optional soft-knee limiter
    """

    def __init__(self, backend: AudioBackend, config: Optional[RecorderConfig] = None) -> None:
        self._backend = backend
        self._config = config or RecorderConfig()
        self._config.validate()

        # Serialize lifecycle changes separately from the lock used by the mixer.
        self._lifecycle_lock = threading.RLock()
        self._lock = threading.RLock()
        self._state = EngineState.IDLE

        self._mic_stream: Optional[ActiveStream] = None
        self._sys_stream: Optional[ActiveStream] = None
        self._mic_resampler: Optional[StreamingResampler] = None
        self._sys_resampler: Optional[StreamingResampler] = None

        # Keep up to 250 ms latency cap in ring buffers to prevent long-term hardware clock drift
        max_buf_frames = max(4096, self._config.sample_rate // 4)
        self._mic_buffer = StereoRingBuffer(max_frames=max_buf_frames)
        self._sys_buffer = StereoRingBuffer(max_frames=max_buf_frames)

        self._writer: Optional[TriTrackWriter] = None
        self._mixer_stop = threading.Event()
        self._mixer_thread: Optional[threading.Thread] = None

        self._mic_level = StereoLevel()
        self._sys_level = StereoLevel()
        self._comb_level = StereoLevel()
        self._last_error: Optional[str] = None
        self._recorded_frames: int = 0

    @property
    def backend_name(self) -> str:
        return self._backend.backend_name

    @property
    def config(self) -> RecorderConfig:
        return self._config

    @property
    def state(self) -> EngineState:
        with self._lock:
            return self._state

    def list_microphones(self) -> List[AudioDeviceInfo]:
        return self._backend.list_microphones()

    def list_system_loopbacks(self) -> List[AudioDeviceInfo]:
        return self._backend.list_system_loopbacks()

    def update_mixer_params(
        self,
        *,
        mic_gain_db: Optional[float] = None,
        system_gain_db: Optional[float] = None,
        mic_muted: Optional[bool] = None,
        system_muted: Optional[bool] = None,
        limiter_enabled: Optional[bool] = None,
    ) -> None:
        """Update real-time gain, mute, and limiter parameters lock-safely."""
        with self._lock:
            if mic_gain_db is not None:
                self._config.mic_gain_db = float(mic_gain_db)
            if system_gain_db is not None:
                self._config.system_gain_db = float(system_gain_db)
            if mic_muted is not None:
                self._config.mic_muted = bool(mic_muted)
            if system_muted is not None:
                self._config.system_muted = bool(system_muted)
            if limiter_enabled is not None:
                self._config.limiter_enabled = bool(limiter_enabled)

    def update_config(self, config: RecorderConfig) -> None:
        """Replace recording configuration (only allowed when not actively recording)."""
        with self._lifecycle_lock:
            config.validate()
            with self._lock:
                if self._state in (EngineState.RECORDING, EngineState.PAUSED):
                    raise RuntimeError("Stop recording before changing sample rate or output format.")
                restart_monitor = self._state is EngineState.MONITORING and (
                    config.sample_rate != self._config.sample_rate
                    or config.mic_device_id != self._config.mic_device_id
                    or config.system_device_id != self._config.system_device_id
                )
                self._config = config
            if restart_monitor:
                self.start_monitoring()

    def _make_mic_callback(self, target_sr: int):
        def _on_mic_chunk(raw_frames: np.ndarray, source_sr: int) -> None:
            stereo = ensure_stereo(raw_frames)
            resampler = self._mic_resampler
            if resampler is None or resampler.source_rate != source_sr or resampler.target_rate != target_sr:
                resampler = StreamingResampler(source_sr, target_sr)
                self._mic_resampler = resampler
            resampled = resampler.process(stereo)
            if resampled.shape[0] > 0:
                self._mic_buffer.push(resampled)

        return _on_mic_chunk

    def _make_sys_callback(self, target_sr: int):
        def _on_sys_chunk(raw_frames: np.ndarray, source_sr: int) -> None:
            stereo = ensure_stereo(raw_frames)
            resampler = self._sys_resampler
            if resampler is None or resampler.source_rate != source_sr or resampler.target_rate != target_sr:
                resampler = StreamingResampler(source_sr, target_sr)
                self._sys_resampler = resampler
            resampled = resampler.process(stereo)
            if resampled.shape[0] > 0:
                self._sys_buffer.push(resampled)

        return _on_sys_chunk

    def start_monitoring(
        self,
        mic_device_id: Optional[int] = None,
        system_device_id: Optional[int] = None,
    ) -> None:
        """Open Mic and System Loopback streams and begin live stereo metering."""
        with self._lifecycle_lock:
            state = self.state
            if state in (EngineState.RECORDING, EngineState.PAUSED):
                raise RuntimeError("Cannot restart monitoring while recording is active.")
            if state is EngineState.MONITORING:
                self.stop_monitoring()

            with self._lock:
                if mic_device_id is not None:
                    self._config.mic_device_id = mic_device_id
                if system_device_id is not None:
                    self._config.system_device_id = system_device_id

                target_sr = self._config.sample_rate
                max_buf_frames = max(4096, target_sr // 4)
                self._mic_buffer = StereoRingBuffer(max_frames=max_buf_frames)
                self._sys_buffer = StereoRingBuffer(max_frames=max_buf_frames)
                self._mic_resampler = None
                self._sys_resampler = None
                self._last_error = None

                errors: List[str] = []

                if self._config.mic_device_id is not None:
                    try:
                        self._mic_stream = self._backend.open_microphone_stream(
                            self._config.mic_device_id,
                            self._make_mic_callback(target_sr),
                        )
                    except Exception as exc:
                        logger.warning("Failed to open microphone stream: %s", exc)
                        errors.append(f"Mic: {exc}")
                        self._mic_stream = None

                if self._config.system_device_id is not None:
                    try:
                        self._sys_stream = self._backend.open_system_loopback_stream(
                            self._config.system_device_id,
                            self._make_sys_callback(target_sr),
                        )
                    except Exception as exc:
                        logger.warning("Failed to open system loopback stream: %s", exc)
                        errors.append(f"System Audio: {exc}")
                        self._sys_stream = None

                if errors:
                    self._last_error = " | ".join(errors)

                self._mixer_stop.clear()
                self._state = EngineState.MONITORING
                self._mixer_thread = threading.Thread(
                    target=self._mixer_loop,
                    name="TriTrackMixerLoop",
                    daemon=True,
                )
                self._mixer_thread.start()

    def stop_monitoring(self) -> None:
        """Stop live monitoring and release hardware capture streams."""
        with self._lifecycle_lock:
            self.stop_recording()
            with self._lock:
                self._mixer_stop.set()
                thread = self._mixer_thread
                self._mixer_thread = None

            if thread is not None and thread.is_alive():
                thread.join()

            with self._lock:
                for stream in (self._mic_stream, self._sys_stream):
                    if stream is not None:
                        try:
                            stream.stop()
                        except Exception:
                            logger.debug("Error stopping stream", exc_info=True)
                self._mic_stream = None
                self._sys_stream = None
                self._mic_buffer.clear()
                self._sys_buffer.clear()
                self._mic_level = StereoLevel()
                self._sys_level = StereoLevel()
                self._comb_level = StereoLevel()
                self._state = EngineState.IDLE

    def start_recording(self) -> None:
        """Start synchronized 3-output stereo recording immediately."""
        with self._lifecycle_lock:
            state = self.state
            if state in (EngineState.RECORDING, EngineState.PAUSED):
                raise RuntimeError("Recording is already active.")
            if state is EngineState.IDLE:
                self.start_monitoring()

            with self._lock:
                # Align both buffers tightly at the start of the recording take
                self._mic_buffer.clear()
                self._sys_buffer.clear()
                self._recorded_frames = 0

                self._writer = TriTrackWriter(
                    output_dir=Path(self._config.output_dir),
                    session_prefix=self._config.session_prefix,
                    sample_rate=self._config.sample_rate,
                    output_format=self._config.output_format,
                    bit_depth=self._config.bit_depth,
                )
                self._state = EngineState.RECORDING

    def pause_recording(self) -> None:
        """Pause writing to all 3 outputs while keeping live stereo meters active."""
        with self._lock:
            if self._state is EngineState.RECORDING:
                self._state = EngineState.PAUSED

    def resume_recording(self) -> None:
        """Resume synchronized writing to all 3 outputs."""
        with self._lock:
            if self._state is EngineState.PAUSED:
                self._mic_buffer.clear()
                self._sys_buffer.clear()
                self._state = EngineState.RECORDING

    def stop_recording(self) -> Optional[RecordingSummary]:
        """Stop recording, finalize all 3 output files, and return the RecordingSummary."""
        with self._lifecycle_lock:
            with self._lock:
                if self._state not in (EngineState.RECORDING, EngineState.PAUSED):
                    return None
                writer = self._writer
                self._writer = None
                self._state = EngineState.MONITORING if self._mixer_thread else EngineState.IDLE

            if writer is not None:
                return writer.close()
            return None

    def get_snapshot(self) -> EngineSnapshot:
        """Return an immutable snapshot of current recording status and L/R levels."""
        with self._lock:
            sr = self._config.sample_rate
            elapsed = self._recorded_frames / float(sr) if sr > 0 else 0.0
            return EngineSnapshot(
                state=self._state,
                elapsed_seconds=elapsed,
                mic_level=self._mic_level,
                system_level=self._sys_level,
                combined_level=self._comb_level,
                sample_rate=sr,
                mic_active=self._mic_stream is not None,
                system_active=self._sys_stream is not None,
                last_error=self._last_error,
            )

    def _mixer_loop(self) -> None:
        """Master-clock 20 ms stereo mixing loop driving meters and 3-output file writes."""
        sr = self._config.sample_rate
        block_frames = max(256, sr // 50)  # Exact 20 ms blocks (e.g., 960 frames @ 48 kHz)
        block_duration = block_frames / float(sr)
        next_tick = time.perf_counter()

        while not self._mixer_stop.is_set():
            next_tick += block_duration
            sleep_time = next_tick - time.perf_counter()
            if sleep_time > 0:
                self._mixer_stop.wait(sleep_time)
                if self._mixer_stop.is_set():
                    break
            elif sleep_time < -0.25:
                # Re-anchor clock after system suspend / extreme scheduling stall
                next_tick = time.perf_counter()

            # Pull exactly `block_frames` from each stereo stream (zero-padded if silent/starved)
            raw_mic = self._mic_buffer.pop(block_frames, pad_silence=True)
            raw_sys = self._sys_buffer.pop(block_frames, pad_silence=True)

            with self._lock:
                mic_gain = self._config.mic_gain_db
                sys_gain = self._config.system_gain_db
                mic_muted = self._config.mic_muted
                sys_muted = self._config.system_muted
                limiter_on = self._config.limiter_enabled
                state = self._state
                writer = self._writer

            out1_mic = apply_gain(raw_mic, mic_gain, muted=mic_muted)
            out2_sys = apply_gain(raw_sys, sys_gain, muted=sys_muted)
            out3_comb = mix_stereo(out1_mic, out2_sys, limiter_enabled=limiter_on)

            mic_lvl = compute_stereo_levels(out1_mic)
            sys_lvl = compute_stereo_levels(out2_sys)
            comb_lvl = compute_stereo_levels(out3_comb)

            with self._lock:
                self._mic_level = mic_lvl
                self._sys_level = sys_lvl
                self._comb_level = comb_lvl

                if (
                    state is EngineState.RECORDING
                    and self._state is EngineState.RECORDING
                    and writer is not None
                    and self._writer is writer
                ):
                    try:
                        writer.write_block(out1_mic, out2_sys, out3_comb)
                        self._recorded_frames = writer.total_frames
                    except Exception as exc:
                        logger.exception("Disk write error during recording")
                        self._last_error = f"Write error: {exc}"
                        try:
                            writer.close()
                        except Exception:
                            pass
                        self._writer = None
                        self._state = EngineState.MONITORING

    def shutdown(self) -> None:
        """Stop all activity and release the audio backend."""
        with self._lifecycle_lock:
            self.stop_monitoring()
            self._backend.close()
