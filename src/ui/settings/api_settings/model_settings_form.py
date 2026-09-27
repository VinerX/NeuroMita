from __future__ import annotations

from copy import deepcopy
import json

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QLineEdit, QComboBox, QPushButton
import qtawesome as qta

import localization
from localization.live import register, tr_set
from model_settings.schema import SettingsSchema, localized_text
from styles.theme import THEME
from utils import _


_PRESET_NOTE = (
    "Настройки принадлежат этому пресету. Выключенные параметры не отправляются в API.",
    "Settings belong to this preset. Unchecked parameters are omitted from the API request.",
)


def parameter_heading(title, key, path=None):
    layout = QHBoxLayout()
    layout.setSpacing(8)
    layout.addWidget(title)
    label = QLabel(key)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setObjectName("ApiParameterKey")
    label.setToolTip(path or key)
    layout.addWidget(label)
    layout.addStretch(1)
    return layout


def schema_text(value, language):
    language = str(language).lower()
    if isinstance(value, dict):
        value = {key.lower(): text for key, text in value.items()}
    if isinstance(value, dict) and language not in value and value.get("ru"):
        return str(localization.translate_for_language(language, value["ru"], value.get("en", "")))
    return localized_text(value, language)


def issue_text(issue):
    labels = {
        "required": ("Введите значение.", "Enter a value."),
        "integer": ("Требуется целое число.", "An integer is required."),
        "number": ("Требуется число.", "A number is required."),
        "finite": ("Требуется конечное число.", "A finite number is required."),
        "boolean": ("Выберите логическое значение.", "Select a boolean value."),
        "string": ("Требуется строка.", "A string is required."),
        "array": ("Требуется JSON-массив.", "A JSON array is required."),
        "object": ("Требуется JSON-объект.", "A JSON object is required."),
        "enum": ("Выберите допустимое значение.", "Select an allowed value."),
        "unknown": ("Параметр отсутствует в текущем описании настроек.", "The parameter is missing from the current settings definition."),
        "exclusive": ("Эти параметры нельзя отправлять одновременно.", "These parameters cannot be sent together."),
    }
    if issue.code in {"range", "length"}:
        if issue.minimum is None:
            return str(_("Максимум: ", "Maximum: ")) + str(issue.maximum)
        if issue.maximum is None:
            return str(_("Минимум: ", "Minimum: ")) + str(issue.minimum)
        return str(_("Диапазон: ", "Range: ")) + f"{issue.minimum} … {issue.maximum}"
    return str(_(*labels.get(issue.code, labels["number"])))


class ModelSettingsForm(QWidget):
    changed = pyqtSignal()
    import_requested = pyqtSignal()
    export_requested = pyqtSignal()
    edit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._schema = None
        self._document = None
        self.fields = {}
        self.support_fields = {}
        self.orphan_fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        toolbar = QHBoxLayout()
        self.format_label = QLabel()
        self.format_label.setObjectName("ApiSettingsSubtitle")
        toolbar.addWidget(self.format_label, 1)
        for ru, en, icon, signal in (
            ("Импорт JSON", "Import JSON", "fa5s.file-import", self.import_requested),
            ("Экспорт JSON", "Export JSON", "fa5s.file-export", self.export_requested),
            ("Настроить параметры", "Customize parameters", "fa5s.sliders-h", self.edit_requested),
        ):
            button = tr_set(QPushButton(), ru, en)
            button.setObjectName("ApiCheckButton")
            button.setIcon(qta.icon(icon, color=THEME["muted"]))
            button.setMinimumHeight(40)
            button.clicked.connect(signal.emit)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.note = tr_set(QLabel(), *_PRESET_NOTE)
        self.note.setObjectName("ApiSettingsSubtitle")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.schema_description = QLabel()
        self.schema_description.setObjectName("ApiSettingsSubtitle")
        self.schema_description.setWordWrap(True)
        layout.addWidget(self.schema_description)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(0)
        layout.addLayout(self.rows)
        register(self, lambda form: form._refresh_texts())

    def load(self, schema: SettingsSchema, document: dict):
        self._loading = True
        self._schema = schema
        self._document = deepcopy(document)
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.fields.clear()
        self.support_fields.clear()
        self.orphan_fields.clear()
        for spec in schema.fields:
            row = QWidget()
            row.setObjectName("ApiGenerationRow")
            horizontal = QHBoxLayout(row)
            horizontal.setContentsMargins(0, 10, 0, 10)
            horizontal.setSpacing(16)
            labels = QVBoxLayout()
            labels.setSpacing(4)
            title = QLabel()
            description = QLabel()
            description.setObjectName("ApiSettingsSubtitle")
            description.setWordWrap(True)
            labels.addLayout(parameter_heading(title, spec["path"][-1], ".".join(spec["path"])))
            labels.addWidget(description)
            horizontal.addLayout(labels, 1)
            enabled = QCheckBox()
            tr_set(enabled, "Отправлять параметр", "Send parameter", "setToolTip")
            value = document["values"].get(spec["id"], spec["default"])
            if "enum" in spec:
                editor = QComboBox()
                for option in spec["enum"]:
                    editor.addItem(str(option), option)
                index = editor.findData(value)
                if index < 0:
                    editor.addItem(str(value), value)
                    index = editor.count() - 1
                editor.setCurrentIndex(index)
                editor.currentIndexChanged.connect(self._field_changed)
            elif spec["type"] == "boolean":
                editor = tr_set(QCheckBox(), "Вкл", "On")
                editor.setChecked(value is True)
                editor.toggled.connect(self._field_changed)
            else:
                editor = QLineEdit()
                if spec["type"] in {"array", "object"}:
                    value = json.dumps(value, ensure_ascii=False)
                    default = json.dumps(spec["default"], ensure_ascii=False)
                else:
                    default = str(spec["default"])
                editor.setText(str(value))
                editor.setPlaceholderText(default)
                editor.textChanged.connect(self._field_changed)
            editor.setFixedWidth(180)
            editor.setMinimumHeight(40)
            enabled.setChecked(spec["id"] in document["enabled"])
            editor.setEnabled(enabled.isChecked())
            enabled.toggled.connect(editor.setEnabled)
            enabled.toggled.connect(self._field_changed)
            horizontal.addWidget(enabled)
            horizontal.addWidget(editor)
            self.fields[spec["id"]] = (spec, enabled, editor, title, description)
            self.rows.addWidget(row)
        for identifier in document["enabled"]:
            if identifier not in self.fields:
                checkbox = QCheckBox(identifier)
                checkbox.setChecked(True)
                tr_set(checkbox, "Параметр отсутствует в текущем описании настроек.", "The parameter is missing from the current settings definition.", "setToolTip")
                checkbox.toggled.connect(self._field_changed)
                self.orphan_fields[identifier] = checkbox
                self.rows.addWidget(checkbox)
        for key, title, explanation in (
            ("structured_output", ("Нативная JSON-схема", "Native JSON schema"), ("Модель принимает схему ответа через API. Формат ответа приложения задаётся в общих настройках.", "The model accepts a response schema through the API. The application's response format is controlled by general settings.")),
            ("tools_native", ("Нативные инструменты", "Native tools"), ("Модель поддерживает вызовы инструментов через API. Выбор инструментов остаётся в общих настройках.", "The model supports tool calls through the API. Tool selection remains in general settings.")),
            ("streaming", ("Поддержка стриминга", "Streaming support"), ("Модель поддерживает потоковый ответ. Включение стриминга остаётся в общих настройках.", "The model supports streamed responses. Streaming is enabled in general settings.")),
        ):
            row = QWidget()
            row.setObjectName("ApiGenerationRow")
            horizontal = QHBoxLayout(row)
            horizontal.setContentsMargins(0, 10, 0, 10)
            labels = QVBoxLayout()
            labels.setSpacing(4)
            labels.addLayout(parameter_heading(tr_set(QLabel(), *title), key))
            subtitle = tr_set(QLabel(), *explanation)
            subtitle.setObjectName("ApiSettingsSubtitle")
            subtitle.setWordWrap(True)
            labels.addWidget(subtitle)
            horizontal.addLayout(labels, 1)
            value = tr_set(QCheckBox(), "Поддерживается", "Supported")
            value.setFixedWidth(180)
            value.setChecked(document.get("support_overrides", {}).get(key, schema.data.get("supports", {}).get(key, True)))
            value.toggled.connect(self._field_changed)
            horizontal.addWidget(value)
            self.support_fields[key] = value
            self.rows.addWidget(row)
        self._loading = False
        self._refresh_texts()
        self.validate()

    def _refresh_texts(self):
        if self._schema is None:
            return
        language = localization._current_language()
        format_name = {"gemini_generate_content": "Google Gemini API", "openai_chat_completions": "OpenAI Compatible", "g4f": "GPT4Free"}[self._schema.data["dialect"]]
        self.format_label.setText(str(_("Формат параметров: ", "Parameter format: ")) + format_name)
        definition_note = self._schema.data.get("description")
        self.schema_description.setText(schema_text(definition_note, language))
        duplicate = schema_text(definition_note, "ru").strip() in _PRESET_NOTE or self.schema_description.text().strip() == self.note.text().strip()
        self.schema_description.setVisible(bool(self.schema_description.text()) and not duplicate)
        for spec, enabled, editor, title, description in self.fields.values():
            title.setText(schema_text(spec.get("title") or spec["id"], language))
            description.setText(schema_text(spec.get("description"), language))
            description.setVisible(bool(description.text()))
        self.validate()

    def _field_changed(self):
        if not self._loading:
            self.validate()
            self.changed.emit()

    def document(self):
        if self._document is None:
            return None
        result = deepcopy(self._document)
        result["enabled"] = [key for key, editor in self.orphan_fields.items() if editor.isChecked()]
        overrides = {key: editor.isChecked() for key, editor in self.support_fields.items() if editor.isChecked() != self._schema.data.get("supports", {}).get(key, True)}
        if overrides:
            result["support_overrides"] = overrides
        else:
            result.pop("support_overrides", None)
        for key, (spec, enabled, editor, *_labels) in self.fields.items():
            if enabled.isChecked():
                result["enabled"].append(key)
            if isinstance(editor, QComboBox):
                value = editor.currentData()
            elif isinstance(editor, QCheckBox):
                value = editor.isChecked()
            else:
                value = editor.text()
                if spec["type"] in {"array", "object"}:
                    try:
                        value = json.loads(value)
                    except ValueError:
                        pass
            result["values"][key] = value
        return result

    def validate(self):
        if self._schema is None:
            return True
        state = self.document()
        issues = self._schema.validate(state["values"], state["enabled"])
        self.error_label.setText("\n".join(issue_text(issue) for key, issue in issues.items() if key not in self.fields))
        self.error_label.setVisible(bool(self.error_label.text()))
        for key, (_spec, _enabled, editor, *_labels) in self.fields.items():
            issue = issues.get(key)
            invalid = bool(issue)
            if editor.property("invalid") != invalid:
                editor.setProperty("invalid", invalid)
                editor.style().unpolish(editor)
                editor.style().polish(editor)
                editor.update()
            editor.setToolTip(issue_text(issue) if issue else "")
        return not issues
