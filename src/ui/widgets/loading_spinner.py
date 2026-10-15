import qtawesome as qta
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QPushButton

from styles.theme import get_theme


class LoadingSpinner(QPushButton):
    """Animate only while visible; stop the timer when the widget is hidden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoadingSpinner")
        self.setFixedSize(32, 32)
        self.setIconSize(QSize(28, 28))
        self.setEnabled(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QPushButton#LoadingSpinner { background: transparent; border: none; padding: 0; }"
        )
        self._animation = qta.Spin(self, interval=20, step=6)
        color = get_theme()["accent"]
        self.setIcon(
            qta.icon(
                "fa6s.circle-notch",
                color=color,
                color_disabled=color,
                animation=self._animation,
            )
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._animation.start()

    def hideEvent(self, event):
        self._animation.stop()
        super().hideEvent(event)
