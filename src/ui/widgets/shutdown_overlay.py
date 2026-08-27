from __future__ import annotations

import qtawesome as qta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from localization.live import tr_set


class ShutdownOverlayPanel(QFrame):
    """Compact status card shown while application services are stopping."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ShutdownOverlayPanel")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 34, 40, 34)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel()
        icon.setObjectName("ShutdownOverlayIcon")
        icon.setFixedSize(58, 58)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(qta.icon("fa6s.power-off", color="#f3edf6").pixmap(25, 25))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel()
        title.setObjectName("ShutdownOverlayTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tr_set(title, "Закрытие", "Closing")
        layout.addWidget(title)

        accent = QFrame()
        accent.setObjectName("ShutdownOverlayAccent")
        accent.setFixedSize(72, 3)
        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignHCenter)


__all__ = ["ShutdownOverlayPanel"]
