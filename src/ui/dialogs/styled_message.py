# src/ui/dialogs/styled_message.py
"""Лёгкое модальное сообщение в тёмной теме приложения.

Замена стандартным QMessageBox.* (которые рисуются в белой системной теме и
выбиваются из оформления). Используется, например, в просмотре контекста
последнего запроса.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# level -> (глиф, цвет)
_ICONS = {
    "info": ("ⓘ", "#60A5FA"),
    "warning": ("⚠", "#F4D35E"),
    "error": ("✕", "#FF6B6B"),
}

_STYLE = """
QDialog { background-color: #1A1A24; }
QLabel#MsgTitle { color: #f3edf6; font-size: 14px; font-weight: 600; background: transparent; border: none; }
QLabel#MsgText  { color: #d6cdd6; font-size: 12px; background: transparent; border: none; }
QPushButton#PrimaryBtn {
    background-color: #b74b7d; color: #ffffff; font-weight: 600;
    border: 1px solid rgba(183, 75, 125,0.46); border-radius: 8px;
    padding: 7px 18px; min-width: 88px; font-size: 12px;
}
QPushButton#PrimaryBtn:hover { background-color: #c04c80; }
"""


class StyledMessageDialog(QDialog):
    """Простое сообщение [иконка | заголовок + текст | OK] в стиле приложения."""

    def __init__(self, title: str, text: str, *, level: str = "info", parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(580)
        self.setStyleSheet(_STYLE)
        self.setWindowTitle(title)

        glyph, color = _ICONS.get(level, _ICONS["info"])

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)

        icon = QLabel(glyph)
        icon.setStyleSheet(f"color: {color}; font-size: 22px; background: transparent; border: none;")
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("MsgTitle")
        title_lbl.setWordWrap(True)
        text_col.addWidget(title_lbl)
        body_lbl = QLabel(text)
        body_lbl.setObjectName("MsgText")
        body_lbl.setWordWrap(True)
        body_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_col.addWidget(body_lbl)
        top.addLayout(text_col, 1)
        root.addLayout(top)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("PrimaryBtn")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)


def show_styled_message(parent, title: str, text: str, *, level: str = "info") -> None:
    """level: 'info' | 'warning' | 'error'."""
    StyledMessageDialog(title, text, level=level, parent=parent).exec()
