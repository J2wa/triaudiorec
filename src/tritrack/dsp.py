"""High-fidelity stereo audio DSP: channel formatting, resampling, mixing, limiting, and metering."""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from math import gcd
from typing import Deque

import numpy as np
from scipy.signal import resample_poly

MIN_DB = -90.0
EPS = 1e-12


@dataclass(frozen=True)
class StereoLevel:
    """Instantaneous stereo level reading in dBFS."""

    left_rms_db: float = MIN_DB
    right_rms_db: float = MIN_DB
    left_peak_db: float = MIN_DB
    right_peak_db: float = MIN_DB
    clipped: bool = False


def db_to_linear(db: float) -> float:
    """Convert decibels to a linear amplitude multiplier."""
    if db <= MIN_DB:
        return 0.0
    return float(10.0 ** (db / 20.0))


def linear_to_db(value: float) -> float:
    """Convert a linear amplitude (0..1+) to dBFS, floored at MIN_DB."""
    if value <= EPS:
        return MIN_DB
    db = 20.0 * math.log10(float(value))
    return max(MIN_DB, db)


def ensure_stereo(samples: np.ndarray) -> np.ndarray:
    """Convert mono, stereo, or surround float arrays into contiguous float32 stereo (N, 2).

    - Mono (N,) or (N, 1): duplicated cleanly to both L and R channels.
    - Stereo (N, 2): preserved verbatim.
    - Multichannel (e.g. 5.1/7.1 Windows WASAPI endpoints): ITU-R BS.775 stereo fold-down
      preserving center and surround energy without clipping.
    """
    arr = np.asarray(samples, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float32)

    if arr.ndim == 1:
        return np.column_stack((arr, arr)).astype(np.float32, copy=False)

    channels = arr.shape[1]
    if channels == 2:
        return np.ascontiguousarray(arr, dtype=np.float32)

    if channels == 1:
        mono = arr[:, 0]
        return np.column_stack((mono, mono)).astype(np.float32, copy=False)

    if channels >= 6:
        # Standard Windows WAVEFORMATEXTENSIBLE order: FL, FR, FC, LFE, BL/SL, BR/SR, [SL, SR]
        inv_sqrt2 = np.float32(0.70710678)
        left = arr[:, 0] + inv_sqrt2 * arr[:, 2] + inv_sqrt2 * arr[:, 4]
        right = arr[:, 1] + inv_sqrt2 * arr[:, 2] + inv_sqrt2 * arr[:, 5]
        if channels >= 8:
            left = left + inv_sqrt2 * arr[:, 6]
            right = right + inv_sqrt2 * arr[:, 7]
        # Normalize fold-down gain so full-scale correlated signals do not clip
        norm = np.float32(1.0 / (1.0 + inv_sqrt2))
        return np.column_stack((left * norm, right * norm)).astype(np.float32, copy=False)

    # Generic N-channel fallback (e.g., 3 or 4 channels): fold even->L, odd->R
    left = np.mean(arr[:, 0::2], axis=1, dtype=np.float32)
    right = np.mean(arr[:, 1::2], axis=1, dtype=np.float32)
    return np.column_stack((left, right)).astype(np.float32, copy=False)


class StreamingResampler:
    """High-fidelity polyphase stereo resampler with phase-exact overlap-save continuity.

    Aligns both filter context padding and emitted block lengths to exact integer
    multiples of the rational decimation factor `down = source_rate // gcd(...)`.
    This guarantees zero fractional phase drift and bit-smooth chunk boundaries
    when resampling live audio streams (e.g., 44.1 kHz mic -> 48 kHz or 96 kHz master).
    """

    def __init__(self, source_rate: int, target_rate: int, min_overlap_frames: int = 64) -> None:
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Sample rates must be positive integers.")
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self._passthrough = self.source_rate == self.target_rate

        g = gcd(self.source_rate, self.target_rate)
        self._up = self.target_rate // g
        self._down = self.source_rate // g

        # Exact integer multiple of `_down` so polyphase start/end offsets are exact integers.
        pad_mult = max(1, math.ceil(min_overlap_frames / self._down))
        self._pad_mult = pad_mult
        self._pad_in = pad_mult * self._down
        self._pad_out = pad_mult * self._up

        self._prev_tail: np.ndarray = np.zeros((0, 2), dtype=np.float32)
        self._pending_in: np.ndarray = np.zeros((0, 2), dtype=np.float32)

    def reset(self) -> None:
        """Clear internal filter history."""
        self._prev_tail = np.zeros((0, 2), dtype=np.float32)
        self._pending_in = np.zeros((0, 2), dtype=np.float32)

    def process(self, stereo_chunk: np.ndarray) -> np.ndarray:
        """Resample a stereo float32 chunk `(N, 2)` to `target_rate`."""
        stereo = ensure_stereo(stereo_chunk)
        if stereo.shape[0] == 0:
            return stereo
        if self._passthrough:
            return stereo

        if self._pending_in.shape[0] > 0:
            work = np.vstack((self._pending_in, stereo))
        else:
            work = stereo

        # Need at least `self._down` frames to emit plus `self._pad_in` lookahead frames.
        available_for_emit = work.shape[0] - self._pad_in
        k_blocks = available_for_emit // self._down
        if k_blocks <= 0:
            self._pending_in = work
            return np.zeros((0, 2), dtype=np.float32)

        emit_in_count = k_blocks * self._down
        current_body = work[:emit_in_count]
        remaining = work[emit_in_count:]
        lookahead = remaining[: self._pad_in]

        if self._prev_tail.shape[0] == 0:
            left_pad = np.repeat(work[0:1], self._pad_in, axis=0)
        else:
            left_pad = self._prev_tail

        window = np.vstack((left_pad, current_body, lookahead))
        resampled = resample_poly(window, self._up, self._down, axis=0).astype(
            np.float32, copy=False
        )

        start_idx = self._pad_out
        out_len = k_blocks * self._up
        emitted = np.ascontiguousarray(
            resampled[start_idx : start_idx + out_len], dtype=np.float32
        )

        combined_past = np.vstack((left_pad, current_body))
        self._prev_tail = combined_past[-self._pad_in :].copy()
        self._pending_in = remaining.copy()
        return emitted

    def flush(self) -> np.ndarray:
        """Flush remaining buffered lookahead frames at end of stream."""
        if self._passthrough or self._pending_in.shape[0] == 0:
            self.reset()
            return np.zeros((0, 2), dtype=np.float32)

        left_pad = (
            self._prev_tail
            if self._prev_tail.shape[0] > 0
            else np.repeat(self._pending_in[0:1], self._pad_in, axis=0)
        )
        right_pad = np.repeat(self._pending_in[-1:], self._pad_in, axis=0)
        window = np.vstack((left_pad, self._pending_in, right_pad))
        resampled = resample_poly(window, self._up, self._down, axis=0).astype(
            np.float32, copy=False
        )

        start_idx = self._pad_out
        out_len = int(round(self._pending_in.shape[0] * (self.target_rate / self.source_rate)))
        end_idx = min(start_idx + out_len, resampled.shape[0])
        emitted = np.ascontiguousarray(resampled[start_idx:end_idx], dtype=np.float32)
        self.reset()
        return emitted


def apply_gain(stereo: np.ndarray, gain_db: float, muted: bool = False) -> np.ndarray:
    """Apply dB gain or mute cleanly to a stereo float32 block."""
    if stereo.shape[0] == 0:
        return stereo
    if muted or gain_db <= MIN_DB:
        return np.zeros_like(stereo, dtype=np.float32)
    if abs(gain_db) < 1e-6:
        return stereo.copy()
    gain = np.float32(db_to_linear(gain_db))
    return (stereo * gain).astype(np.float32, copy=False)


def soft_limit_stereo(
    stereo: np.ndarray,
    threshold_db: float = -1.0,
    ceiling_db: float = -0.1,
) -> np.ndarray:
    """Transparent stereo-linked soft-knee peak limiter.

    Signals below `threshold_db` pass through bit-identically untouched (100% linear).
    Peaks exceeding `threshold_db` are smoothly compressed asymptotically toward
    `ceiling_db` using stereo-linked peak gain reduction to preserve stereo imaging.
    """
    if stereo.shape[0] == 0:
        return stereo

    thresh = db_to_linear(threshold_db)
    ceiling = db_to_linear(ceiling_db)
    headroom = max(ceiling - thresh, 1e-5)

    # Stereo-linked instantaneous magnitude preserves L/R balance during limiting.
    peak_env = np.max(np.abs(stereo), axis=1)
    over_mask = peak_env > thresh
    if not np.any(over_mask):
        return stereo

    out = stereo.copy()
    over_vals = peak_env[over_mask]
    excess = over_vals - thresh
    compressed = thresh + headroom * np.tanh(excess / headroom)
    scale = (compressed / over_vals).astype(np.float32)
    out[over_mask] *= scale[:, np.newaxis]
    return out


def mix_stereo(
    mic_stereo: np.ndarray,
    system_stereo: np.ndarray,
    limiter_enabled: bool = True,
) -> np.ndarray:
    """Combine Microphone and System stereo tracks into Output 3."""
    if mic_stereo.shape != system_stereo.shape:
        raise ValueError(
            f"Stereo mix shape mismatch: mic={mic_stereo.shape} vs system={system_stereo.shape}"
        )
    combined = (mic_stereo + system_stereo).astype(np.float32, copy=False)
    if limiter_enabled:
        combined = soft_limit_stereo(combined)
    return np.clip(combined, -1.0, 1.0, out=combined)


def compute_stereo_levels(stereo: np.ndarray) -> StereoLevel:
    """Compute left and right RMS/Peak dBFS levels and clip state for a stereo block."""
    if stereo.shape[0] == 0:
        return StereoLevel()

    left = stereo[:, 0]
    right = stereo[:, 1]

    l_peak = float(np.max(np.abs(left)))
    r_peak = float(np.max(np.abs(right)))
    l_rms = float(np.sqrt(np.mean(left.astype(np.float64) ** 2)))
    r_rms = float(np.sqrt(np.mean(right.astype(np.float64) ** 2)))

    clipped = l_peak >= 0.999 or r_peak >= 0.999
    return StereoLevel(
        left_rms_db=linear_to_db(l_rms),
        right_rms_db=linear_to_db(r_rms),
        left_peak_db=linear_to_db(l_peak),
        right_peak_db=linear_to_db(r_peak),
        clipped=clipped,
    )


class StereoRingBuffer:
    """Thread-safe FIFO queue of stereo float32 frames with bounded latency."""

    def __init__(self, max_frames: int) -> None:
        self._max_frames = int(max_frames)
        self._chunks: Deque[np.ndarray] = deque()
        self._total_frames: int = 0
        self._lock = threading.Lock()
        self._dropped_frames: int = 0

    @property
    def available(self) -> int:
        with self._lock:
            return self._total_frames

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._total_frames = 0

    def push(self, stereo: np.ndarray) -> None:
        """Append stereo `(N, 2)` float32 frames, trimming oldest excess if overflowing."""
        if stereo.shape[0] == 0:
            return
        chunk = np.ascontiguousarray(stereo, dtype=np.float32)
        with self._lock:
            self._chunks.append(chunk)
            self._total_frames += chunk.shape[0]
            # Bound maximum queue latency to avoid drift build-up
            while self._total_frames > self._max_frames and self._chunks:
                excess = self._total_frames - self._max_frames
                head = self._chunks[0]
                if head.shape[0] <= excess:
                    self._chunks.popleft()
                    self._total_frames -= head.shape[0]
                    self._dropped_frames += head.shape[0]
                else:
                    self._chunks[0] = head[excess:]
                    self._total_frames -= excess
                    self._dropped_frames += excess

    def pop(self, num_frames: int, pad_silence: bool = True) -> np.ndarray:
        """Pop up to `num_frames` stereo frames; optionally zero-pad on underrun."""
        with self._lock:
            if self._total_frames == 0:
                if pad_silence:
                    return np.zeros((num_frames, 2), dtype=np.float32)
                return np.zeros((0, 2), dtype=np.float32)

            take = min(num_frames, self._total_frames)
            parts = []
            remaining = take
            while remaining > 0 and self._chunks:
                head = self._chunks[0]
                if head.shape[0] <= remaining:
                    parts.append(self._chunks.popleft())
                    remaining -= head.shape[0]
                    self._total_frames -= head.shape[0]
                else:
                    parts.append(head[:remaining])
                    self._chunks[0] = head[remaining:]
                    self._total_frames -= remaining
                    remaining = 0

        out = np.vstack(parts) if len(parts) > 1 else parts[0]
        if pad_silence and out.shape[0] < num_frames:
            pad = np.zeros((num_frames - out.shape[0], 2), dtype=np.float32)
            out = np.vstack((out, pad))
        return np.ascontiguousarray(out, dtype=np.float32)
