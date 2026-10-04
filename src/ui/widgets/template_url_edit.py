from PyQt6.QtCore import QEvent, QRegularExpression, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedLayout,
    QWidget,
)

from presets.api_endpoints import server_address
from styles.theme import THEME
from localization.live import tr_set


class TemplateUrlEdit(QWidget):
    textChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._template = {}
        self._updating = False
        self.setFixedHeight(40)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self.free_edit = QLineEdit()
        self.free_edit.setMinimumHeight(40)
        self._stack.addWidget(self.free_edit)
        self._frame = QFrame()
        self._frame.setObjectName("TemplateUrlSegments")
        row = QHBoxLayout(self._frame)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(0)
        self.prefix = QLabel("http")
        self.secure_edit = QLineEdit()
        self.secure_edit.setMaxLength(1)
        self.secure_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("s?"), self)
        )
        self.secure_edit.setFixedWidth(10)
        self.secure_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tr_set(
            self.secure_edit,
            "HTTPS: необязательная s",
            "HTTPS: optional s",
            "setAccessibleName",
        )
        tr_set(
            self.secure_edit,
            "Введите s для HTTPS или оставьте пустым для HTTP.",
            "Enter s for HTTPS or leave empty for HTTP.",
            "setToolTip",
        )
        self.separator = QLabel("://")
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("127.0.0.1:1234")
        tr_set(
            self.address_edit, "Адрес сервера", "Server address", "setAccessibleName"
        )
        self.suffix = QLabel()
        for widget in (
            self.prefix,
            self.secure_edit,
            self.separator,
            self.address_edit,
            self.suffix,
        ):
            row.addWidget(widget)
        row.addStretch(1)
        self._stack.addWidget(self._frame)
        self._frame.setStyleSheet(f"""
            QFrame#TemplateUrlSegments {{ background: {THEME['control_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}
            QFrame#TemplateUrlSegments QLabel {{ color: #85818f; background: transparent; border: none; padding: 0; }}
            QFrame#TemplateUrlSegments QLineEdit {{ color: {THEME['text']}; background: transparent; border: none; border-bottom: 1px solid {THEME['border_soft']}; border-radius: 0; padding: 0; min-height: 24px; }}
            QFrame#TemplateUrlSegments QLineEdit:focus {{ border-bottom: 1px solid {THEME['accent']}; }}
        """)
        self.free_edit.textChanged.connect(self._changed)
        self.secure_edit.textChanged.connect(self._changed)
        self.address_edit.textChanged.connect(self._changed)
        self.secure_edit.textEdited.connect(self._secure_typed)
        self.secure_edit.installEventFilter(self)
        self.address_edit.installEventFilter(self)
        QWidget.setTabOrder(self.secure_edit, self.address_edit)
        self.setFocusProxy(self.free_edit)

    def set_template(self, template: dict) -> None:
        template = dict(template or {})
        if template == self._template:
            return
        value = self.text()
        self._template = template
        segmented = bool(template.get("url_editable") and template.get("request_path"))
        self._stack.setCurrentIndex(1 if segmented else 0)
        self.suffix.setText(str(template.get("request_path") or ""))
        self.setFocusProxy(self.address_edit if segmented else self.free_edit)
        self._set_value(value, emit=False)

    def text(self) -> str:
        if self._stack.currentIndex() == 0:
            return self.free_edit.text()
        return f"http{self.secure_edit.text()}://{self.address_edit.text()}{self.suffix.text()}"

    def setText(self, value: str) -> None:
        self._set_value(str(value or ""), emit=True)

    def _set_value(self, value: str, *, emit: bool) -> None:
        previous = self.text()
        self._updating = True
        try:
            self.free_edit.setText(value)
            if self._stack.currentIndex() == 1:
                address = server_address(self._template, value)
                scheme, separator, host = address.partition("://")
                self.secure_edit.setText("s" if separator and scheme == "https" else "")
                self.address_edit.setText(host if separator else address)
                self._size_address()
        finally:
            self._updating = False
        if emit and self.text() != previous:
            self.textChanged.emit(self.text())

    def setPlaceholderText(self, value: str) -> None:
        self.free_edit.setPlaceholderText(value)

    def _changed(self, *_args) -> None:
        if not self._updating:
            self._size_address()
            self.textChanged.emit(self.text())

    def _secure_typed(self, value: str) -> None:
        if value == "s":
            self.address_edit.setFocus()
            self.address_edit.setCursorPosition(0)

    def _size_address(self) -> None:
        self.secure_edit.setFixedWidth(
            self.secure_edit.fontMetrics().horizontalAdvance("s") + 4
        )
        locked_width = (
            sum(
                label.sizeHint().width()
                for label in (self.prefix, self.separator, self.suffix)
            )
            + 42
        )
        available = max(70, self.width() - locked_width)
        desired = (
            self.address_edit.fontMetrics().horizontalAdvance(
                self.address_edit.text() or self.address_edit.placeholderText()
            )
            + 8
        )
        self.address_edit.setFixedWidth(min(available, max(100, desired)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._size_address()

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        key = event.key()
        if event.matches(QKeySequence.StandardKey.Paste):
            pasted = QApplication.clipboard().text().strip()
            if "://" in pasted:
                self.setText(pasted)
                self.address_edit.setFocus()
                self.address_edit.setCursorPosition(len(self.address_edit.text()))
                return True
        if (
            event.matches(QKeySequence.StandardKey.Copy)
            and not watched.hasSelectedText()
        ):
            QApplication.clipboard().setText(self.text())
            return True
        if watched.hasSelectedText() or event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            return super().eventFilter(watched, event)
        if watched is self.address_edit and watched.cursorPosition() == 0:
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
                self.secure_edit.setFocus()
                self.secure_edit.setCursorPosition(len(self.secure_edit.text()))
                if key == Qt.Key.Key_Backspace:
                    self.secure_edit.clear()
                return True
        if (
            watched is self.secure_edit
            and key == Qt.Key.Key_Right
            and watched.cursorPosition() == len(watched.text())
        ):
            self.address_edit.setFocus()
            self.address_edit.setCursorPosition(0)
            return True
        return super().eventFilter(watched, event)
