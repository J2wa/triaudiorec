"""Regression tests for compact exports, gain, and source preservation."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tritrack.converter import CONVERSION_PRESETS, ConversionPreset, convert_recording


@pytest.mark.parametrize("preset", [item for item in CONVERSION_PRESETS if item.format == "MP3"])
def test_mp3_presets_shrink_a_4608_kbps_recording(tmp_path: Path, preset: ConversionPreset) -> None:
    source = tmp_path / "hi-res.wav"
    seconds = 4
    source_rate = 96000
    time = np.arange(seconds * source_rate) / source_rate
    audio = np.column_stack((0.2 * np.sin(880 * np.pi * time), 0.1 * np.sin(660 * np.pi * time)))
    sf.write(source, audio, source_rate, subtype="PCM_24")
    original = source.read_bytes()

    output = convert_recording(source, preset)

    info = sf.info(output)
    assert info.format == "MP3"
    assert info.channels == 2
    assert info.samplerate == 48000
    assert info.duration == pytest.approx(seconds, abs=0.05)
    # A tag and encoder padding increase the measured container bitrate slightly.
    actual_kbps = output.stat().st_size * 8 / seconds / 1000
    assert actual_kbps == pytest.approx(preset.bitrate_kbps, rel=0.025)
    assert source.read_bytes() == original


def test_gain_resamples_mono_and_limits_peaks_without_overwriting(tmp_path: Path) -> None:
    source = tmp_path / "mic.wav"
    source_rate = 88200
    time = np.arange(source_rate) / source_rate
    audio = 0.1 * np.sin(880 * np.pi * time)
    audio[source_rate // 2:] *= 8
    sf.write(source, audio, source_rate, subtype="PCM_24")
    original = source.read_bytes()
    wav_preset = next(item for item in CONVERSION_PRESETS if item.sample_rate == 44100)
    flac_preset = next(item for item in CONVERSION_PRESETS if item.format == "FLAC")

    boosted = convert_recording(source, wav_preset, gain_db=6)
    second = convert_recording(source, wav_preset)
    lossless = convert_recording(source, flac_preset)

    assert boosted != second
    assert source.read_bytes() == original
    data, rate = sf.read(boosted)
    assert rate == 44100
    assert data.shape == (44100,)
    assert sf.info(boosted).subtype == "PCM_16"
    assert np.max(np.abs(data[:20000])) == pytest.approx(0.2, abs=0.005)
    assert 0.9 < np.max(np.abs(data[23000:])) < 1.0
    assert sf.info(lossless).samplerate == 88200
    assert sf.info(lossless).subtype == "PCM_24"
    np.testing.assert_array_equal(sf.read(lossless)[0], sf.read(source)[0])


def test_cancelled_conversion_cleans_up_partial_copy(tmp_path: Path) -> None:
    source = tmp_path / "recording.flac"
    sf.write(source, np.zeros((150000, 2)), 48000, subtype="PCM_24")
    checks = iter((False, False, True))

    with pytest.raises(InterruptedError):
        convert_recording(source, CONVERSION_PRESETS[0], cancelled=lambda: next(checks))

    assert list(tmp_path.iterdir()) == [source]
