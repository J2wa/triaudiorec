"""Audio backend factory selecting native Windows WASAPI or simulated test mode."""

from __future__ import annotations

import sys

from .base import ActiveStream, AudioBackend, AudioChunkCallback, AudioDeviceInfo
from .simulated import SimulatedBackend
from .wasapi import WasapiBackend


def create_backend(force_simulated: bool = False) -> AudioBackend:
    """Instantiate the native Windows WASAPI backend (or SimulatedBackend when requested)."""
    if force_simulated:
        return SimulatedBackend()
    if sys.platform == "win32":
        return WasapiBackend()
    return SimulatedBackend()


__all__ = [
    "ActiveStream",
    "AudioBackend",
    "AudioChunkCallback",
    "AudioDeviceInfo",
    "SimulatedBackend",
    "WasapiBackend",
    "create_backend",
]
