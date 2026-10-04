from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from styles.theme import get_theme
from .helpers import qta


class StatusIcon(QPushButton):
    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self.setObjectName("AIHubStatusIcon")
        self.setFixedSize(size, size)
        self.setIconSize(QSize(size // 2, size // 2))
        self.setEnabled(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._animation = None
        self._spinning = False
        self._icon_key = None

    def set_status(self, name: str, *, spinning: bool = False, color: str | None = None) -> None:
        key = (name, spinning, color)
        if key == self._icon_key:
            return
        self._icon_key = key
        if self._animation is not None:
            self._animation.stop()
        self._spinning = spinning
        if qta is None:
            self.setText("…" if spinning else "•")
            return
        color = color or get_theme()["accent"]
        if spinning and self._animation is None:
            self._animation = qta.Spin(self, interval=20, step=6)
        self.setIcon(qta.icon(
            name, color=color, color_disabled=color,
            **({"animation": self._animation} if spinning else {}),
        ))
        if spinning and self.isVisible():
            self._animation.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._spinning and self._animation is not None:
            self._animation.start()

    def hideEvent(self, event) -> None:
        if self._animation is not None:
            self._animation.stop()
        super().hideEvent(event)


class SettingsStatusPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIHubSettingsStatePane")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(460)
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        self.icon = StatusIcon(64)
        box.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel()
        self.title.setObjectName("AIHubSettingsStateTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        box.addWidget(self.title)
        self.description = QLabel()
        self.description.setObjectName("AIHubSettingsEmpty")
        self.description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description.setWordWrap(True)
        self.description.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        box.addWidget(self.description)
        self.action = QPushButton()
        self.action.setObjectName("AIHubSecondary")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        box.addWidget(self.action, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(content, 8)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def present(self, title: str, description: str, *, icon: str, loading: bool = False, action: str = "") -> None:
        self.title.setText(title)
        self.description.setText(description)
        self.icon.set_status(icon, spinning=loading)
        self.action.setText(action)
        self.action.setVisible(bool(action))
