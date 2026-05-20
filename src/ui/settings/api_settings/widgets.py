from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QPixmap, QColor, QFont, QFontMetrics, QPalette
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QStyledItemDelegate, QStyle, QListWidgetItem, QComboBox, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QTextEdit, QToolButton, QPushButton, QFrame
)
import qtawesome as qta


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


class FallbackRow(QWidget):
    """
    One fallback chain entry: preset combo + optional model override + reorder/remove buttons.
    """
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)
    move_up_requested = pyqtSignal(object)
    move_down_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)

        self.preset_combo = QComboBox()
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset_combo.setMinimumContentsLength(8)
        try:
            self.preset_combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        except Exception:
            pass

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("model (optional)")
        self.model_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.up_btn = QToolButton()
        self.up_btn.setIcon(qta.icon("fa5s.arrow-up", color="#e6e6e6"))
        self.up_btn.setFixedSize(22, 22)
        self.up_btn.setIconSize(QSize(11, 11))
        self.up_btn.setAutoRaise(True)

        self.down_btn = QToolButton()
        self.down_btn.setIcon(qta.icon("fa5s.arrow-down", color="#e6e6e6"))
        self.down_btn.setFixedSize(22, 22)
        self.down_btn.setIconSize(QSize(11, 11))
        self.down_btn.setAutoRaise(True)

        self.remove_btn = QToolButton()
        self.remove_btn.setIcon(qta.icon("fa5s.times", color="#e26e9e"))
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.setIconSize(QSize(11, 11))
        self.remove_btn.setAutoRaise(True)
        self.remove_btn.setToolTip("Remove fallback")

        lay.addWidget(self.preset_combo, 2)
        lay.addWidget(self.model_edit, 2)
        lay.addWidget(self.up_btn)
        lay.addWidget(self.down_btn)
        lay.addWidget(self.remove_btn)

        self.preset_combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.model_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.remove_btn.clicked.connect(lambda *_: self.remove_requested.emit(self))
        self.up_btn.clicked.connect(lambda *_: self.move_up_requested.emit(self))
        self.down_btn.clicked.connect(lambda *_: self.move_down_requested.emit(self))

    def populate_presets(self, items) -> None:
        cur = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for label, pid in items:
            self.preset_combo.addItem(str(label), int(pid))
        if cur is not None:
            idx = self.preset_combo.findData(cur)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

    def set_value(self, preset_id: int, model: str) -> None:
        self.preset_combo.blockSignals(True)
        self.model_edit.blockSignals(True)
        try:
            idx = self.preset_combo.findData(int(preset_id))
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        except Exception:
            pass
        self.model_edit.setText(str(model or ""))
        self.preset_combo.blockSignals(False)
        self.model_edit.blockSignals(False)

    def get_value(self):
        pid = self.preset_combo.currentData()
        if pid is None:
            return None
        try:
            pid_int = int(pid)
        except Exception:
            return None
        return {"preset_id": pid_int, "model": str(self.model_edit.text() or "").strip()}


class FallbackChainEditor(QWidget):
    """
    Vertical list of FallbackRow + Add button. Emits changed on any mutation.
    """
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._available_presets = []
        self._self_preset_id = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        hint = QLabel(
            "Если основной провайдер недоступен, запросы пойдут по этой цепочке сверху вниз. "
            "Поле model опционально — если пусто, используется модель пресета."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #bfbfbf; font-size: 11px;")
        outer.addWidget(hint)

        self._rows_container = QFrame()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_container)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self.add_btn = QPushButton("+ Добавить фолбэк")
        self.add_btn.setIcon(qta.icon("fa5s.plus", color="#3498db"))
        self.add_btn.clicked.connect(lambda *_: self._on_add_clicked())
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

    def set_self_preset_id(self, pid) -> None:
        try:
            self._self_preset_id = int(pid) if pid else None
        except Exception:
            self._self_preset_id = None

    def set_available_presets(self, items) -> None:
        self._available_presets = [(str(lbl), int(pid)) for lbl, pid in items if pid]
        for r in self._iter_rows():
            r.populate_presets(self._available_presets)

    def _iter_rows(self):
        for i in range(self._rows_layout.count()):
            w = self._rows_layout.itemAt(i).widget()
            if isinstance(w, FallbackRow):
                yield w

    def _add_row(self, value=None) -> FallbackRow:
        row = FallbackRow(self._rows_container)
        row.populate_presets(self._available_presets)
        if value:
            try:
                row.set_value(int(value.get("preset_id")), str(value.get("model") or ""))
            except Exception:
                pass
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_row_remove)
        row.move_up_requested.connect(self._on_row_move_up)
        row.move_down_requested.connect(self._on_row_move_down)
        self._rows_layout.addWidget(row)
        return row

    def _on_add_clicked(self):
        default_pid = None
        for _lbl, pid in self._available_presets:
            if self._self_preset_id is None or pid != self._self_preset_id:
                default_pid = pid
                break
        if default_pid is None and self._available_presets:
            default_pid = self._available_presets[0][1]
        if default_pid:
            self._add_row({"preset_id": default_pid, "model": ""})
        else:
            self._add_row()
        self.changed.emit()

    def _on_row_changed(self):
        self.changed.emit()

    def _on_row_remove(self, row):
        if isinstance(row, FallbackRow):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
            self.changed.emit()

    def _on_row_move_up(self, row):
        idx = self._rows_layout.indexOf(row)
        if idx <= 0:
            return
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(idx - 1, row)
        self.changed.emit()

    def _on_row_move_down(self, row):
        idx = self._rows_layout.indexOf(row)
        if idx < 0 or idx >= self._rows_layout.count() - 1:
            return
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(idx + 1, row)
        self.changed.emit()

    def clear(self) -> None:
        rows = list(self._iter_rows())
        for r in rows:
            self._rows_layout.removeWidget(r)
            r.setParent(None)
            r.deleteLater()

    def set_value(self, fallbacks) -> None:
        self.clear()
        if not isinstance(fallbacks, list):
            return
        for fb in fallbacks:
            if isinstance(fb, dict):
                self._add_row({
                    "preset_id": fb.get("preset_id", fb.get("id")) or 0,
                    "model": str(fb.get("model") or ""),
                })

    def get_value(self):
        out = []
        for r in self._iter_rows():
            v = r.get_value()
            if v and v.get("preset_id"):
                out.append(v)
        return out


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