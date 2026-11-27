"""Deterministic stereo audio simulator backend for testing and non-Windows preview."""

from __future__ import annotations

import threading
import time
from typing import List

import numpy as np

from .base import ActiveStream, AudioBackend, AudioChunkCallback, AudioDeviceInfo


class _SimulatedActiveStream(ActiveStream):
    """Background producer generating realistic stereo test signals at real-time cadence."""

    def __init__(
        self,
        sample_rate: int,
        channels: int,
        mode: str,
        callback: AudioChunkCallback,
        dropout_every_n_blocks: int = 0,
    ) -> None:
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._mode = mode
        self._callback = callback
        self._dropout_every = int(dropout_every_n_blocks)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def _synthesize(self, start_sample: int, num_frames: int) -> np.ndarray:
        t = (np.arange(num_frames, dtype=np.float64) + start_sample) / float(self._sample_rate)
        if self._mode == "mic":
            # Warm vocal-like harmonic cadence (440 Hz + 880 Hz with gentle amplitude modulation)
            env = 0.25 * (0.65 + 0.35 * np.sin(2.0 * np.pi * 1.5 * t))
            sig = env * (0.75 * np.sin(2.0 * np.pi * 440.0 * t) + 0.25 * np.sin(2.0 * np.pi * 880.0 * t))
            if self._channels == 1:
                return sig[:, np.newaxis].astype(np.float32)
            # Slight natural stereo room width
            left = sig
            right = sig * 0.94
            return np.column_stack((left, right)).astype(np.float32)

        # System audio: rich stereo synth chord with distinct L/R panning
        left = 0.22 * np.sin(2.0 * np.pi * 261.63 * t) + 0.14 * np.sin(2.0 * np.pi * 329.63 * t)
        right = 0.22 * np.sin(2.0 * np.pi * 392.00 * t) + 0.14 * np.sin(2.0 * np.pi * 523.25 * t)
        return np.column_stack((left, right)).astype(np.float32)

    def _run(self) -> None:
        block_frames = max(256, self._sample_rate // 50)  # 20 ms blocks
        block_duration = block_frames / float(self._sample_rate)
        sample_cursor = 0
        block_idx = 0
        next_wake = time.perf_counter()

        while not self._stop_event.is_set():
            block_idx += 1
            if self._dropout_every > 0 and (block_idx % self._dropout_every == 0):
                # Intentionally simulate a WASAPI silence gap
                pass
            else:
                chunk = self._synthesize(sample_cursor, block_frames)
                self._callback(chunk, self._sample_rate)
            sample_cursor += block_frames
            next_wake += block_duration
            sleep_for = next_wake - time.perf_counter()
            if sleep_for > 0:
                self._stop_event.wait(sleep_for)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


class SimulatedBackend(AudioBackend):
    """Simulated dual-source backend supporting mismatched sample rates & silence gaps."""

    def __init__(
        self,
        mic_rate: int = 48000,
        mic_channels: int = 2,
        system_rate: int = 48000,
        system_channels: int = 2,
        system_dropout_every_n: int = 0,
    ) -> None:
        self._mic_rate = int(mic_rate)
        self._mic_channels = int(mic_channels)
        self._system_rate = int(system_rate)
        self._system_channels = int(system_channels)
        self._system_dropout_every_n = int(system_dropout_every_n)

    @property
    def backend_name(self) -> str:
        return "Simulated Studio Devices (Demo / Test Mode)"

    def list_microphones(self) -> List[AudioDeviceInfo]:
        return [
            AudioDeviceInfo(
                device_id=101,
                name="Studio USB Microphone (Simulated)",
                sample_rate=self._mic_rate,
                channels=self._mic_channels,
                is_loopback=False,
                is_default=True,
                host_api="Simulated",
            ),
            AudioDeviceInfo(
                device_id=102,
                name="Headset Mono Microphone (Simulated 44.1k)",
                sample_rate=44100,
                channels=1,
                is_loopback=False,
                is_default=False,
                host_api="Simulated",
            ),
        ]

    def list_system_loopbacks(self) -> List[AudioDeviceInfo]:
        return [
            AudioDeviceInfo(
                device_id=201,
                name="Speakers (High Definition Audio) [Loopback]",
                sample_rate=self._system_rate,
                channels=self._system_channels,
                is_loopback=True,
                is_default=True,
                host_api="Simulated Loopback",
            ),
            AudioDeviceInfo(
                device_id=202,
                name="Studio Headphones (DAC 96k) [Loopback]",
                sample_rate=96000,
                channels=2,
                is_loopback=True,
                is_default=False,
                host_api="Simulated Loopback",
            ),
        ]

    def open_microphone_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        sr = 44100 if device_id == 102 else self._mic_rate
        ch = 1 if device_id == 102 else self._mic_channels
        return _SimulatedActiveStream(
            sample_rate=sr,
            channels=ch,
            mode="mic",
            callback=callback,
        )

    def open_system_loopback_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        sr = 96000 if device_id == 202 else self._system_rate
        ch = 2 if device_id == 202 else self._system_channels
        return _SimulatedActiveStream(
            sample_rate=sr,
            channels=ch,
            mode="system",
            callback=callback,
            dropout_every_n_blocks=self._system_dropout_every_n,
        )
