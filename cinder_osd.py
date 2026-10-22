"""A small crimson Windows-style brightness on-screen display for Cinder."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget


class BrightnessOSD(QWidget):
    """Non-activating, auto-hiding brightness HUD shown after brightness changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 50
        self.setFixedSize(330, 76)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity_effect)
        self.fade = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out)

    def show_level(self, level: int) -> None:
        self.level = max(0, min(100, int(level)))
        screen = QApplication.primaryScreen()
        if screen:
            bounds = screen.availableGeometry()
            x = bounds.left() + (bounds.width() - self.width()) // 2
            # Sit in the lower screen area, above the taskbar, like a system OSD.
            y = bounds.bottom() - self.height() - 18
            self.move(x, y)
        self.hide_timer.stop()
        self.fade.stop()
        self.opacity_effect.setOpacity(0.0 if not self.isVisible() else self.opacity_effect.opacity())
        self.show()
        self.raise_()
        self.fade.setStartValue(self.opacity_effect.opacity())
        self.fade.setEndValue(1.0)
        self.fade.setDuration(150)
        self.fade.start()
        self.hide_timer.start(1150)
        self.update()

    def _fade_out(self) -> None:
        self.fade.stop()
        self.fade.setStartValue(self.opacity_effect.opacity())
        self.fade.setEndValue(0.0)
        self.fade.setDuration(220)
        self.fade.finished.connect(self._hide_after_fade)
        self.fade.start()

    def _hide_after_fade(self) -> None:
        if self.opacity_effect.opacity() <= 0.01:
            self.hide()
        try:
            self.fade.finished.disconnect(self._hide_after_fade)
        except (RuntimeError, TypeError):
            pass

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        surface = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(119, 48, 59, 205), 1.0))
        painter.setBrush(QColor(20, 13, 16, 246))
        painter.drawRoundedRect(surface, 17, 17)

        # Simple sun glyph and compact percentage readout.
        painter.setPen(QPen(QColor(255, 135, 144, 245), 1.8))
        cx, cy = 31, 29
        painter.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))
        for i in range(8):
            ang = math.radians(i * 45)
            painter.drawLine(
                int(cx + math.cos(ang) * 10), int(cy + math.sin(ang) * 10),
                int(cx + math.cos(ang) * 13), int(cy + math.sin(ang) * 13),
            )
        painter.setPen(QColor(255, 244, 246, 245))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(54, 13, 170, 23), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Brightness")
        painter.setPen(QColor(211, 187, 192, 245))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        painter.drawText(QRectF(265, 13, 48, 23), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self.level}%")

        track = QRectF(54, 43, 258, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(74, 48, 54, 225))
        painter.drawRoundedRect(track, 3.5, 3.5)
        fill = QRectF(track.x(), track.y(), track.width() * self.level / 100.0, track.height())
        painter.setBrush(QColor(239, 78, 93, 250))
        painter.drawRoundedRect(fill, 3.5, 3.5)
