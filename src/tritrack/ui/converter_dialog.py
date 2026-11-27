"""Qt dialog for converting one or more recordings off the UI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..converter import CONVERSION_PRESETS, ConversionPreset, convert_recording


class _ConversionThread(QThread):
    file_finished = Signal(int, str, str)

    def __init__(
        self, parent: QWidget, sources: list[Path], preset: ConversionPreset, gain_db: int
    ) -> None:
        super().__init__(parent)
        self.sources = sources
        self.preset = preset
        self.gain_db = gain_db

    def run(self) -> None:
        for index, source in enumerate(self.sources):
            try:
                output = convert_recording(
                    source, self.preset, self.gain_db, cancelled=self.isInterruptionRequested
                )
            except InterruptedError as exc:
                if self.isInterruptionRequested():
                    break
                self.file_finished.emit(index, "", str(exc))
            except Exception as exc:
                self.file_finished.emit(index, "", str(exc) or type(exc).__name__)
            else:
                self.file_finished.emit(index, str(output), "")


class ConverterDialog(QDialog):
    def __init__(self, parent: QWidget | None, start_folder: str, sources: list[Path]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert Recordings")
        self.resize(680, 420)
        self._start_folder = start_folder
        self._sources = sources
        self._worker: _ConversionThread | None = None
        self._saved = 0
        self._cancel_requested = False

        layout = QVBoxLayout(self)
        self._browse = QPushButton("Choose WAV or FLAC Files…")
        self._browse.clicked.connect(self._choose_files)
        layout.addWidget(self._browse)

        self._files = QListWidget()
        self._files.addItems([source.name for source in sources])
        layout.addWidget(self._files, stretch=1)

        form = QFormLayout()
        self._preset = QComboBox()
        self._preset.addItems([preset.label for preset in CONVERSION_PRESETS])
        form.addRow("Export format", self._preset)
        self._gain = QSpinBox()
        self._gain.setRange(-24, 24)
        self._gain.setSuffix(" dB")
        self._gain.setToolTip("Positive values make the audio louder. Peak limiting reduces clipping.")
        form.addRow("Volume adjustment", self._gain)
        layout.addLayout(form)

        layout.addWidget(QLabel("Copies are saved beside the original files."))
        self._status = QLabel()
        layout.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.hide()
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._close = QPushButton("Close")
        self._close.clicked.connect(self.reject)
        buttons.addWidget(self._close)
        self._convert = QPushButton("Convert")
        self._convert.setEnabled(bool(sources))
        self._convert.clicked.connect(self._start_conversion)
        buttons.addWidget(self._convert)
        layout.addLayout(buttons)

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose Recordings", self._start_folder, "Recordings (*.wav *.flac)"
        )
        if files:
            self._sources = list(dict.fromkeys(Path(file) for file in files))
            self._start_folder = str(self._sources[0].parent)
            self._files.clear()
            self._files.addItems([source.name for source in self._sources])
            self._progress.hide()
            self._status.clear()
            self._convert.setEnabled(True)

    def _start_conversion(self) -> None:
        if self._worker is not None or not self._sources:
            return

        self._saved = 0
        self._cancel_requested = False
        self._status.setText("Converting recordings…")
        self._progress.setRange(0, len(self._sources))
        self._progress.setValue(0)
        self._progress.show()
        self._files.clear()
        self._files.addItems([source.name for source in self._sources])

        for widget in (self._browse, self._preset, self._gain, self._convert):
            widget.setEnabled(False)
        self._close.setText("Cancel")

        preset = CONVERSION_PRESETS[self._preset.currentIndex()]
        self._worker = _ConversionThread(self, self._sources, preset, self._gain.value())
        self._worker.file_finished.connect(self._show_file_result)
        self._worker.finished.connect(self._finish_conversion)
        self._worker.start()

    @Slot(int, str, str)
    def _show_file_result(self, index: int, output: str, error: str) -> None:
        item = self._files.item(index)
        if error:
            item.setText(f"{self._sources[index].name} · {error}")
            item.setToolTip(error)
        else:
            self._saved += 1
            item.setText(f"{self._sources[index].name} → {Path(output).name}")
            item.setToolTip(output)
        self._progress.setValue(index + 1)

    @Slot()
    def _finish_conversion(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        total = len(self._sources)
        result = f"Saved {self._saved} of {total} converted files."
        if self._cancel_requested and self._progress.value() < total:
            result = f"Conversion cancelled. {result}"
        self._status.setText(result)
        for widget in (self._browse, self._preset, self._gain, self._convert, self._close):
            widget.setEnabled(True)
        self._close.setText("Close")

    def reject(self) -> None:
        if self._worker is not None:
            self._cancel_requested = True
            self._worker.requestInterruption()
            self._close.setEnabled(False)
            self._status.setText("Cancelling…")
            return
        super().reject()
