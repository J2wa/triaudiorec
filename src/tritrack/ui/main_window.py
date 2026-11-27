"""Main PySide6 desktop GUI window for TriTrack Studio."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..backends.base import AudioDeviceInfo
from ..config import BitDepth, OutputFormat, RecorderConfig
from ..engine import EngineState, RecordingEngine
from ..writer import RecordingSummary
from .converter_dialog import ConverterDialog
from .meters import StereoMeterWidget
from .theme import STUDIO_QSS


def _format_duration(seconds: float) -> str:
    total_tenths = int(round(max(0.0, seconds) * 10))
    tenths = total_tenths % 10
    total_secs = total_tenths // 10
    hrs = total_secs // 3600
    mins = (total_secs % 3600) // 60
    secs = total_secs % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{tenths}"


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def _open_folder_in_explorer(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


class MainWindow(QMainWindow):
    """TriTrack Studio primary desktop window with live 3-output stereo controls."""

    def __init__(self, engine: RecordingEngine) -> None:
        super().__init__()
        self._engine = engine
        self._config: RecorderConfig = engine.config
        self._mic_devices: List[AudioDeviceInfo] = []
        self._sys_devices: List[AudioDeviceInfo] = []
        self._populating_devices = False
        self._loading_config = True

        self.setWindowTitle(f"{__app_name__} v{__version__} — 3-Output Hi-Fi Stereo Recorder")
        self.setMinimumSize(1020, 680)
        self.resize(1120, 740)
        self.setStyleSheet(STUDIO_QSS)

        self._build_ui()
        self._load_config_into_widgets()
        self._loading_config = False
        self._on_mixer_changed()
        self._refresh_devices()

        # 30 FPS UI telemetry timer for smooth stereo metering and recording clock
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(33)
        self._ui_timer.timeout.connect(self._poll_engine)
        self._ui_timer.start()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        root.addWidget(self._build_top_bar())
        root.addLayout(self._build_channel_strips())
        root.addWidget(self._build_settings_panel())
        root.addWidget(self._build_recent_outputs_panel(), stretch=1)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        title = QLabel(__app_name__)
        title.setObjectName("AppTitle")
        title_row.addWidget(title)

        backend_badge = QLabel(self._engine.backend_name)
        backend_badge.setObjectName("BackendBadge")
        title_row.addWidget(backend_badge)
        title_row.addStretch()

        subtitle = QLabel(
            "3-Output Stereo Recorder  •  Output 1: Mic   |   Output 2: System Audio   |   Output 3: Combined"
        )
        subtitle.setObjectName("MutedLabel")

        title_col.addLayout(title_row)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, stretch=1)

        self._status_pill = QLabel("MONITORING")
        self._status_pill.setObjectName("StatusMonitoring")
        layout.addWidget(self._status_pill)

        self._timer_label = QLabel("00:00:00.0")
        self._timer_label.setObjectName("TimerDisplay")
        layout.addWidget(self._timer_label)

        self._record_btn = QPushButton("●  Record 3 Outputs")
        self._record_btn.setObjectName("RecordButton")
        self._record_btn.clicked.connect(self._on_record_clicked)
        layout.addWidget(self._record_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setObjectName("PauseButton")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("■  Stop & Save")
        self._stop_btn.setObjectName("StopButton")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._stop_btn)

        return bar

    def _build_channel_strips(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        # Output 1: Microphone
        mic_card = QFrame()
        mic_card.setObjectName("ChannelCard")
        mic_lay = QVBoxLayout(mic_card)
        mic_lay.setContentsMargins(14, 14, 14, 14)
        mic_lay.setSpacing(10)

        tag1 = QLabel("OUTPUT 1  •  STEREO TRACK")
        tag1.setObjectName("CardTag")
        hdr1 = QLabel("Microphone Input")
        hdr1.setObjectName("CardHeader")
        mic_lay.addWidget(tag1)
        mic_lay.addWidget(hdr1)

        dev1_row = QHBoxLayout()
        self._mic_combo = QComboBox()
        self._mic_combo.currentIndexChanged.connect(self._on_device_selection_changed)
        dev1_row.addWidget(self._mic_combo, stretch=1)

        refresh_btn1 = QPushButton("↻")
        refresh_btn1.setFixedWidth(34)
        refresh_btn1.setToolTip("Refresh Windows WASAPI audio devices")
        refresh_btn1.clicked.connect(self._refresh_devices)
        dev1_row.addWidget(refresh_btn1)
        mic_lay.addLayout(dev1_row)

        gain1_row = QHBoxLayout()
        gain1_lbl = QLabel("Gain")
        gain1_lbl.setObjectName("MutedLabel")
        self._mic_gain_val = QLabel("+0.0 dB")
        self._mic_gain_val.setObjectName("MutedLabel")
        self._mic_mute_btn = QPushButton("Mute")
        self._mic_mute_btn.setObjectName("MuteButton")
        self._mic_mute_btn.setCheckable(True)
        self._mic_mute_btn.toggled.connect(self._on_mixer_changed)
        gain1_row.addWidget(gain1_lbl)
        gain1_row.addStretch()
        gain1_row.addWidget(self._mic_gain_val)
        gain1_row.addWidget(self._mic_mute_btn)
        mic_lay.addLayout(gain1_row)

        self._mic_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_gain_slider.setRange(-240, 180)  # tenths of dB: -24.0 to +18.0 dB
        self._mic_gain_slider.setValue(0)
        self._mic_gain_slider.valueChanged.connect(self._on_mixer_changed)
        mic_lay.addWidget(self._mic_gain_slider)

        self._mic_meter = StereoMeterWidget()
        mic_lay.addWidget(self._mic_meter)

        self._mic_file_preview = QLabel("session_YYYYMMDD_HHMMSS_1_mic.wav")
        self._mic_file_preview.setObjectName("FilePreview")
        mic_lay.addWidget(self._mic_file_preview)

        # Output 2: System Audio (WASAPI Loopback)
        sys_card = QFrame()
        sys_card.setObjectName("ChannelCard")
        sys_lay = QVBoxLayout(sys_card)
        sys_lay.setContentsMargins(14, 14, 14, 14)
        sys_lay.setSpacing(10)

        tag2 = QLabel("OUTPUT 2  •  STEREO TRACK")
        tag2.setObjectName("CardTag")
        hdr2 = QLabel("System Audio (WASAPI Loopback)")
        hdr2.setObjectName("CardHeader")
        sys_lay.addWidget(tag2)
        sys_lay.addWidget(hdr2)

        dev2_row = QHBoxLayout()
        self._sys_combo = QComboBox()
        self._sys_combo.currentIndexChanged.connect(self._on_device_selection_changed)
        dev2_row.addWidget(self._sys_combo, stretch=1)

        refresh_btn2 = QPushButton("↻")
        refresh_btn2.setFixedWidth(34)
        refresh_btn2.setToolTip("Refresh Windows WASAPI loopback devices")
        refresh_btn2.clicked.connect(self._refresh_devices)
        dev2_row.addWidget(refresh_btn2)
        sys_lay.addLayout(dev2_row)

        gain2_row = QHBoxLayout()
        gain2_lbl = QLabel("Gain")
        gain2_lbl.setObjectName("MutedLabel")
        self._sys_gain_val = QLabel("+0.0 dB")
        self._sys_gain_val.setObjectName("MutedLabel")
        self._sys_mute_btn = QPushButton("Mute")
        self._sys_mute_btn.setObjectName("MuteButton")
        self._sys_mute_btn.setCheckable(True)
        self._sys_mute_btn.toggled.connect(self._on_mixer_changed)
        gain2_row.addWidget(gain2_lbl)
        gain2_row.addStretch()
        gain2_row.addWidget(self._sys_gain_val)
        gain2_row.addWidget(self._sys_mute_btn)
        sys_lay.addLayout(gain2_row)

        self._sys_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._sys_gain_slider.setRange(-240, 180)
        self._sys_gain_slider.setValue(0)
        self._sys_gain_slider.valueChanged.connect(self._on_mixer_changed)
        sys_lay.addWidget(self._sys_gain_slider)

        self._sys_meter = StereoMeterWidget()
        sys_lay.addWidget(self._sys_meter)

        self._sys_file_preview = QLabel("session_YYYYMMDD_HHMMSS_2_system.wav")
        self._sys_file_preview.setObjectName("FilePreview")
        sys_lay.addWidget(self._sys_file_preview)

        # Output 3: Combined Stereo Mix
        comb_card = QFrame()
        comb_card.setObjectName("ChannelCardCombined")
        comb_lay = QVBoxLayout(comb_card)
        comb_lay.setContentsMargins(14, 14, 14, 14)
        comb_lay.setSpacing(10)

        tag3 = QLabel("OUTPUT 3  •  MASTER STEREO MIX")
        tag3.setObjectName("CardTag")
        hdr3 = QLabel("Combined (Mic + System)")
        hdr3.setObjectName("CardHeader")
        comb_lay.addWidget(tag3)
        comb_lay.addWidget(hdr3)

        desc3 = QLabel(
            "Sample-locked real-time stereo blend of Output 1 and Output 2, recorded simultaneously."
        )
        desc3.setWordWrap(True)
        desc3.setObjectName("MutedLabel")
        comb_lay.addWidget(desc3)

        self._limiter_cb = QCheckBox("Soft-Knee Peak Limiter (-1.0 dBFS knee / -0.1 dBFS ceiling)")
        self._limiter_cb.setChecked(True)
        self._limiter_cb.toggled.connect(self._on_mixer_changed)
        comb_lay.addWidget(self._limiter_cb)

        comb_lay.addStretch()

        self._comb_meter = StereoMeterWidget()
        comb_lay.addWidget(self._comb_meter)

        self._comb_file_preview = QLabel("session_YYYYMMDD_HHMMSS_3_combined.wav")
        self._comb_file_preview.setObjectName("FilePreview")
        comb_lay.addWidget(self._comb_file_preview)

        row.addWidget(mic_card, stretch=1)
        row.addWidget(sys_card, stretch=1)
        row.addWidget(comb_card, stretch=1)
        return row

    def _build_settings_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SettingsCard")
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        # Row 0: Format, Sample Rate, Bit Depth
        fmt_lbl = QLabel("Output Format")
        fmt_lbl.setObjectName("MutedLabel")
        self._format_combo = QComboBox()
        for fmt in OutputFormat:
            self._format_combo.addItem(fmt.label, fmt.value)
        self._format_combo.currentIndexChanged.connect(self._on_settings_changed)

        sr_lbl = QLabel("Sample Rate (Stereo)")
        sr_lbl.setObjectName("MutedLabel")
        self._sr_combo = QComboBox()
        self._sr_combo.addItem("48,000 Hz — Studio Standard Hi-Fi", 48000)
        self._sr_combo.addItem("96,000 Hz — Master Hi-Res", 96000)
        self._sr_combo.addItem("88,200 Hz", 88200)
        self._sr_combo.addItem("44,100 Hz — CD Standard", 44100)
        self._sr_combo.currentIndexChanged.connect(self._on_settings_changed)

        bd_lbl = QLabel("Bit Depth")
        bd_lbl.setObjectName("MutedLabel")
        self._bitdepth_combo = QComboBox()
        for bd in BitDepth:
            self._bitdepth_combo.addItem(bd.label, bd.value)
        self._bitdepth_combo.currentIndexChanged.connect(self._on_settings_changed)

        grid.addWidget(fmt_lbl, 0, 0)
        grid.addWidget(sr_lbl, 0, 1)
        grid.addWidget(bd_lbl, 0, 2)
        grid.addWidget(self._format_combo, 1, 0)
        grid.addWidget(self._sr_combo, 1, 1)
        grid.addWidget(self._bitdepth_combo, 1, 2)

        # Row 2: Session Prefix + Output Directory
        prefix_lbl = QLabel("Session Filename Prefix")
        prefix_lbl.setObjectName("MutedLabel")
        self._prefix_edit = QLineEdit("session")
        self._prefix_edit.textChanged.connect(self._on_settings_changed)

        dir_lbl = QLabel("Output Folder")
        dir_lbl.setObjectName("MutedLabel")

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self._dir_edit = QLineEdit()
        self._dir_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_folder)
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._on_open_folder)
        dir_row.addWidget(self._dir_edit, stretch=1)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(open_btn)

        grid.addWidget(prefix_lbl, 2, 0)
        grid.addWidget(dir_lbl, 2, 1, 1, 2)
        grid.addWidget(self._prefix_edit, 3, 0)
        grid.addLayout(dir_row, 3, 1, 1, 2)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        return panel

    def _build_recent_outputs_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("SettingsCard")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr = QLabel("Recorded Output Files")
        hdr.setObjectName("CardHeader")
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #ff7b72; font-size: 12px; background: transparent;")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        hdr_row.addWidget(self._error_label)
        self._convert_btn = QPushButton("Convert Recordings…")
        self._convert_btn.clicked.connect(self._on_convert_recordings)
        hdr_row.addWidget(self._convert_btn)
        lay.addLayout(hdr_row)

        self._outputs_table = QTableWidget(0, 5)
        self._outputs_table.setHorizontalHeaderLabels(
            ["Output Track", "Format", "Specs", "Size", "File Path"]
        )
        self._outputs_table.verticalHeader().setVisible(False)
        self._outputs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._outputs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self._outputs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._outputs_table.cellDoubleClicked.connect(lambda _r, _c: self._on_open_folder())
        lay.addWidget(self._outputs_table)
        return panel

    # ------------------------------------------------------------------
    # State Sync & Device Discovery
    # ------------------------------------------------------------------
    def _load_config_into_widgets(self) -> None:
        self._mic_gain_slider.setValue(int(round(self._config.mic_gain_db * 10)))
        self._sys_gain_slider.setValue(int(round(self._config.system_gain_db * 10)))
        self._mic_mute_btn.setChecked(self._config.mic_muted)
        self._sys_mute_btn.setChecked(self._config.system_muted)
        self._limiter_cb.setChecked(self._config.limiter_enabled)

        fmt_idx = self._format_combo.findData(self._config.output_format.value)
        if fmt_idx >= 0:
            self._format_combo.setCurrentIndex(fmt_idx)

        sr_idx = self._sr_combo.findData(self._config.sample_rate)
        if sr_idx >= 0:
            self._sr_combo.setCurrentIndex(sr_idx)

        bd_idx = self._bitdepth_combo.findData(self._config.bit_depth.value)
        if bd_idx >= 0:
            self._bitdepth_combo.setCurrentIndex(bd_idx)

        self._prefix_edit.setText(self._config.session_prefix)
        self._dir_edit.setText(self._config.output_dir)
        self._update_file_previews()

    def _refresh_devices(self) -> None:
        if self._engine.state in (EngineState.RECORDING, EngineState.PAUSED):
            return
        self._populating_devices = True
        try:
            self._mic_devices = self._engine.list_microphones()
            self._sys_devices = self._engine.list_system_loopbacks()

            self._mic_combo.clear()
            selected_mic_idx = 0
            for i, dev in enumerate(self._mic_devices):
                self._mic_combo.addItem(dev.display_label, dev.device_id)
                if self._config.mic_device_id == dev.device_id:
                    selected_mic_idx = i
                elif self._config.mic_device_id is None and dev.is_default:
                    selected_mic_idx = i
            if self._mic_devices:
                self._mic_combo.setCurrentIndex(selected_mic_idx)
            else:
                self._mic_combo.addItem("No microphone detected", None)

            self._sys_combo.clear()
            selected_sys_idx = 0
            for i, dev in enumerate(self._sys_devices):
                self._sys_combo.addItem(dev.display_label, dev.device_id)
                if self._config.system_device_id == dev.device_id:
                    selected_sys_idx = i
                elif self._config.system_device_id is None and dev.is_default:
                    selected_sys_idx = i
            if self._sys_devices:
                self._sys_combo.setCurrentIndex(selected_sys_idx)
            else:
                self._sys_combo.addItem("No WASAPI loopback output detected", None)
        finally:
            self._populating_devices = False

        self._start_live_monitoring()

    def _start_live_monitoring(self) -> None:
        mic_id = self._mic_combo.currentData()
        sys_id = self._sys_combo.currentData()
        self._config.mic_device_id = mic_id
        self._config.system_device_id = sys_id
        try:
            self._engine.start_monitoring(mic_device_id=mic_id, system_device_id=sys_id)
        except Exception as exc:
            self._error_label.setText(str(exc))
        else:
            self._error_label.setText(self._engine.get_snapshot().last_error or "")

    def _update_file_previews(self) -> None:
        prefix = self._prefix_edit.text().strip() or "session"
        fmt = self._config.output_format
        ext = "wav + .flac" if fmt is OutputFormat.BOTH else fmt.value
        self._mic_file_preview.setText(f"{prefix}_<timestamp>_1_mic.{ext}")
        self._sys_file_preview.setText(f"{prefix}_<timestamp>_2_system.{ext}")
        self._comb_file_preview.setText(f"{prefix}_<timestamp>_3_combined.{ext}")

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------
    def _on_device_selection_changed(self) -> None:
        if self._populating_devices:
            return
        if self._engine.state in (EngineState.RECORDING, EngineState.PAUSED):
            return
        self._start_live_monitoring()

    def _on_mixer_changed(self) -> None:
        if self._loading_config:
            return
        mic_db = self._mic_gain_slider.value() / 10.0
        sys_db = self._sys_gain_slider.value() / 10.0
        self._mic_gain_val.setText(f"{mic_db:+.1f} dB")
        self._sys_gain_val.setText(f"{sys_db:+.1f} dB")

        self._engine.update_mixer_params(
            mic_gain_db=mic_db,
            system_gain_db=sys_db,
            mic_muted=self._mic_mute_btn.isChecked(),
            system_muted=self._sys_mute_btn.isChecked(),
            limiter_enabled=self._limiter_cb.isChecked(),
        )

    def _on_settings_changed(self) -> None:
        if self._loading_config or self._engine.state in (EngineState.RECORDING, EngineState.PAUSED):
            return
        new_sr = int(self._sr_combo.currentData() or 48000)
        self._config.output_format = OutputFormat(self._format_combo.currentData())
        self._config.bit_depth = BitDepth(self._bitdepth_combo.currentData())
        self._config.session_prefix = self._prefix_edit.text().strip() or "session"
        self._update_file_previews()

        if new_sr != self._config.sample_rate:
            self._engine.update_config(replace(self._config, sample_rate=new_sr))
            self._config = self._engine.config

    def _on_browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self._config.output_dir
        )
        if chosen:
            self._config.output_dir = chosen
            self._dir_edit.setText(chosen)

    def _on_open_folder(self) -> None:
        try:
            _open_folder_in_explorer(Path(self._config.output_dir))
        except Exception as exc:
            QMessageBox.warning(self, "Open Folder", f"Could not open output folder:\n{exc}")

    def _set_settings_locked(self, locked: bool) -> None:
        for widget in (
            self._mic_combo,
            self._sys_combo,
            self._format_combo,
            self._sr_combo,
            self._bitdepth_combo,
            self._prefix_edit,
            self._convert_btn,
        ):
            widget.setEnabled(not locked)

    def _on_convert_recordings(self) -> None:
        model = self._outputs_table.selectionModel()
        sources = [Path(index.data()) for index in model.selectedRows(4)]
        dialog = ConverterDialog(self, self._config.output_dir, sources)
        dialog.exec()
        dialog.deleteLater()

    def _on_record_clicked(self) -> None:
        try:
            self._config.save()
            self._engine.start_recording()
        except Exception as exc:
            QMessageBox.critical(self, "Recording Error", f"Could not start recording:\n{exc}")
            return

        self._set_settings_locked(True)
        self._record_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Pause")
        self._stop_btn.setEnabled(True)
        self._error_label.setText("")

    def _on_pause_clicked(self) -> None:
        if self._engine.state is EngineState.RECORDING:
            self._engine.pause_recording()
            self._pause_btn.setText("Resume")
        elif self._engine.state is EngineState.PAUSED:
            self._engine.resume_recording()
            self._pause_btn.setText("Pause")

    def _on_stop_clicked(self) -> None:
        summary = self._engine.stop_recording()
        self._set_settings_locked(False)
        self._record_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._pause_btn.setText("Pause")
        self._stop_btn.setEnabled(False)

        if summary is not None:
            self._append_summary_to_table(summary)

    def _append_summary_to_table(self, summary: RecordingSummary) -> None:
        specs = (
            f"{summary.sample_rate // 1000} kHz • Stereo • "
            f"{_format_duration(summary.duration_seconds)}"
        )
        for info in summary.files:
            row = 0
            self._outputs_table.insertRow(row)
            self._outputs_table.setItem(row, 0, QTableWidgetItem(info.track_label))
            self._outputs_table.setItem(
                row, 1, QTableWidgetItem(f"{info.audio_format} ({info.subtype})")
            )
            self._outputs_table.setItem(row, 2, QTableWidgetItem(specs))
            self._outputs_table.setItem(row, 3, QTableWidgetItem(_format_size(info.size_bytes)))
            self._outputs_table.setItem(row, 4, QTableWidgetItem(str(info.path)))

    def _poll_engine(self) -> None:
        snap = self._engine.get_snapshot()
        self._mic_meter.set_level(snap.mic_level)
        self._sys_meter.set_level(snap.system_level)
        self._comb_meter.set_level(snap.combined_level)

        if snap.state in (EngineState.RECORDING, EngineState.PAUSED):
            self._timer_label.setText(_format_duration(snap.elapsed_seconds))
        elif snap.state is EngineState.MONITORING:
            self._timer_label.setText("00:00:00.0")

        pill_map = {
            EngineState.IDLE: ("IDLE", "StatusIdle"),
            EngineState.MONITORING: ("LIVE MONITOR", "StatusMonitoring"),
            EngineState.RECORDING: ("● RECORDING", "StatusRecording"),
            EngineState.PAUSED: ("❚❚ PAUSED", "StatusPaused"),
        }
        text, obj_name = pill_map[snap.state]
        if self._status_pill.objectName() != obj_name:
            self._status_pill.setText(text)
            self._status_pill.setObjectName(obj_name)
            self._status_pill.style().unpolish(self._status_pill)
            self._status_pill.style().polish(self._status_pill)

        if snap.last_error:
            self._error_label.setText(snap.last_error)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._ui_timer.stop()
        try:
            self._config.save()
        except Exception:
            pass
        self._engine.shutdown()
        super().closeEvent(event)
