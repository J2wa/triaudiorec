"""High-FPS custom QPainter dual-channel L/R stereo dBFS level meter with peak hold and clip LED."""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..dsp import MIN_DB, StereoLevel


class StereoMeterWidget(QWidget):
    """Dual horizontal stereo L/R meter (-60 dBFS to 0 dBFS) with peak hold & clip alert."""

    FLOOR_DB = -60.0
    CEIL_DB = 0.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMaximumHeight(74)
        self.setToolTip("Stereo Left/Right dBFS meter (click to reset clip indicator)")

        self._l_rms = self.FLOOR_DB
        self._r_rms = self.FLOOR_DB
        self._l_peak_hold = self.FLOOR_DB
        self._r_peak_hold = self.FLOOR_DB
        self._l_peak_ts = 0.0
        self._r_peak_ts = 0.0
        self._clip_until = 0.0

    def set_level(self, level: StereoLevel) -> None:
        """Update meter values with smooth decay ballistics and 1.2s peak hold."""
        now = time.monotonic()

        # Smooth falloff on RMS/bar display, instant attack
        target_l = max(self.FLOOR_DB, min(self.CEIL_DB, level.left_peak_db))
        target_r = max(self.FLOOR_DB, min(self.CEIL_DB, level.right_peak_db))

        self._l_rms = target_l if target_l >= self._l_rms else max(self.FLOOR_DB, self._l_rms - 2.4)
        self._r_rms = target_r if target_r >= self._r_rms else max(self.FLOOR_DB, self._r_rms - 2.4)

        if target_l >= self._l_peak_hold or (now - self._l_peak_ts) > 1.2:
            if target_l >= self._l_peak_hold:
                self._l_peak_hold = target_l
                self._l_peak_ts = now
            else:
                self._l_peak_hold = max(target_l, self._l_peak_hold - 1.5)

        if target_r >= self._r_peak_hold or (now - self._r_peak_ts) > 1.2:
            if target_r >= self._r_peak_hold:
                self._r_peak_hold = target_r
                self._r_peak_ts = now
            else:
                self._r_peak_hold = max(target_r, self._r_peak_hold - 1.5)

        if level.clipped:
            self._clip_until = now + 2.0

        self.update()

    def reset(self) -> None:
        self._l_rms = self.FLOOR_DB
        self._r_rms = self.FLOOR_DB
        self._l_peak_hold = self.FLOOR_DB
        self._r_peak_hold = self.FLOOR_DB
        self._clip_until = 0.0
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._clip_until = 0.0
        self.update()
        super().mousePressEvent(event)

    def _db_to_ratio(self, db: float) -> float:
        if db <= self.FLOOR_DB:
            return 0.0
        if db >= self.CEIL_DB:
            return 1.0
        return (db - self.FLOOR_DB) / (self.CEIL_DB - self.FLOOR_DB)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background frame
        bg_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        painter.setPen(QPen(QColor("#262c36"), 1.0))
        painter.setBrush(QColor("#0a0d12"))
        painter.drawRoundedRect(bg_rect, 8.0, 8.0)

        label_w = 20.0
        clip_w = 42.0
        pad_x = 8.0
        bar_x = pad_x + label_w
        bar_w = max(20.0, w - bar_x - clip_w - pad_x)
        bar_h = 13.0
        l_y = 10.0
        r_y = 28.0

        # Horizontal stereo gradient: Emerald -> Amber -> Crimson
        grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        grad.setColorAt(0.0, QColor("#1f883d"))
        grad.setColorAt(0.68, QColor("#3fb950"))
        grad.setColorAt(0.82, QColor("#e3b341"))
        grad.setColorAt(0.95, QColor("#f85149"))
        grad.setColorAt(1.0, QColor("#ff4d4f"))

        font_ch = QFont("Cascadia Mono", 9)
        font_ch.setBold(True)
        painter.setFont(font_ch)

        for label, y, val_db, peak_db in (
            ("L", l_y, self._l_rms, self._l_peak_hold),
            ("R", r_y, self._r_rms, self._r_peak_hold),
        ):
            painter.setPen(QColor("#8b949e"))
            painter.drawText(
                QRectF(pad_x, y - 1, label_w - 4, bar_h + 2),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )

            track_rect = QRectF(bar_x, y, bar_w, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#161b22"))
            painter.drawRoundedRect(track_rect, 3.0, 3.0)

            fill_ratio = self._db_to_ratio(val_db)
            if fill_ratio > 0.002:
                fill_rect = QRectF(bar_x, y, bar_w * fill_ratio, bar_h)
                painter.setBrush(grad)
                painter.drawRoundedRect(fill_rect, 3.0, 3.0)

            peak_ratio = self._db_to_ratio(peak_db)
            if peak_ratio > 0.01:
                px = bar_x + bar_w * peak_ratio
                peak_color = QColor("#ff7b72") if peak_db >= -3.0 else QColor("#f0f6fc")
                painter.setPen(QPen(peak_color, 2.0))
                painter.drawLine(int(px), int(y + 1), int(px), int(y + bar_h - 1))

        # Clip LED indicator
        clip_active = time.monotonic() < self._clip_until
        clip_rect = QRectF(bar_x + bar_w + 6, l_y, clip_w - 8, (r_y + bar_h) - l_y)
        painter.setPen(QPen(QColor("#da3633" if clip_active else "#262c36"), 1.0))
        painter.setBrush(QColor("#da3633" if clip_active else "#161b22"))
        painter.drawRoundedRect(clip_rect, 4.0, 4.0)

        font_clip = QFont("Segoe UI", 8)
        font_clip.setBold(True)
        painter.setFont(font_clip)
        painter.setPen(QColor("#ffffff" if clip_active else "#484f58"))
        painter.drawText(clip_rect, Qt.AlignmentFlag.AlignCenter, "CLIP")

        # Bottom dB scale markers
        font_scale = QFont("Cascadia Mono", 8)
        painter.setFont(font_scale)
        painter.setPen(QColor("#6e7681"))
        scale_y = r_y + bar_h + 4
        for mark_db in (-60, -36, -24, -12, -6, 0):
            ratio = self._db_to_ratio(float(mark_db))
            mx = bar_x + bar_w * ratio
            txt = f"{mark_db}"
            rect = QRectF(mx - 14, scale_y, 28, 14)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, txt)

        # Numeric readout in bottom-right under CLIP
        l_txt = "-inf" if self._l_peak_hold <= MIN_DB + 1 else f"{self._l_peak_hold:4.0f}"
        r_txt = "-inf" if self._r_peak_hold <= MIN_DB + 1 else f"{self._r_peak_hold:4.0f}"
        painter.setPen(QColor("#8b949e"))
        painter.drawText(
            QRectF(bar_x + bar_w + 2, scale_y, clip_w, 14),
            Qt.AlignmentFlag.AlignCenter,
            f"{l_txt}/{r_txt}",
        )
