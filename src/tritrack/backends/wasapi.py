"""Native Windows WASAPI + WASAPI Loopback audio backend powered by PyAudioWPatch."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import numpy as np

from .base import ActiveStream, AudioBackend, AudioChunkCallback, AudioDeviceInfo

logger = logging.getLogger(__name__)


class _WasapiActiveStream(ActiveStream):
    """Wraps a PyAudioWPatch input/loopback stream plus an optional silent keepalive stream."""

    def __init__(
        self,
        capture_stream: Any,
        sample_rate: int,
        channels: int,
        keepalive_stream: Optional[Any] = None,
    ) -> None:
        self._capture_stream = capture_stream
        self._keepalive_stream = keepalive_stream
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._stopped = False

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for stream in (self._capture_stream, self._keepalive_stream):
            if stream is None:
                continue
            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception:
                logger.debug("Ignoring error stopping WASAPI stream", exc_info=True)
            try:
                stream.close()
            except Exception:
                logger.debug("Ignoring error closing WASAPI stream", exc_info=True)


class WasapiBackend(AudioBackend):
    """Windows native WASAPI microphone + WASAPI loopback system audio backend.

    Key reliability features for studio-grade Windows capture:
    - Enumerates native WASAPI microphones and every active WASAPI loopback endpoint.
    - Opens loopback streams at the endpoint's exact native channel layout and sample rate
      (preventing Windows WASAPI shared-mode channel mismatch errors on 5.1/7.1 devices).
    - Runs an inaudible zero-filled WASAPI silent keepalive render stream on the target
      playback device during loopback capture so Windows continuously clocks loopback
      packets even during total system silence (zero audio drift or pauses).
    """

    def __init__(self) -> None:
        try:
            import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "PyAudioWPatch is required for native Windows WASAPI capture. "
                "Install it with: pip install PyAudioWPatch"
            ) from exc

        self._pyaudio_mod = pyaudio
        self._pa = pyaudio.PyAudio()
        try:
            self._wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:
            self._pa.terminate()
            raise RuntimeError(
                "Windows WASAPI audio host API is unavailable on this machine."
            ) from exc

    @property
    def backend_name(self) -> str:
        return "Windows WASAPI (Native Loopback)"

    def _default_output_name(self) -> str:
        try:
            default_out_idx = int(self._wasapi_info["defaultOutputDevice"])
            info = self._pa.get_device_info_by_index(default_out_idx)
            return str(info.get("name", ""))
        except Exception:
            return ""

    def list_microphones(self) -> List[AudioDeviceInfo]:
        wasapi_idx = int(self._wasapi_info["index"])
        default_in_idx = int(self._wasapi_info.get("defaultInputDevice", -1))
        devices: List[AudioDeviceInfo] = []

        for idx in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(idx)
            if int(dev.get("hostApi", -1)) != wasapi_idx:
                continue
            if dev.get("isLoopbackDevice", False):
                continue
            max_in = int(dev.get("maxInputChannels", 0))
            if max_in <= 0:
                continue
            devices.append(
                AudioDeviceInfo(
                    device_id=int(dev["index"]),
                    name=str(dev["name"]),
                    sample_rate=int(round(float(dev.get("defaultSampleRate", 48000)))),
                    channels=min(max_in, 2),
                    is_loopback=False,
                    is_default=(int(dev["index"]) == default_in_idx),
                    host_api="WASAPI",
                )
            )
        return devices

    def list_system_loopbacks(self) -> List[AudioDeviceInfo]:
        default_out_name = self._default_output_name()
        devices: List[AudioDeviceInfo] = []

        for loopback in self._pa.get_loopback_device_info_generator():
            name = str(loopback["name"])
            is_default = bool(default_out_name and default_out_name in name)
            devices.append(
                AudioDeviceInfo(
                    device_id=int(loopback["index"]),
                    name=name,
                    sample_rate=int(round(float(loopback.get("defaultSampleRate", 48000)))),
                    channels=max(1, int(loopback.get("maxInputChannels", 2))),
                    is_loopback=True,
                    is_default=is_default,
                    host_api="WASAPI Loopback",
                )
            )
        return devices

    def open_microphone_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        dev = self._pa.get_device_info_by_index(int(device_id))
        native_sr = int(round(float(dev.get("defaultSampleRate", 48000))))
        max_in = int(dev.get("maxInputChannels", 1))
        # Prefer stereo when supported by the microphone; otherwise capture mono and upmix in DSP
        channels = 2 if max_in >= 2 else 1
        frames_per_buffer = max(256, native_sr // 50)

        def _pa_callback(in_data: bytes, frame_count: int, time_info: Any, status: int) -> tuple:
            if in_data:
                arr = np.frombuffer(in_data, dtype=np.float32).reshape(-1, channels).copy()
                callback(arr, native_sr)
            return (None, self._pyaudio_mod.paContinue)

        stream = self._pa.open(
            format=self._pyaudio_mod.paFloat32,
            channels=channels,
            rate=native_sr,
            input=True,
            input_device_index=int(device_id),
            frames_per_buffer=frames_per_buffer,
            stream_callback=_pa_callback,
        )
        stream.start_stream()
        return _WasapiActiveStream(capture_stream=stream, sample_rate=native_sr, channels=channels)

    def _open_silent_keepalive(self, loopback_dev: dict) -> Optional[Any]:
        """Open a zero-amplitude WASAPI output stream to keep loopback clocking during silence."""
        wasapi_idx = int(self._wasapi_info["index"])
        loopback_name = str(loopback_dev.get("name", ""))
        base_name = loopback_name.replace(" [Loopback]", "").strip()

        target_out_dev = None
        for idx in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(idx)
            if int(dev.get("hostApi", -1)) != wasapi_idx:
                continue
            if dev.get("isLoopbackDevice", False):
                continue
            if int(dev.get("maxOutputChannels", 0)) <= 0:
                continue
            if str(dev.get("name", "")).strip() == base_name:
                target_out_dev = dev
                break

        if target_out_dev is None:
            return None

        try:
            out_sr = int(round(float(target_out_dev.get("defaultSampleRate", 48000))))
            out_ch = max(1, min(int(target_out_dev.get("maxOutputChannels", 2)), 2))
            frames_per_buffer = max(256, out_sr // 25)
            zero_bytes = np.zeros((frames_per_buffer, out_ch), dtype=np.float32).tobytes()

            def _silence_cb(in_data: Any, frame_count: int, time_info: Any, status: int) -> tuple:
                if frame_count == frames_per_buffer:
                    return (zero_bytes, self._pyaudio_mod.paContinue)
                buf = np.zeros((frame_count, out_ch), dtype=np.float32).tobytes()
                return (buf, self._pyaudio_mod.paContinue)

            keepalive = self._pa.open(
                format=self._pyaudio_mod.paFloat32,
                channels=out_ch,
                rate=out_sr,
                output=True,
                output_device_index=int(target_out_dev["index"]),
                frames_per_buffer=frames_per_buffer,
                stream_callback=_silence_cb,
            )
            keepalive.start_stream()
            return keepalive
        except Exception:
            logger.debug(
                "Could not open silent keepalive stream for %s; falling back to clock padding.",
                loopback_name,
                exc_info=True,
            )
            return None

    def open_system_loopback_stream(
        self,
        device_id: int,
        callback: AudioChunkCallback,
    ) -> ActiveStream:
        dev = self._pa.get_device_info_by_index(int(device_id))
        native_sr = int(round(float(dev.get("defaultSampleRate", 48000))))
        # WASAPI loopback in shared mode must be opened at the endpoint's exact native channels
        native_ch = max(1, int(dev.get("maxInputChannels", 2)))
        frames_per_buffer = max(256, native_sr // 50)

        keepalive_stream = self._open_silent_keepalive(dev)

        def _pa_callback(in_data: bytes, frame_count: int, time_info: Any, status: int) -> tuple:
            if in_data:
                arr = np.frombuffer(in_data, dtype=np.float32).reshape(-1, native_ch).copy()
                callback(arr, native_sr)
            return (None, self._pyaudio_mod.paContinue)

        try:
            stream = self._pa.open(
                format=self._pyaudio_mod.paFloat32,
                channels=native_ch,
                rate=native_sr,
                input=True,
                input_device_index=int(device_id),
                frames_per_buffer=frames_per_buffer,
                stream_callback=_pa_callback,
            )
            stream.start_stream()
        except Exception:
            if keepalive_stream is not None:
                try:
                    keepalive_stream.stop_stream()
                    keepalive_stream.close()
                except Exception:
                    pass
            raise

        return _WasapiActiveStream(
            capture_stream=stream,
            sample_rate=native_sr,
            channels=native_ch,
            keepalive_stream=keepalive_stream,
        )

    def close(self) -> None:
        try:
            self._pa.terminate()
        except Exception:
            pass
