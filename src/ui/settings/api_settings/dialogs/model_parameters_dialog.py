from __future__ import annotations

from copy import deepcopy
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QListWidget,
    QPushButton, QLineEdit, QComboBox, QTextEdit, QDialogButtonBox, QTabWidget,
    QWidget, QMessageBox,
)
import qtawesome as qta

import localization
from localization.live import tr_set, register
from model_settings.schema import localized_text
from styles.theme import THEME
from utils import _


class ModelParametersDialog(QDialog):
    """Edit parameter declarations without changing the preset's API protocol."""

    def __init__(self, definition, parent=None, *, validate_definition):
        super().__init__(parent)
        self._definition = deepcopy(definition)
        self._validate_definition = validate_definition
        self._selected = -1
        self._loading = False
        self._last_tab = 0
        tr_set(self, "Настроить параметры", "Customize parameters", "setWindowTitle")
        self.resize(820, 650)
        layout = QVBoxLayout(self)
        note = tr_set(QLabel(), "Формат параметров определяется подключением. Здесь можно добавлять и изменять поля только этого пресета.", "The connection determines the parameter format. Add and edit fields for this preset here.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        fields_page = QWidget()
        fields_layout = QHBoxLayout(fields_page)
        fields_layout.setContentsMargins(0, 12, 0, 0)
        sidebar = QVBoxLayout()
        self.field_list = QListWidget()
        self.field_list.setObjectName("ModelParameterFields")
        self.field_list.setMinimumWidth(200)
        sidebar.addWidget(self.field_list, 1)
        actions = QHBoxLayout()
        add = tr_set(QPushButton(), "Добавить параметр", "Add parameter")
        add.setIcon(qta.icon("fa5s.plus", color=THEME["muted"]))
        remove = tr_set(QPushButton(), "Удалить", "Remove")
        remove.setObjectName("ApiCheckButton")
        remove.setIcon(qta.icon("fa5s.trash-alt", color=THEME["muted"]))
        actions.addWidget(add)
        actions.addWidget(remove)
        sidebar.addLayout(actions)
        fields_layout.addLayout(sidebar, 1)
        self.field_editor = QWidget()
        form = QFormLayout(self.field_editor)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setSpacing(12)
        self.title = QLineEdit()
        self.path = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["number", "integer", "boolean", "string", "array", "object"])
        self.default = QLineEdit()
        self.minimum = QLineEdit()
        self.maximum = QLineEdit()
        self.options = QLineEdit()
        self.description = QTextEdit()
        self.description.setMaximumHeight(100)
        for editor, ru, en in (
            (self.title, "Название", "Name"),
            (self.path, "Ключ параметра", "Parameter key"),
            (self.kind, "Тип значения", "Value type"),
            (self.default, "Значение по умолчанию", "Default value"),
            (self.minimum, "Минимум", "Minimum"),
            (self.maximum, "Максимум", "Maximum"),
            (self.options, "Допустимые значения (JSON)", "Allowed values (JSON)"),
            (self.description, "Описание", "Description"),
        ):
            if isinstance(editor, (QLineEdit, QComboBox)):
                editor.setMinimumHeight(36)
            form.addRow(tr_set(QLabel(), ru, en), editor)
        tr_set(self.path, "Вложенные ключи разделяются точкой. Для Google префикс generationConfig добавляется автоматически.", "Separate nested keys with a dot. Google's generationConfig prefix is added automatically.", "setToolTip")
        self.options.setPlaceholderText('["low", "medium", "high"]')
        tr_set(self.default, "Для массива и объекта введите JSON; для логического значения — true или false.", "Enter JSON for arrays and objects; true or false for booleans.", "setToolTip")
        fields_layout.addWidget(self.field_editor, 2)
        self.tabs.addTab(fields_page, _("Параметры", "Parameters"))
        self.json_editor = QTextEdit()
        self.tabs.addTab(self.json_editor, "JSON")
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        tr_set(buttons.button(QDialogButtonBox.StandardButton.Save), "Сохранить", "Save")
        tr_set(buttons.button(QDialogButtonBox.StandardButton.Cancel), "Отмена", "Cancel")
        layout.addWidget(buttons)
        self.field_list.currentRowChanged.connect(self._select)
        self.tabs.currentChanged.connect(self._switch_tab)
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.kind.currentTextChanged.connect(self._sync_kind)
        self._reload(0)
        register(self, lambda dialog: dialog._refresh_titles())

    def _refresh_titles(self):
        self.tabs.setTabText(0, _("Параметры", "Parameters"))
        language = localization._current_language()
        for index, field in enumerate(self._definition["fields"]):
            self.field_list.item(index).setText(localized_text(field.get("title"), language) or field["id"])

    def _sync_kind(self):
        numeric = self.kind.currentText() in {"number", "integer"}
        self.minimum.setEnabled(numeric)
        self.maximum.setEnabled(numeric)

    def _reload(self, selected):
        self._loading = True
        self.field_list.clear()
        language = localization._current_language()
        self._editor_language = language.lower()
        for field in self._definition["fields"]:
            self.field_list.addItem(localized_text(field.get("title"), language) or field["id"])
        self._selected = -1
        self._loading = False
        self.field_list.setCurrentRow(min(selected, self.field_list.count() - 1))
        if not self.field_list.count():
            self.field_editor.setEnabled(False)

    def _select(self, row):
        if self._loading:
            return
        if not self._try_commit():
            self._loading = True
            self.field_list.setCurrentRow(self._selected)
            self._loading = False
            return
        self._selected = row
        self.field_editor.setEnabled(row >= 0)
        if row < 0:
            return
        field = self._definition["fields"][row]
        language = localization._current_language()
        self._editor_language = language.lower()
        self.title.setText(localized_text(field.get("title"), language) or field["id"])
        self.description.setPlainText(localized_text(field.get("description"), language))
        path = field["path"]
        if self._definition["dialect"] == "gemini_generate_content" and path[0] == "generationConfig":
            path = path[1:]
        self.path.setText(".".join(path))
        self.kind.setCurrentText(field["type"])
        value = field["default"]
        self.default.setText(value if field["type"] == "string" else json.dumps(value, ensure_ascii=False))
        self.minimum.setText(str(field.get("minimum", "")))
        self.maximum.setText(str(field.get("maximum", "")))
        self.options.setText(json.dumps(field["enum"], ensure_ascii=False) if "enum" in field else "")
        self._sync_kind()

    def _commit(self):
        if self._selected < 0:
            return
        field = deepcopy(self._definition["fields"][self._selected])
        language = self._editor_language
        for key, value in (("title", self.title.text()), ("description", self.description.toPlainText())):
            if localized_text(field.get(key), language) != value:
                labels = deepcopy(field.get(key)) if isinstance(field.get(key), dict) else {}
                labels[language] = value
                field[key] = labels
        field["type"] = self.kind.currentText()
        field["default"] = self.default.text() if field["type"] == "string" else json.loads(self.default.text())
        path = self.path.text().strip().split(".")
        if self._definition["dialect"] == "gemini_generate_content" and path[0] != "generationConfig":
            path.insert(0, "generationConfig")
        field["path"] = path
        for key, editor in (("minimum", self.minimum), ("maximum", self.maximum), ("enum", self.options)):
            if editor.isEnabled() and editor.text().strip():
                field[key] = json.loads(editor.text())
            else:
                field.pop(key, None)
        if field["type"] not in {"number", "integer"}:
            field.pop("special_values", None)
        if field["type"] not in {"string", "array"}:
            field.pop("min_length", None)
            field.pop("max_length", None)
        self._definition["fields"][self._selected] = field
        self.field_list.item(self._selected).setText(self.title.text() or field["id"])

    def _try_commit(self):
        try:
            self._commit()
            return True
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, _("Ошибка описания настроек", "Settings definition error"), str(exc))
            return False

    def _add(self):
        if not self._try_commit():
            return
        ids = {field["id"] for field in self._definition["fields"]}
        number = 1
        while f"parameter_{number}" in ids:
            number += 1
        identifier = f"parameter_{number}"
        path = [identifier]
        if self._definition["dialect"] == "gemini_generate_content":
            path.insert(0, "generationConfig")
        self._definition["fields"].append({"id": identifier, "path": path, "type": "number", "default": 1.0, "enabled_by_default": False})
        self._reload(len(self._definition["fields"]) - 1)
        self.path.setFocus(Qt.FocusReason.OtherFocusReason)
        self.path.selectAll()

    def _remove(self):
        if self._selected >= 0:
            row = self._selected
            self._definition["fields"].pop(row)
            self._reload(row)

    def _switch_tab(self, index):
        if index == self._last_tab:
            return
        try:
            if index == 1:
                self._commit()
                self.json_editor.setPlainText(json.dumps(self._definition, ensure_ascii=False, indent=2))
            else:
                definition = json.loads(self.json_editor.toPlainText())
                if not isinstance(definition, dict) or not isinstance(definition.get("fields"), list):
                    raise ValueError(_("Требуется JSON-объект.", "A JSON object is required."))
                if definition.get("dialect") != self._definition["dialect"]:
                    raise ValueError(_("Формат параметров определяется подключением.", "The connection determines the parameter format."))
                if any(not isinstance(field, dict) or not all(key in field for key in ("id", "path", "type", "default")) or not isinstance(field["path"], list) or not field["path"] for field in definition["fields"]):
                    raise ValueError(_("Некорректное описание параметра.", "Invalid parameter definition."))
                self._definition = self._validate_definition(definition)
                self._reload(0)
            self._last_tab = index
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, _("Ошибка описания настроек", "Settings definition error"), str(exc))
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self._last_tab)
            self.tabs.blockSignals(False)

    def _save(self):
        if self.tabs.currentIndex() == 1 or self._try_commit():
            self.accept()

    def definition(self):
        if self.tabs.currentIndex() == 1:
            return json.loads(self.json_editor.toPlainText())
        return deepcopy(self._definition)
