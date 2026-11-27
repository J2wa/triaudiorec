"""Exercise the Qt recording controls with simulated audio devices."""

import time

import soundfile as sf
from PySide6.QtWidgets import QApplication, QMessageBox

from tritrack.backends.simulated import SimulatedBackend
from tritrack.config import BitDepth, OutputFormat, RecorderConfig
from tritrack.engine import EngineState, RecordingEngine
from tritrack.ui.main_window import MainWindow


def test_window_loads_settings_and_records_using_the_selected_format(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _parent, _title, message: errors.append(message))
    app = QApplication.instance() or QApplication([])
    config = RecorderConfig(
        output_dir=str(tmp_path),
        session_prefix="studio",
        sample_rate=96000,
        output_format=OutputFormat.BOTH,
        bit_depth=BitDepth.FLOAT_32,
        mic_gain_db=-5.0,
        system_gain_db=7.0,
        limiter_enabled=False,
    )
    engine = RecordingEngine(SimulatedBackend(), config)
    window = MainWindow(engine)
    try:
        window.show()
        app.processEvents()
        assert engine.state is EngineState.MONITORING
        assert "studio_" in window._mic_file_preview.text()
        assert window._sr_combo.currentData() == 96000
        assert window._format_combo.currentData() == OutputFormat.BOTH.value
        assert window._bitdepth_combo.currentData() == BitDepth.FLOAT_32.value
        assert window._mic_gain_slider.value() == -50
        assert window._sys_gain_slider.value() == 70
        assert not window._limiter_cb.isChecked()

        previous_mixer = engine._mixer_thread
        assert previous_mixer is not None
        window._sr_combo.setCurrentIndex(window._sr_combo.findData(44100))
        assert engine.config.sample_rate == 44100
        assert previous_mixer is not engine._mixer_thread
        assert not previous_mixer.is_alive()

        window._record_btn.click()
        assert not errors, errors
        assert engine.state is EngineState.RECORDING
        deadline = time.monotonic() + 2
        while engine.get_snapshot().elapsed_seconds < 0.06 and time.monotonic() < deadline:
            time.sleep(0.01)
        window._pause_btn.click()
        assert engine.state is EngineState.PAUSED
        window._pause_btn.click()
        assert engine.state is EngineState.RECORDING
        window._stop_btn.click()

        assert engine.state is EngineState.MONITORING
        assert window._outputs_table.rowCount() == 6
        assert RecorderConfig.load().output_format is OutputFormat.BOTH
        wav = [sf.info(path) for path in tmp_path.glob("studio_*.wav")]
        flac = [sf.info(path) for path in tmp_path.glob("studio_*.flac")]
        assert len(wav) == len(flac) == 3
        assert all(info.subtype == "FLOAT" for info in wav)
        assert all(info.subtype == "PCM_24" for info in flac)
        assert all(info.samplerate == 44100 and info.channels == 2 for info in wav + flac)
        assert {info.frames for info in wav + flac} == {wav[0].frames}
        assert wav[0].frames > 0
    finally:
        window.close()
