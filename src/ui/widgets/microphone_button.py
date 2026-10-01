from __future__ import annotations

import math
import time

import qtawesome as qta
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen
from PyQt6.QtWidgets import QPushButton


class MicrophoneButton(QPushButton):
    """Draw capture activity locally; the wave is an activity indicator, not a level meter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatMicrophoneButton")
        self.setFixedSize(38, 38)
        self.setIconSize(QSize(18, 18))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capture_active = False
        self._phase = "idle"
        self._idle_icon = qta.icon("fa6s.microphone", color="#a0a0b4")
        self.setIcon(self._idle_icon)
        self._animation = QTimer(self)
        self._animation.setInterval(33)
        self._animation.timeout.connect(self.update)

    def set_capture_visual(self, *, active: bool, phase: str) -> None:
        if (active, phase) == (self._capture_active, self._phase):
            return
        self._capture_active, self._phase = active, phase
        self.setProperty("captureActive", active)
        self.setIcon(QIcon() if self._animated else self._idle_icon)
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_animation()
        self.update()

    @property
    def _animated(self) -> bool:
        return self._capture_active or self._phase == "recognizing"

    def _sync_animation(self) -> None:
        if self._animated and self.isVisible():
            self._animation.start()
        else:
            self._animation.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event) -> None:
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._animated:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.rect().center())
        color = QColor("#ffffff" if self._capture_active else "#ff65a6")
        pen = QPen(color, 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        elapsed = time.monotonic()
        if self._capture_active:
            speed = 5.0 if self._phase == "listening" else 9.0
            amplitude = 10.0 if self._phase == "listening" else 18.0
            for index in range(5):
                envelope = (0.5, 0.8, 1.0, 0.8, 0.5)[index]
                height = 4.0 + amplitude * envelope * (0.5 + 0.5 * math.sin(elapsed * speed - index * 0.9))
                x = center.x() + (index - 2) * 4.0
                painter.drawLine(QPointF(x, center.y() - height / 2), QPointF(x, center.y() + height / 2))
        else:
            bounds = QRectF(center.x() - 8, center.y() - 8, 16, 16)
            painter.drawArc(bounds, int((-elapsed * 240) % 360 * 16), 240 * 16)
        painter.end()
