from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QPixmap, QColor, QFont, QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QStyledItemDelegate, QStyle, QListWidgetItem, QComboBox, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QTextEdit, QToolButton
)


class ProviderDelegate(QStyledItemDelegate):
    _free_pm = None

    @classmethod
    def _free_pixmap(cls):
        if cls._free_pm is None:
            font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            metrics = QFontMetrics(font)
            text_w = metrics.horizontalAdvance("FREE")
            w, h = text_w + 8, 14
            pm = QPixmap(w, h)
            pm.fill(Qt.GlobalColor.transparent)

            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor("#4CAF50"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, w, h, 3, 3)

            p.setPen(QColor("#ffffff"))
            p.setFont(font)
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "FREE")
            p.end()

            cls._free_pm = pm
        return cls._free_pm

    def __init__(self, parent=None):
        super().__init__(parent)
        self.presets_meta = {}

    def set_presets_meta(self, presets_meta):
        self.presets_meta = {p.id: p for p in presets_meta}

    def paint(self, painter, option, index):
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        preset_id = index.data(Qt.ItemDataRole.UserRole)
        text = index.data()

        if preset_id and preset_id in self.presets_meta:
            preset = self.presets_meta[preset_id]
            pricing = preset.pricing
        else:
            pricing = ""

        dollar_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        ascent = QFontMetrics(dollar_font).ascent()

        x = option.rect.x() + 4
        y = option.rect.y() + (option.rect.height() - 16) // 2

        if pricing == "free":
            painter.drawPixmap(x, y, self._free_pixmap())
            x += self._free_pixmap().width() + 6

        elif pricing == "paid":
            painter.setPen(QColor("#FFC107"))
            painter.setFont(dollar_font)
            painter.drawText(x, y + ascent, "$")
            x += 12

        elif pricing == "mixed":
            painter.drawPixmap(x, y, self._free_pixmap())
            x += self._free_pixmap().width() + 4

            painter.setPen(QColor("#666"))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(x, y + 10, "/")
            x += 8

            painter.setPen(QColor("#FFC107"))
            painter.setFont(dollar_font)
            painter.drawText(x, y + ascent, "$")
            x += 12

        painter.setPen(option.palette.color(
            QPalette.ColorRole.HighlightedText
            if option.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        ))
        painter.setFont(option.font)
        txt_rect = option.rect.adjusted(x - option.rect.x(), 0, -4, 0)
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        return sz.expandedTo(QSize(140, 24))


class CustomPresetListItem(QListWidgetItem):
    def __init__(self, preset_id, name, has_changes=False):
        super().__init__()
        self.preset_id = preset_id
        self.base_name = name
        self.has_changes = has_changes
        self.update_display()

    def update_changes_indicator(self, has_changes):
        self.has_changes = has_changes
        self.update_display()

    def update_display(self):
        display_text = self.base_name
        if self.has_changes:
            display_text = f"{self.base_name}   *"
        self.setText(display_text)


class LabeledLineEditRow(QWidget):
    def __init__(self, label: str, *, password: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._base_label = str(label)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        self.label = QLabel(self._base_label)
        self.label.setMinimumWidth(140)
        self.label.setMaximumWidth(140)
        self.label.setWordWrap(True)

        self.edit = QLineEdit()
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)

        lay.addWidget(self.label)
        lay.addWidget(self.edit, 1)

        self._dirty = False

    def set_text(self, s: str) -> None:
        self.edit.setText(str(s or ""))

    def text(self) -> str:
        return self.edit.text()

    def set_enabled(self, enabled: bool) -> None:
        self.edit.setEnabled(bool(enabled))
        self.label.setEnabled(bool(enabled))

    def set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        if dirty:
            self.label.setText(f"{self._base_label}*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(self._base_label)
            self.label.setStyleSheet("")


class LabeledTextEditRow(QWidget):
    def __init__(self, label: str, *, parent: QWidget | None = None):
        super().__init__(parent)
        self._base_label = str(label)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)

        self.label = QLabel(self._base_label)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)

        self.edit = QTextEdit()
        self.edit.setMinimumHeight(70)
        lay.addWidget(self.edit)

        self._dirty = False

    def set_text(self, s: str) -> None:
        self.edit.setPlainText(str(s or ""))

    def text(self) -> str:
        return self.edit.toPlainText()

    def set_enabled(self, enabled: bool) -> None:
        self.edit.setEnabled(bool(enabled))
        self.label.setEnabled(bool(enabled))

    def set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        if dirty:
            self.label.setText(f"{self._base_label}*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(self._base_label)
            self.label.setStyleSheet("")

class LabeledComboRow(QWidget):
    def __init__(self, label: str, *, parent: QWidget | None = None):
        super().__init__(parent)
        self._base_label = str(label)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        self.label = QLabel(self._base_label)
        self.label.setMinimumWidth(140)
        self.label.setMaximumWidth(140)
        self.label.setWordWrap(True)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(10)
        try:
            self.combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        except Exception:
            pass

        lay.addWidget(self.label)
        lay.addWidget(self.combo, 1)

        self._dirty = False

    def set_items(self, items: list[tuple[str, object]]) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for text, data in items:
            # keep long text, but it will be elided
            self.combo.addItem(str(text), data)
        self.combo.blockSignals(False)

    def set_current_by_data(self, data: object) -> None:
        self.combo.blockSignals(True)
        idx = self.combo.findData(data)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    def current_data(self) -> object:
        return self.combo.currentData()

    def set_enabled(self, enabled: bool) -> None:
        self.combo.setEnabled(bool(enabled))
        self.label.setEnabled(bool(enabled))

    def set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        if dirty:
            self.label.setText(f"{self._base_label}*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(self._base_label)
            self.label.setStyleSheet("")