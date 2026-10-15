from copy import deepcopy
from html import escape

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from localization.live import register, tr_set
from styles.theme import THEME
from ui.widgets.tr_combobox import TRQComboBox
from utils import _


def _render_help(browser):
    browser.setPlainText(str(_(browser.property("helpRu") or "", browser.property("helpEn") or "")))


def _tooltip(text):
    return "<qt>" + escape(text).replace("\n", "<br>") + "</qt>"


def _render_combo_tooltips(combo):
    catalog = combo.property("helpCatalog") or {}
    for index in range(combo.count()):
        ru, en = catalog.get(str(combo.itemData(index)), ("", ""))
        combo.setItemData(index, _tooltip(str(_(ru, en))), Qt.ItemDataRole.ToolTipRole)


class MessageProcessingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        tr_set(self, "Обработка сообщений", "Message processing", "setWindowTitle")
        self.setModal(True)
        self.setMinimumWidth(660)
        self.resize(740, 570)
        self._catalog = {}
        self._available = []
        self._base = []
        self._current = []
        self._initial = []
        self.setObjectName("MessageProcessingDialog")
        self.setStyleSheet(f"""
            QDialog#MessageProcessingDialog {{ background: {THEME['bg_root']}; }}
            QFrame#ProcessingStep {{ background: {THEME['card_alt_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}
            QFrame#ProcessingStep[selected="true"] {{ border-color: {THEME['accent']}; }}
            QFrame#ProcessingStep QLabel {{ background: transparent; border: none; padding: 0; }}
            QLabel#ProcessingDescription {{ color: {THEME['muted']}; font-size: 12px; font-weight: normal; }}
            QLabel#ProcessingTitle {{ color: {THEME['text']}; font-size: 13px; font-weight: 600; }}
            QTextBrowser#ProcessingHelp {{ background: {THEME['card_alt_bg']}; color: {THEME['text']}; border: 1px solid {THEME['panel_border']}; border-radius: 9px; padding: 10px; font-size: 12px; }}
            QListWidget#ProcessingList {{ background: transparent; border: none; padding: 0; }}
            QListWidget#ProcessingList::item {{ padding: 0; margin: 0 0 8px 0; border: none; background: transparent; }}
            QListWidget#ProcessingList::item:selected, QListWidget#ProcessingList::item:hover {{ background: transparent; border: none; }}
            QPushButton#ProcessingSecondary {{ background: {THEME['card_alt_bg']}; color: {THEME['text']}; border: 1px solid {THEME['panel_border']}; border-radius: 9px; padding: 0 14px; }}
            QPushButton#ProcessingSecondary:hover {{ background: {THEME['chip_hover']}; }}
            QPushButton#ProcessingSecondary:disabled {{ color: {THEME['btn_disabled_fg']}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.sliders-h", color=THEME["accent"]).pixmap(26, 26))
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"background: {THEME['chip_hover']}; border-radius: 12px;")
        header.addWidget(icon)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title = tr_set(QLabel(), "Обработка сообщений", "Message processing")
        title.setStyleSheet("font-size: 21px; font-weight: 600;")
        copy.addWidget(title)
        hint = tr_set(
            QLabel(),
            "Шаги выполняются сверху вниз перед отправкой сообщений.",
            "Steps run from top to bottom before messages are sent.",
        )
        hint.setObjectName("ProcessingDescription")
        hint.setWordWrap(True)
        copy.addWidget(hint)
        header.addLayout(copy, 1)
        layout.addLayout(header)
        add_row = QHBoxLayout()
        self.combo = TRQComboBox()
        self.combo.setMinimumHeight(40)
        self.add_button = self._button("Добавить шаг", "Add step", "fa5s.plus")
        self.add_button.clicked.connect(self._on_add)
        add_row.addWidget(self.combo, 1)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)
        help_header = tr_set(QLabel(), "Пояснение выбранного шага", "Selected step explained")
        help_header.setObjectName("ProcessingTitle")
        layout.addWidget(help_header)
        self.help_text = QTextBrowser()
        self.help_text.setObjectName("ProcessingHelp")
        self.help_text.setMinimumHeight(150)
        self.help_text.setMaximumHeight(190)
        self.help_text.setOpenLinks(False)
        tr_set(self.help_text, "Пояснение выбранного шага", "Selected step explained", "setAccessibleName")
        register(self.help_text, _render_help)
        register(self.combo, _render_combo_tooltips)
        self.combo.currentIndexChanged.connect(self._show_candidate_help)
        self.combo.highlighted.connect(self._show_candidate_help)
        layout.addWidget(self.help_text)
        list_header = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setProperty("stepCount", 0)
        register(
            self.count_label,
            lambda label: label.setText(
                str(
                    _("Порядок обработки · {count}", "Processing order · {count}")
                ).format(count=label.property("stepCount") or 0)
            ),
        )
        list_header.addWidget(self.count_label, 1)
        self.up_button = self._icon_button(
            "fa5s.arrow-up", "Переместить выше", "Move up", lambda: self._move(-1)
        )
        self.down_button = self._icon_button(
            "fa5s.arrow-down", "Переместить ниже", "Move down", lambda: self._move(1)
        )
        self.remove_button = self._icon_button(
            "fa5s.trash-alt", "Удалить шаг", "Remove step", self._on_remove
        )
        for button in (self.up_button, self.down_button, self.remove_button):
            list_header.addWidget(button)
        layout.addLayout(list_header)
        self.list = QListWidget()
        self.list.setObjectName("ProcessingList")
        self.list.setSpacing(0)
        self.list.currentRowChanged.connect(self._sync_selection)
        self.list.setMinimumHeight(110)
        layout.addWidget(self.list, 1)
        self.empty_label = tr_set(
            QLabel(),
            "Дополнительная обработка отключена. Сообщения отправляются без преобразований.",
            "Extra processing is disabled. Messages are sent without transformations.",
        )
        self.empty_label.setObjectName("ProcessingDescription")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        footer = QHBoxLayout()
        self.reset_button = self._button(
            "По умолчанию", "Restore defaults", "fa5s.undo", secondary=True
        )
        self.reset_button.clicked.connect(self._on_reset)
        footer.addWidget(self.reset_button)
        footer.addStretch(1)
        cancel = self._button("Отмена", "Cancel", secondary=True)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.apply_button = self._button("Применить", "Apply", "fa5s.check")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.accept)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)

    def _button(self, ru, en, icon=None, *, secondary=False):
        button = tr_set(QPushButton(), ru, en)
        button.setFixedHeight(38)
        button.setAutoDefault(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if secondary:
            button.setObjectName("ProcessingSecondary")
        if icon:
            button.setIcon(qta.icon(icon, color=THEME["text"]))
        return button

    def _icon_button(self, icon, ru, en, callback):
        button = self._button("", "", icon, secondary=True)
        button.setFixedWidth(36)
        button.setStyleSheet("padding: 0;")
        tr_set(button, ru, en, "setToolTip")
        tr_set(button, ru, en, "setAccessibleName")
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _steps(value):
        return deepcopy(
            [
                item
                for item in (value or [])
                if isinstance(item, dict) and item.get("id")
            ]
        )

    def apply_payload(self, payload):
        self._catalog = {
            str(entry["id"]): dict(entry)
            for entry in payload.get("transform_catalog", [])
            if isinstance(entry, dict) and entry.get("id")
        }
        self._available = list(
            dict.fromkeys(
                str(value)
                for value in payload.get("available_ids", [])
                if str(value).strip()
            )
        )
        self._base = self._steps(payload.get("base_transforms"))
        current = payload.get("current_transforms")
        self._current = self._steps(
            current if isinstance(current, list) else self._base
        )
        self._initial = deepcopy(self._current)
        self._reload(0)

    def _labels(self, transform_id):
        entry = self._catalog.get(transform_id, {})
        title = str(entry.get("title") or transform_id.replace("_", " "))
        ru = str(entry.get("title_ru") or title)
        description = str(entry.get("description") or "")
        return ru, title, str(entry.get("description_ru") or description), description

    def _help_labels(self, transform_id):
        ru, en, short_ru, short_en = self._labels(transform_id)
        entry = self._catalog.get(transform_id, {})
        return (
            f"{ru}\n\n{entry.get('help_ru') or entry.get('help') or short_ru}",
            f"{en}\n\n{entry.get('help') or short_en}",
        )

    def _show_help(self, transform_id):
        ru, en = self._help_labels(str(transform_id)) if transform_id else ("", "")
        self.help_text.setProperty("helpRu", ru)
        self.help_text.setProperty("helpEn", en)
        _render_help(self.help_text)
        self.help_text.verticalScrollBar().setValue(0)

    def _show_candidate_help(self, index):
        self._show_help(self.combo.itemData(index))

    def _reload(self, selection=0):
        self.list.blockSignals(True)
        self.list.clear()
        for index, step in enumerate(self._current):
            ru, en, hint_ru, hint_en = self._labels(str(step["id"]))
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 78))
            self.list.addItem(item)
            card = QFrame()
            card.setObjectName("ProcessingStep")
            help_ru, help_en = self._help_labels(str(step["id"]))
            tr_set(card, _tooltip(help_ru), _tooltip(help_en), "setToolTip")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 10, 14, 10)
            row.setSpacing(14)
            number = QLabel(str(index + 1))
            number.setFixedWidth(22)
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setStyleSheet(
                f"color: {THEME['accent']}; font-size: 17px; font-weight: 600;"
            )
            row.addWidget(number)
            text = QVBoxLayout()
            text.setSpacing(4)
            title = tr_set(QLabel(), ru, en)
            title.setObjectName("ProcessingTitle")
            text.addWidget(title)
            description = tr_set(QLabel(), hint_ru, hint_en)
            description.setObjectName("ProcessingDescription")
            description.setWordWrap(True)
            description.setVisible(bool(hint_ru or hint_en))
            text.addWidget(description)
            row.addLayout(text, 1)
            self.list.setItemWidget(item, card)
        self.list.setCurrentRow(min(selection, len(self._current) - 1))
        self.list.blockSignals(False)
        selected = self.combo.currentData()
        used = {str(step["id"]) for step in self._current}
        items = [
            (self._labels(tid)[0], self._labels(tid)[1], tid)
            for tid in self._available
            if tid not in used
        ]
        self.combo.set_items(items, current=selected)
        self.combo.setProperty("helpCatalog", {
            tid: self._help_labels(tid) for tid in self._available
        })
        _render_combo_tooltips(self.combo)
        self.combo.setEnabled(bool(items))
        self.add_button.setEnabled(bool(items))
        self.empty_label.setVisible(not self._current)
        self.list.setVisible(bool(self._current))
        self.count_label.setProperty("stepCount", len(self._current))
        self.count_label.setText(
            str(_("Порядок обработки · {count}", "Processing order · {count}")).format(
                count=len(self._current)
            )
        )
        self.reset_button.setEnabled(self._current != self._base)
        self.apply_button.setEnabled(self._current != self._initial)
        self.list.setMinimumHeight(max(86, min(len(self._current), 3) * 86))
        self.resize(self.width(), 480 + max(100, min(len(self._current), 3) * 86))
        self._sync_selection()

    def _sync_selection(self, *_args):
        selected = self.list.currentRow()
        self.up_button.setEnabled(selected > 0)
        self.down_button.setEnabled(0 <= selected < len(self._current) - 1)
        self.remove_button.setEnabled(0 <= selected < len(self._current))
        for index in range(self.list.count()):
            card = self.list.itemWidget(self.list.item(index))
            card.setProperty("selected", index == selected)
            card.style().unpolish(card)
            card.style().polish(card)
        transform_id = self._current[selected]["id"] if 0 <= selected < len(self._current) else self.combo.currentData()
        self._show_help(transform_id)

    def _on_add(self):
        transform_id = self.combo.currentData()
        if transform_id:
            self._current.append({"id": str(transform_id)})
            self._reload(len(self._current) - 1)

    def _on_remove(self):
        selected = self.list.currentRow()
        if 0 <= selected < len(self._current):
            self._current.pop(selected)
            self._reload(selected)

    def _move(self, delta):
        selected = self.list.currentRow()
        target = selected + delta
        if 0 <= selected < len(self._current) and 0 <= target < len(self._current):
            self._current[selected], self._current[target] = (
                self._current[target],
                self._current[selected],
            )
            self._reload(target)

    def _on_reset(self):
        self._current = deepcopy(self._base)
        self._reload(0)

    def transforms(self):
        return deepcopy(self._current)
