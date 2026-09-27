from __future__ import annotations


from PyQt6.QtCore import Qt, QSize, QRect, QTimer, QPointF
from PyQt6.QtGui import QPainter, QPixmap, QColor, QFont, QFontMetrics, QPalette
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QStyledItemDelegate, QStyle, QListWidget, QListWidgetItem, QComboBox, QSizePolicy, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QTextEdit, QToolButton, QPushButton, QFrame, QCheckBox, QAbstractItemView, QMenu
)
import qtawesome as qta

from utils import _
from localization.live import tr_set, register_if_tr, register
from styles.theme import THEME
from ui.provider_icons import provider_icon
from PyQt6.QtWidgets import QToolTip


def _label_translation(text):
    ru = getattr(text, "tr_ru", None)
    return str(_(ru, getattr(text, "tr_en", ""))) if ru is not None else str(text)


class ProviderDelegate(QStyledItemDelegate):
    _free_pm = None
    _local_pm = None
    _ru_pm = None

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

    @classmethod
    def _local_pixmap(cls):
        if cls._local_pm is None:
            font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            metrics = QFontMetrics(font)
            text_w = metrics.horizontalAdvance("LOCAL")
            w, h = text_w + 10, 14
            pm = QPixmap(w, h)
            pm.fill(Qt.GlobalColor.transparent)

            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor("#4FC3F7"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, w, h, 3, 3)

            p.setPen(QColor("#0b1220"))
            p.setFont(font)
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "LOCAL")
            p.end()

            cls._local_pm = pm
        return cls._local_pm

    @classmethod
    def _ru_pixmap(cls):
        if cls._ru_pm is None:
            font = QFont("Segoe UI", 7, QFont.Weight.Bold)
            metrics = QFontMetrics(font)
            text_w = metrics.horizontalAdvance("RU")
            w, h = text_w + 10, 14
            pm = QPixmap(w, h)
            pm.fill(Qt.GlobalColor.transparent)

            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor("#2D66C3"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(0, 0, w, h, 3, 3)

            p.setPen(QColor("#ffffff"))
            p.setFont(font)
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "RU")
            p.end()

            cls._ru_pm = pm
        return cls._ru_pm

    def __init__(self, parent=None):
        super().__init__(parent)
        self.presets_meta = {}

    def set_presets_meta(self, presets_meta):
        self.presets_meta = {p.id: p for p in presets_meta}

    def _badges(self, index):
        preset = self.presets_meta.get(index.data(Qt.ItemDataRole.UserRole))
        pricing = getattr(preset, "pricing", "")
        kind = getattr(preset, "badge_kind", "")
        badges = []
        if kind == "local":
            badges.append(self._local_pixmap())
        elif kind == "ru":
            badges.append(self._ru_pixmap())
        if kind != "local":
            if pricing in ("free", "mixed"):
                badges.append(self._free_pixmap())
            if pricing in ("paid", "mixed"):
                badges.append(qta.icon("fa5s.dollar-sign", color="#FFC107").pixmap(10, 14))
        return badges

    def paint(self, painter, option, index):
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, option.palette.highlight() if selected else option.palette.base())
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        x = option.rect.left() + 10
        if icon is not None:
            icon.paint(painter, QRect(x, option.rect.center().y() - 10, 20, 20))
        x += 30
        badges = self._badges(index)
        reserved = sum(badge.width() + 6 for badge in badges)
        metrics = QFontMetrics(option.font)
        text = metrics.elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight,
                                  max(0, option.rect.right() - x - reserved - 10))
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        painter.drawText(QRect(x, option.rect.top(), metrics.horizontalAdvance(text), option.rect.height()), Qt.AlignmentFlag.AlignVCenter, text)
        x += metrics.horizontalAdvance(text) + 6
        for badge in badges:
            painter.drawPixmap(x, option.rect.center().y() - badge.height() // 2, badge)
            x += badge.width() + 6
        painter.restore()

    def sizeHint(self, option, index):
        width = QFontMetrics(option.font).horizontalAdvance(str(index.data() or "")) + 50
        width += sum(badge.width() + 6 for badge in self._badges(index))
        return QSize(width, 32)


class PresetCardDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        item = self.parent().item(index.row())
        rect = option.rect.adjusted(2, 3, -2, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(THEME["accent"] if selected else THEME["bg_root"])
        if selected:
            background.setAlphaF(0.12)
        border = QColor(THEME["accent"] if selected else THEME["muted"])
        if not selected:
            border.setAlphaF(0.18)
        painter.setBrush(background)
        painter.setPen(border)
        painter.drawRoundedRect(rect, 10, 10)
        icon_rect = QRect(rect.left() + 14, rect.center().y() - 13, 26, 26)
        provider_icon(getattr(item, "provider", "")).paint(painter, icon_rect)
        x = rect.left() + 52
        width = max(0, rect.width() - 82)
        font = QFont(option.font)
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(THEME["text"]))
        title = item.base_name + (" *" if item.has_changes else "")
        display_title, title_width, indicator = self._title_layout(rect, font, title, getattr(item, "is_default", False))
        if indicator is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME["success"]))
            painter.drawEllipse(indicator)
            painter.setPen(QColor(THEME["text"]))
        self._draw_text(painter, x, rect.center().y() - 10, display_title)
        font = QFont(option.font)
        painter.setFont(font)
        painter.setPen(QColor(THEME["muted"]))
        text = item.model or str(_("Модель не выбрана", "No model selected"))
        self._draw_text(painter, x, rect.center().y() + 10,
                        QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width))
        qta.icon("fa5s.ellipsis-v", color=THEME["muted"]).paint(
            painter, QRect(rect.right() - 23, rect.center().y() - 9, 14, 18)
        )
        painter.restore()

    @staticmethod
    def _draw_text(painter, x, center_y, text):
        bounds = QFontMetrics(painter.font()).tightBoundingRect(text)
        baseline = center_y - (bounds.top() + bounds.bottom()) / 2
        painter.drawText(QPointF(x, baseline), text)

    @staticmethod
    def _title_layout(rect, font, title, is_default):
        width = max(0, rect.width() - 82 - (18 if is_default else 0))
        metrics = QFontMetrics(font)
        shown = metrics.elidedText(title, Qt.TextElideMode.ElideRight, width)
        indicator = QRect(rect.left() + 52 + metrics.horizontalAdvance(shown) + 6, rect.center().y() - 15, 10, 10) if is_default else None
        return shown, width, indicator

    def sizeHint(self, option, index):
        return QSize(270, 62)

    def helpEvent(self, event, view, option, index):
        rect = option.rect.adjusted(2, 3, -2, -3)
        icon_rect = QRect(rect.left() + 14, rect.center().y() - 13, 26, 26)
        if icon_rect.contains(event.pos()):
            item = view.item(index.row())
            text = getattr(item, "provider_label", "") or str(_("Пользовательский API", "Custom API"))
            QToolTip.showText(event.globalPos(), text, view.viewport(), icon_rect)
            return True
        item = view.item(index.row())
        font = QFont(option.font)
        font.setPixelSize(14)
        font.setBold(True)
        title = item.base_name + (" *" if item.has_changes else "")
        _, _, indicator = self._title_layout(rect, font, title, getattr(item, "is_default", False))
        if indicator is not None and indicator.adjusted(-3, -3, 3, 3).contains(event.pos()):
            QToolTip.showText(event.globalPos(), str(_("По умолчанию", "Default")), view.viewport())
            return True
        QToolTip.hideText()
        return False


class PresetsListWidget(QListWidget):
    """Preset cards with context actions, internal reordering and an empty-state invitation."""

    create_requested = pyqtSignal()
    action_requested = pyqtSignal(str, int)
    order_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setItemDelegate(PresetCardDelegate(self))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)
        # Текст плейсхолдера рисуется в paintEvent (берётся свежим из `_()`),
        # а на смену языка перерисовываем виджет по сигналу.
        try:
            from localization.live import language_changed_signal
            language_changed_signal().connect(self.viewport().update)
        except Exception:
            pass

    @property
    def _placeholder(self) -> str:
        return _("Нажмите, чтобы создать пресет", "Click to create a preset")

    @property
    def _placeholder_hint(self) -> str:
        return _("Кнопка «Добавить пресет» находится сверху", "Use Add preset above")

    def _open_menu(self, position):
        item = self.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        for key, label in (
            ("default", _("Выбрать по умолчанию", "Use by default")),
            ("rename", _("Переименовать", "Rename")),
            ("copy", _("Дублировать", "Duplicate")),
            ("remove", _("Удалить", "Delete")),
        ):
            action = menu.addAction(str(label))
            if key == "default":
                action.setEnabled(not getattr(item, "is_default", False))
            action.triggered.connect(lambda checked=False, k=key, pid=item.preset_id: self.action_requested.emit(k, pid))
        menu.exec(self.viewport().mapToGlobal(position))

    def dropEvent(self, event):
        blocked = self.blockSignals(True)
        try:
            super().dropEvent(event)
        finally:
            self.blockSignals(blocked)
        if event.isAccepted():
            QTimer.singleShot(0, self.order_changed.emit)

    def _is_empty(self) -> bool:
        return self.count() == 0

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._is_empty():
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.viewport().rect().adjusted(12, 12, -12, -12)

        title_font = QFont(self.font())
        title_font.setPointSizeF(max(9.5, self.font().pointSizeF()))
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(214, 156, 188))  # мягкий акцент
        title_rect = rect.adjusted(0, 0, 0, -22)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._placeholder)

        hint_font = QFont(self.font())
        hint_font.setPointSizeF(max(8.0, self.font().pointSizeF() - 1.0))
        painter.setFont(hint_font)
        painter.setPen(QColor(150, 142, 162))
        hint_rect = rect.adjusted(0, 24, 0, 0)
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._placeholder_hint)
        painter.end()

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            if event.pos().x() >= self.visualItemRect(item).right() - 30:
                self._open_menu(event.pos())
                return
        if self._is_empty():
            self.create_requested.emit()
            return
        super().mousePressEvent(event)


class CustomPresetListItem(QListWidgetItem):
    def __init__(self, preset_id, name, has_changes=False, model=""):
        super().__init__()
        self.preset_id = preset_id
        self.base_name = name
        self.model = str(model or "")
        self.has_changes = has_changes
        self.provider = ""
        self.provider_label = ""
        self.is_default = False
        self.setData(Qt.ItemDataRole.UserRole, preset_id)
        self.update_display()

    def update_changes_indicator(self, has_changes):
        self.has_changes = has_changes
        self.update_display()

    def update_display(self):
        display_text = self.base_name
        if self.model:
            display_text = f"{self.base_name} ({self.model})"
        if self.has_changes:
            display_text = f"{display_text}   *"
        self.setText(display_text)


class LabeledLineEditRow(QWidget):
    def __init__(self, label: str, *, password: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._base_label = label

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        self.label = QLabel(self._base_label)
        self.label.setMinimumWidth(140)
        self.label.setMaximumWidth(140)
        self.label.setWordWrap(True)
        # Живая смена языка: если метка пришла из _()/TrStr — регистрируем, чтобы
        # переустанавливалась при смене языка (иначе застывает на языке сборки).
        register_if_tr(self.label, label)
        register(self.label, lambda widget, text=label: widget.setText(
            _label_translation(text) + ("*" if widget.property("dirty") else "")
        ))

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
        self.label.setProperty("dirty", dirty)
        if dirty:
            self.label.setText(_label_translation(self._base_label) + "*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(_label_translation(self._base_label))
            self.label.setStyleSheet("")


class LabeledTextEditRow(QWidget):
    def __init__(self, label: str, *, parent: QWidget | None = None):
        super().__init__(parent)
        self._base_label = label

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)

        self.label = QLabel(self._base_label)
        register(self.label, lambda widget, text=label: widget.setText(
            _label_translation(text) + ("*" if widget.property("dirty") else "")
        ))
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
        self.label.setProperty("dirty", dirty)
        if dirty:
            self.label.setText(_label_translation(self._base_label) + "*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(_label_translation(self._base_label))
            self.label.setStyleSheet("")


class ReserveKeyRow(QWidget):
    """
    Одна строка списка резервных ключей: поле ввода + кнопка показа + кнопка удаления.
    По умолчанию ключ скрыт (Password), кнопка глаза переключает видимость.
    """
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        tr_set(self.key_edit, "API ключ", "API key", "setPlaceholderText")
        self.key_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.eye_btn = QToolButton()
        self.eye_btn.setIcon(qta.icon("fa5s.eye", color=THEME["muted"]))
        self.eye_btn.toggled.connect(lambda on: self.eye_btn.setIcon(qta.icon("fa5s.eye-slash" if on else "fa5s.eye", color=THEME["muted"])))
        self.eye_btn.setCheckable(True)
        self.eye_btn.setFixedWidth(24)
        tr_set(self.eye_btn, "Показать/скрыть ключ", "Show/hide key", "setToolTip")
        self.eye_btn.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )

        self.remove_btn = QToolButton()
        self.remove_btn.setIcon(qta.icon("fa5s.times", color=THEME["accent"]))
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.setIconSize(QSize(11, 11))
        self.remove_btn.setAutoRaise(True)
        tr_set(self.remove_btn, "Удалить ключ", "Remove key", "setToolTip")

        lay.addWidget(self.key_edit, 1)
        lay.addWidget(self.eye_btn)
        lay.addWidget(self.remove_btn)

        self.key_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.remove_btn.clicked.connect(lambda *_: self.remove_requested.emit(self))

    def set_visible(self, visible: bool) -> None:
        self.eye_btn.setChecked(visible)

    def set_value(self, key: str) -> None:
        self.key_edit.blockSignals(True)
        self.key_edit.setText(str(key or ""))
        self.key_edit.blockSignals(False)

    def get_value(self) -> str:
        return str(self.key_edit.text() or "").strip()


class ReserveKeysEditor(QWidget):
    """
    Список резервных ключей: вертикальный список ReserveKeyRow + кнопка добавления.
    Совместим по интерфейсу с прежним текстовым полем: text()/set_text() работают
    со строкой "ключ на строку", поэтому хранение настройки не меняется.
    """
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._section = None
        self._section_base_title = ""
        self._dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        hint = tr_set(QLabel(),
            "Используются по очереди, если основной ключ упёрся в лимит или ошибку. "
            "По одному ключу в строке.",
            "Used in turn when the main key hits a limit or error. One key per row.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #bfbfbf; font-size: 11px;")
        outer.addWidget(hint)

        self.distribute_checkbox = tr_set(QCheckBox(), "Всегда распределять", "Always distribute")
        self.distribute_checkbox.setToolTip(_(
            "Использовать основной и резервные ключи по кругу на каждый запрос "
            "(лимиты всех ключей тратятся одновременно), а не только при сбое.",
            "Use the main and reserve keys in round-robin on every request "
            "(all keys' limits are spent at once), not only on failure."))
        self.distribute_checkbox.toggled.connect(lambda *_: self.changed.emit())
        outer.addWidget(self.distribute_checkbox)

        self._rows_container = QFrame()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_container)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        self.add_btn = tr_set(QPushButton(), "Добавить ключ", "Add key")
        self.add_btn.setIcon(qta.icon("fa5s.plus", color=THEME["text"]))
        self.add_btn.clicked.connect(lambda *_: self._on_add_clicked())
        btn_row.addWidget(self.add_btn)

        self._toggle_all_btn = QToolButton()
        self._toggle_all_btn.setIcon(qta.icon("fa5s.eye", color=THEME["muted"]))
        self._toggle_all_btn.toggled.connect(lambda on: self._toggle_all_btn.setIcon(qta.icon("fa5s.eye-slash" if on else "fa5s.eye", color=THEME["muted"])))
        self._toggle_all_btn.setCheckable(True)
        self._toggle_all_btn.setFixedWidth(24)
        tr_set(self._toggle_all_btn, "Показать/скрыть все ключи", "Show/hide all keys", "setToolTip")
        self._toggle_all_btn.toggled.connect(self._on_toggle_all)
        btn_row.addWidget(self._toggle_all_btn)

        btn_row.addStretch()
        outer.addLayout(btn_row)

    def attach_section(self, section, base_title: str) -> None:
        """Секция-обёртка, заголовок которой получает '*' при наличии изменений."""
        self._section = section
        self._section_base_title = base_title or ""
        register(section.title_label, lambda widget, text=base_title: widget.setText(
            _label_translation(text) + ("*" if widget.property("dirty") else "")
        ))

    def _iter_rows(self):
        for i in range(self._rows_layout.count()):
            w = self._rows_layout.itemAt(i).widget()
            if isinstance(w, ReserveKeyRow):
                yield w

    def _add_row(self, value: str = "") -> ReserveKeyRow:
        row = ReserveKeyRow(self._rows_container)
        row.set_value(value)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_row_remove)
        self._rows_layout.addWidget(row)
        return row

    def _on_add_clicked(self):
        self._add_row("")
        self.changed.emit()

    def _on_row_changed(self):
        self.changed.emit()

    def _on_row_remove(self, row):
        if isinstance(row, ReserveKeyRow):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
            self.changed.emit()

    def _on_toggle_all(self, checked: bool) -> None:
        for row in self._iter_rows():
            row.set_visible(checked)

    def clear(self) -> None:
        for r in list(self._iter_rows()):
            self._rows_layout.removeWidget(r)
            r.setParent(None)
            r.deleteLater()

    def get_keys(self):
        return [v for v in (r.get_value() for r in self._iter_rows()) if v]

    def set_keys(self, keys) -> None:
        self.clear()
        if not isinstance(keys, (list, tuple)):
            keys = []
        for k in keys:
            ks = str(k or "").strip()
            if ks:
                self._add_row(ks)
        if hasattr(self, "count_label"):
            self.count_label.setProperty("keyCount", len(self.get_keys()))
            self.count_label.setText(str(len(self.get_keys())) + str(_(" ключей", " keys")))

    def is_distribute(self) -> bool:
        return bool(self.distribute_checkbox.isChecked())

    def set_distribute(self, value: bool) -> None:
        self.distribute_checkbox.blockSignals(True)
        try:
            self.distribute_checkbox.setChecked(bool(value))
        finally:
            self.distribute_checkbox.blockSignals(False)

    # --- интерфейс, совместимый с прежним LabeledTextEditRow ---
    def text(self) -> str:
        return "\n".join(self.get_keys())

    def set_text(self, s: str) -> None:
        lines = [ln.strip() for ln in str(s or "").splitlines() if ln.strip()]
        self.set_keys(lines)

    def set_enabled(self, enabled: bool) -> None:
        self.setEnabled(bool(enabled))

    def set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        if self._section is not None and hasattr(self._section, "title_label"):
            self._section.title_label.setProperty("dirty", dirty)
            title = _label_translation(self._section_base_title) + ("*" if dirty else "")
            self._section.title_label.setText(title)


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
        tr_set(self.model_edit, "модель (необязательно)", "model (optional)", "setPlaceholderText")
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
        self.remove_btn.setIcon(qta.icon("fa5s.times", color=THEME["accent"]))
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.setIconSize(QSize(11, 11))
        self.remove_btn.setAutoRaise(True)
        tr_set(self.remove_btn, "Удалить резерв", "Remove backup", "setToolTip")

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

        hint = tr_set(QLabel(),
            "Если основной провайдер недоступен, запросы пойдут по этой цепочке сверху вниз. "
            "Поле model опционально — если пусто, используется модель пресета.",
            "If the main provider is unavailable, requests will go down this chain top to bottom. "
            "The model field is optional — if empty, the preset's own model is used.")
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
        self.add_btn = tr_set(QPushButton(), "+ Добавить резерв", "+ Add backup")
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
        self._base_label = label

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)

        self.label = QLabel(self._base_label)
        register(self.label, lambda widget, text=label: widget.setText(
            _label_translation(text) + ("*" if widget.property("dirty") else "")
        ))
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
        self.label.setProperty("dirty", dirty)
        if dirty:
            self.label.setText(_label_translation(self._base_label) + "*")
            self.label.setStyleSheet("color: #f39c12; font-weight: bold;")
        else:
            self.label.setText(_label_translation(self._base_label))
            self.label.setStyleSheet("")
