"""Abstract audio capture backend interface for TriTrack Studio."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List

import numpy as np

# Callback signature: (audio_frames: np.ndarray [N, ch] float32, sample_rate: int)
AudioChunkCallback = Callable[[np.ndarray, int], None]


@dataclass(frozen=True)
class AudioDeviceInfo:
    """Description of an audio input or WASAPI loopback endpoint."""

    device_id: int
    name: str
    sample_rate: int
    channels: int
    is_loopback: bool
    is_default: bool = False
    host_api: str = "WASAPI"

    @property
    def display_label(self) -> str:
        tag = " [Default]" if self.is_default else ""
        ch_str = f"{self.channels}ch" if self.channels != 2 else "Stereo"
        return f"{self.name} ({self.sample_rate // 1000} kHz, {ch_str}){tag}"


class ActiveStream(ABC):
    """Handle to a running audio capture stream."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Native capture sample rate in Hz."""

    @property
    @abstractmethod
    def channels(self) -> int:
        """Native capture channel count."""

    @abstractmethod
    def stop(self) -> None:
        """Stop and release all stream resources cleanly."""


class AudioBackend(ABC):
    """Abstract interface for enumerating and capturing mic + system loopback audio."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable backend name shown in the UI."""

    @abstractmethod
    def list_microphones(self) -> List[AudioDeviceInfo]:
        """List available microphone input devices."""

    @abstractmethod
    def list_system_loopbacks(self) -> List[AudioDeviceInfo]:
        """List available system audio loopback devices."""

    @abstractmethod
    def open_microphone_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        """Open a live microphone capture stream invoking `callback` with float32 frames."""

    @abstractmethod
    def open_system_loopback_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        """Open a live system audio loopback stream invoking `callback` with float32 frames."""

    def close(self) -> None:
        """Release any global backend resources."""
