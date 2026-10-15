from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QBoxLayout,
    QLabel,
    QPushButton,
    QButtonGroup,
    QSizePolicy,
)
import qtawesome as qta

from localization.live import tr_set
from localization import translate
from styles.theme import get_theme


def voice_label(ru, en, name="VoiceDescription"):
    label = tr_set(QLabel(), ru, en)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class VoiceCard(QFrame):
    def __init__(
        self, ru="", en="", icon="fa5s.volume-up", hint_ru="", hint_en="", parent=None
    ):
        super().__init__(parent)
        self.setObjectName("VoiceCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 18, 18, 18)
        self.body.setSpacing(14)
        if not ru:
            return
        header = QHBoxLayout()
        header.setSpacing(12)
        badge = QLabel()
        badge.setObjectName("VoiceCardIcon")
        badge.setPixmap(qta.icon(icon, color=get_theme()["accent"]).pixmap(24, 24))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 44)
        header.addWidget(badge)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        copy.addWidget(voice_label(ru, en, "VoiceCardTitle"))
        if hint_ru:
            copy.addWidget(voice_label(hint_ru, hint_en))
        header.addLayout(copy, 1)
        self.body.addLayout(header)


class VoiceColumns(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.left = QWidget()
        self.right = QWidget()
        for widget, weight in ((self.left, 6), (self.right, 4)):
            widget.setMinimumWidth(0)
            self.box.addWidget(widget, weight, Qt.AlignmentFlag.AlignTop)
        self.left_layout = QVBoxLayout(self.left)
        self.right_layout = QVBoxLayout(self.right)
        for layout in (self.left_layout, self.right_layout):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 1050
        self.box.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compact
            else QBoxLayout.Direction.LeftToRight
        )


class VoiceMethodSelector(QFrame):
    currentTextChanged = pyqtSignal(str)

    def __init__(self, method="Local", parent=None):
        super().__init__(parent)
        self._method = ""
        self.setObjectName("VoiceMethodSelector")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        self.buttons = {}
        self.group = QButtonGroup(self)
        for value, ru, en, icon in (
            ("TG", "Telegram", "Telegram", "fa5b.telegram-plane"),
            ("Local", "Локальная", "Local", "fa5s.desktop"),
            ("API", "API", "API", "fa5s.cloud"),
        ):
            button = tr_set(QPushButton(), ru, en)
            button.setObjectName("VoiceMethodButton")
            button.setCheckable(True)
            button.setIcon(qta.icon(icon, color=get_theme()["text"]))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, v=value: self.setCurrentText(v))
            self.group.addButton(button)
            self.buttons[value] = button
            row.addWidget(button)
        self.setCurrentText(method if method in self.buttons else "Local")

    def currentText(self):
        return self._method

    def setCurrentText(self, method):
        if method not in self.buttons or method == self._method:
            return
        self._method = method
        self.buttons[method].setChecked(True)
        self.currentTextChanged.emit(method)


class VoiceStatus(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VoiceStatus")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(9)
        self.indicator = QFrame()
        self.indicator.setFixedSize(8, 8)
        row.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel()
        self.label.setObjectName("VoiceStatusText")
        self.label.setWordWrap(True)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(self.label, 1)
        self.set_status(None, "")

    def set_status(self, state, text):
        theme = get_theme()
        colors = {
            "green": theme["success"],
            "red": theme["danger"],
            "warn": "#e4ad68",
            "loading": theme["accent"],
        }
        color = colors.get(state, theme["muted"])
        self.label.setText(
            str(text or translate("Озвучка выключена", "Voiceover disabled"))
        )
        self.label.setStyleSheet(f"color: {color};")
        self.indicator.setStyleSheet(
            f"background: {color}; border: none; border-radius: 4px;"
        )
