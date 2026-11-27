"""Unit tests for TriTrack Studio stereo DSP pipeline."""

from __future__ import annotations

import numpy as np

from tritrack.dsp import (
    MIN_DB,
    StereoRingBuffer,
    StreamingResampler,
    apply_gain,
    compute_stereo_levels,
    db_to_linear,
    ensure_stereo,
    linear_to_db,
    mix_stereo,
    soft_limit_stereo,
)


def test_ensure_stereo_formats() -> None:
    mono_1d = np.linspace(-0.5, 0.5, 128, dtype=np.float32)
    s1 = ensure_stereo(mono_1d)
    assert s1.shape == (128, 2)
    assert np.allclose(s1[:, 0], mono_1d)
    assert np.allclose(s1[:, 1], mono_1d)

    mono_2d = mono_1d[:, np.newaxis]
    s2 = ensure_stereo(mono_2d)
    assert s2.shape == (128, 2)
    assert np.allclose(s2[:, 0], s2[:, 1])

    stereo = np.column_stack((mono_1d, -mono_1d)).astype(np.float32)
    s3 = ensure_stereo(stereo)
    assert s3.shape == (128, 2)
    assert np.allclose(s3, stereo)

    # 5.1 surround fold-down preserves stereo separation without clipping
    surround_51 = np.zeros((100, 6), dtype=np.float32)
    surround_51[:, 0] = 0.8  # FL
    surround_51[:, 2] = 0.4  # Center
    s51 = ensure_stereo(surround_51)
    assert s51.shape == (100, 2)
    assert float(np.max(np.abs(s51))) <= 1.0
    assert float(np.mean(s51[:, 0])) > float(np.mean(s51[:, 1]))


def test_streaming_resampler_passthrough() -> None:
    resampler = StreamingResampler(48000, 48000)
    data = np.random.default_rng(42).uniform(-0.5, 0.5, size=(960, 2)).astype(np.float32)
    out = resampler.process(data)
    assert out.shape == (960, 2)
    assert np.array_equal(out, data)


def test_streaming_resampler_44100_to_48000_continuity() -> None:
    src_sr = 44100
    dst_sr = 48000
    duration = 0.5
    n_src = int(src_sr * duration)
    t = np.arange(n_src, dtype=np.float64) / src_sr
    left = (0.5 * np.sin(2.0 * np.pi * 1000.0 * t)).astype(np.float32)
    right = (0.5 * np.sin(2.0 * np.pi * 500.0 * t)).astype(np.float32)
    stereo = np.column_stack((left, right))

    resampler = StreamingResampler(src_sr, dst_sr)
    chunks = []
    block = 882  # 20 ms at 44.1 kHz
    for i in range(0, n_src, block):
        out = resampler.process(stereo[i : i + block])
        if out.shape[0] > 0:
            chunks.append(out)
    tail = resampler.flush()
    if tail.shape[0] > 0:
        chunks.append(tail)

    full = np.vstack(chunks)
    expected_len = int(round(n_src * (dst_sr / src_sr)))
    assert abs(full.shape[0] - expected_len) <= 4
    assert full.shape[1] == 2

    # Check interior smoothness: no chunk-boundary clicks (1 kHz sine derivative is bounded)
    interior = full[500:-500, 0]
    max_step = float(np.max(np.abs(np.diff(interior))))
    theoretical_max_step = 0.5 * (2.0 * np.pi * 1000.0 / dst_sr)
    assert max_step < theoretical_max_step * 1.15


def test_soft_limiter_linear_below_threshold_and_bounds_peaks() -> None:
    quiet = np.full((256, 2), 0.5, dtype=np.float32)
    limited_quiet = soft_limit_stereo(quiet, threshold_db=-1.0, ceiling_db=-0.1)
    assert np.array_equal(quiet, limited_quiet)

    # Loud asymmetric stereo signal (L=1.8, R=0.9 -> ratio 2:1)
    loud = np.column_stack((np.full(256, 1.8), np.full(256, 0.9))).astype(np.float32)
    limited_loud = soft_limit_stereo(loud, threshold_db=-1.0, ceiling_db=-0.1)
    ceiling = db_to_linear(-0.1)
    assert float(np.max(np.abs(limited_loud))) <= ceiling + 1e-5
    # Stereo-linked limiting preserves exact 2:1 L/R imaging ratio
    ratio = float(limited_loud[0, 0] / limited_loud[0, 1])
    assert abs(ratio - 2.0) < 1e-4


def test_gain_mix_and_metering() -> None:
    sig = np.full((480, 2), 0.25, dtype=np.float32)
    boosted = apply_gain(sig, +6.0206)
    assert np.allclose(boosted, 0.5, atol=1e-3)

    muted = apply_gain(sig, 0.0, muted=True)
    assert np.all(muted == 0.0)

    combined = mix_stereo(sig, sig, limiter_enabled=True)
    assert np.allclose(combined, 0.5, atol=1e-5)

    lvl = compute_stereo_levels(combined)
    assert abs(lvl.left_peak_db - linear_to_db(0.5)) < 0.05
    assert not lvl.clipped

    silent_lvl = compute_stereo_levels(muted)
    assert silent_lvl.left_rms_db == MIN_DB


def test_stereo_ring_buffer_fifo_and_bounds() -> None:
    buf = StereoRingBuffer(max_frames=100)
    a = np.ones((60, 2), dtype=np.float32)
    b = np.full((60, 2), 2.0, dtype=np.float32)
    buf.push(a)
    buf.push(b)

    # Overflow trimmed oldest 20 frames from `a`, leaving 40 ones + 60 twos
    assert buf.available == 100
    assert buf.dropped_frames == 20

    first = buf.pop(50)
    assert first.shape == (50, 2)
    assert np.all(first[:40] == 1.0)
    assert np.all(first[40:] == 2.0)

    # Underrun pads exact zeros
    rest = buf.pop(80, pad_silence=True)
    assert rest.shape == (80, 2)
    assert np.all(rest[:50] == 2.0)
    assert np.all(rest[50:] == 0.0)
