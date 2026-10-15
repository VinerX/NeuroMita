"""Generic renderer for ConfigurableComponent.settings_schema().

Schema entries are plain dicts with keys:
    key           — settings key (str)
    label         — human label (str)
    type          — "entry" | "combobox" | "checkbutton" | "spinbox" | ...
    options       — type-specific config:
        entry:        {"default": str}
        combobox:     {"values": list[str], "default": str,
                       "display_labels": {raw_value: display_text}}
        checkbutton:  {"default": bool}
        spinbox / number_stepper:
                      {"default": int, "min": int, "max": int, "step": int}
    help          — tooltip / inline help (optional)
    locked        — if True, the input is rendered disabled
    behavior      — optional declarative dependency on another field
    presentation_slot — a full-width named slot supplied by the owning view

Anything not understood is rendered as a read-only QLineEdit so the field
isn't silently dropped.
"""
from __future__ import annotations

from typing import Any, Callable

from core.setting_behaviors import evaluate_setting_behaviors
from utils import getTranslationVariant as _tr
from localization.schema import bind_option_labels

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.number_stepper import NumberStepper


class SchemaForm(QWidget):
    """Renders a list of schema entries into a vertical form.

    Public API:
        values()              -> dict[str, str]   — current values
        set_values(values)    -> None              — bulk apply (for load)
        set_field_error(k, m) -> None              — show validation error
        clear_field_errors()  -> None
        set_slot_widgets({slot: widget}) -> None   — register full-width UI slots
        is_dirty()            -> bool
        on_change             — optional callable invoked on any field edit
    """

    def __init__(
        self,
        schema: list[dict[str, Any]] | None = None,
        *,
        on_change: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._schema: list[dict[str, Any]] = []
        self._widgets: dict[str, QWidget] = {}
        self._error_labels: dict[str, QLabel] = {}
        self._defaults: dict[str, str] = {}
        self._original: dict[str, str] = {}
        self._base_locked: dict[str, bool] = {}
        self._on_change = on_change
        self._slot_widgets: dict[str, QWidget] = {}
        self._slot_hosts: list[QFrame] = []

        self._form_box = QVBoxLayout(self)
        self._form_box.setContentsMargins(0, 0, 0, 0)
        self._form_box.setSpacing(14)
        self._form_box.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._form_host = QFrame(self)
        self._form_host.setObjectName("AIHubSchemaForm")
        self._form_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._form_layout = QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(16)
        self._form_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._form_box.addWidget(self._form_host, 0)

        if schema:
            self.set_schema(schema)

    # ---------------------------------------------------------- public

    def set_schema(self, schema: list[dict[str, Any]]) -> None:
        self._clear()
        self._schema = list(schema or [])
        for entry in self._schema:
            if self._normalize_type(entry.get("type")) == "presentation_slot":
                self._build_slot_row(entry)
                continue
            self._build_row(entry)
        self._apply_behaviors()

    def set_slot_widgets(self, widgets: dict[str, QWidget] | None) -> None:
        replacement = {
            str(slot).strip(): widget
            for slot, widget in dict(widgets or {}).items()
            if str(slot).strip() and isinstance(widget, QWidget)
        }
        for slot, widget in self._slot_widgets.items():
            if replacement.get(slot) is not widget:
                widget.setParent(self)
        self._slot_widgets = replacement

    def values(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for entry in self._schema:
            key = str(entry.get("key") or "")
            if not key:
                continue
            w = self._widgets.get(key)
            if w is None:
                continue
            out[key] = self._read_widget(entry, w)
        return out

    def set_values(self, values: dict[str, Any] | None) -> None:
        if not isinstance(values, dict):
            values = {}
        for entry in self._schema:
            key = str(entry.get("key") or "")
            if not key:
                continue
            raw = values.get(key, self._defaults.get(key, ""))
            w = self._widgets.get(key)
            if w is not None:
                self._write_widget(entry, w, raw)
        self._apply_behaviors()
        self._original = self.values()

    def is_dirty(self) -> bool:
        current = self.values()
        for k, v in current.items():
            if str(v) != str(self._original.get(k, self._defaults.get(k, ""))):
                return True
        return False

    def set_field_error(self, key: str, message: str) -> None:
        lbl = self._error_labels.get(key)
        if lbl is None:
            return
        lbl.setText(str(message or ""))
        lbl.setVisible(bool(message))
        w = self._widgets.get(key)
        if w is not None:
            w.setProperty("hasError", "true" if message else "false")
            w.style().unpolish(w)
            w.style().polish(w)

    def clear_field_errors(self) -> None:
        for k in list(self._error_labels.keys()):
            self.set_field_error(k, "")

    # ---------------------------------------------------------- build

    def _clear(self) -> None:
        for widget in self._slot_widgets.values():
            widget.setParent(self)
        self._slot_hosts.clear()
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._widgets.clear()
        self._error_labels.clear()
        self._defaults.clear()
        self._original.clear()
        self._base_locked.clear()
        self._schema = []

    def _build_slot_row(self, entry: dict[str, Any]) -> None:
        slot = str(entry.get("slot") or "").strip()
        widget = self._slot_widgets.get(slot)
        if widget is None:
            return
        host = QFrame(self._form_host)
        host.setObjectName("AIHubSchemaInlineHost")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(widget)
        self._slot_hosts.append(host)
        self._form_layout.addWidget(host)

    # ---- schema-dialect tolerance -------------------------------------
    # Two schema formats coexist in the codebase:
    #   new (TTS / AI Hub):  {"label": "...", "options": {"values": [...], "default": ...}}
    #   old (ASR models):    {"label_ru": "...", "label_en": "...",
    #                         "options": [...], "default": ...}
    # SchemaForm accepts both so ASR recognizers render correctly here too.

    @staticmethod
    def _normalize_type(raw: Any) -> str:
        t = str(raw or "entry").lower()
        if t == "check":
            return "checkbutton"
        return t

    @staticmethod
    def _normalize_options(entry: dict[str, Any]) -> dict[str, Any]:
        raw = entry.get("options")
        if isinstance(raw, dict):
            opts = dict(raw)
        elif isinstance(raw, (list, tuple)):
            opts = {"values": list(raw)}
        else:
            opts = {}
        if "display_labels" not in opts and isinstance(entry.get("option_labels"), dict):
            opts["display_labels"] = dict(entry["option_labels"])
        if "default" not in opts and entry.get("default") is not None:
            opts["default"] = entry.get("default")
        return opts

    @staticmethod
    def _resolve_label(entry: dict[str, Any], key: str) -> str:
        label = entry.get("label")
        if label:
            return str(label)
        ru = entry.get("label_ru")
        en = entry.get("label_en")
        if ru or en:
            return _tr(str(ru or en), str(en or ru))
        return key

    def _build_row(self, entry: dict[str, Any]) -> None:
        key = str(entry.get("key") or "")
        if not key:
            return
        type_ = self._normalize_type(entry.get("type"))
        opts = self._normalize_options(entry)
        locked = bool(entry.get("locked")) or entry.get("enabled") is False

        widget = self._build_widget(type_, opts, locked, key)
        if widget is None:
            return
        if isinstance(widget, QComboBox):
            bind_option_labels(widget, entry)
        self._widgets[key] = widget

        label_text = self._resolve_label(entry, key)
        help_text = str(entry.get("help") or _tr(entry.get("help_ru", ""), entry.get("help_en", "")))
        label = QLabel(label_text)
        label.setObjectName("AIHubFormLabel")
        label.setWordWrap(True)
        label.setFixedWidth(180)
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        if help_text:
            label.setToolTip(help_text)

        row = QFrame(self._form_host)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        grid.addWidget(label, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if type_ == "checkbutton":
            widget.setMinimumHeight(32)
            grid.addWidget(widget, 0, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        else:
            grid.addWidget(widget, 0, 1)
        if help_text:
            help_lbl = QLabel(help_text)
            help_lbl.setObjectName("AIHubFormHelp")
            help_lbl.setWordWrap(True)
            help_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            grid.addWidget(help_lbl, 1, 1)
        err_lbl = QLabel("")
        err_lbl.setObjectName("AIHubFormError")
        err_lbl.setWordWrap(True)
        err_lbl.hide()
        grid.addWidget(err_lbl, 2, 1)
        self._error_labels[key] = err_lbl
        self._form_layout.addWidget(row)

    def _build_widget(
        self,
        type_: str,
        opts: dict[str, Any],
        locked: bool,
        key: str,
    ) -> QWidget | None:
        default = opts.get("default", "")
        self._base_locked[key] = bool(locked)

        if type_ == "checkbutton":
            w = QCheckBox()
            w.setChecked(bool(default))
            w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self._defaults[key] = "True" if default else "False"
            w.toggled.connect(self._fire_change)
            if locked:
                w.setEnabled(False)
            return w

        if type_ == "combobox":
            w = QComboBox()
            values = [str(v) for v in (opts.get("values") or []) if str(v).strip()]
            labels = opts.get("display_labels") if isinstance(opts.get("display_labels"), dict) else {}
            for value in values:
                w.addItem(str(labels.get(value, value)), value)
            default_str = str(default or (values[0] if values else ""))
            idx = w.findData(default_str)
            if idx < 0:
                idx = w.findText(default_str)
            if idx >= 0:
                w.setCurrentIndex(idx)
            self._defaults[key] = default_str
            w.currentIndexChanged.connect(self._fire_change)
            if locked:
                w.setEnabled(False)
            return w

        if type_ == "spinbox":
            w = QSpinBox()
            try:
                w.setMinimum(int(opts.get("min", 0)))
                w.setMaximum(int(opts.get("max", 100)))
                w.setSingleStep(int(opts.get("step", 1)))
                w.setValue(int(default))
            except Exception:
                w.setValue(0)
            self._defaults[key] = str(w.value())
            w.valueChanged.connect(self._fire_change)
            if locked:
                w.setEnabled(False)
            return w

        if type_ == "number_stepper":
            w = NumberStepper()
            try:
                minimum = int(opts.get("min", 0))
            except (TypeError, ValueError, OverflowError):
                minimum = 0
            try:
                maximum = int(opts.get("max", 100))
            except (TypeError, ValueError, OverflowError):
                maximum = 100
            try:
                step = max(1, int(opts.get("step", 1)))
            except (TypeError, ValueError, OverflowError):
                step = 1
            try:
                value = int(float(default))
            except (TypeError, ValueError, OverflowError):
                value = 0
            w.setRange(minimum, maximum)
            w.setSingleStep(step)
            w.setValue(max(minimum, min(maximum, value)))
            suffix = str(opts.get("suffix") or "")
            if suffix:
                w.setSuffix(suffix)
            self._defaults[key] = str(w.value())
            w.valueChanged.connect(self._fire_change)
            if locked:
                w.setEnabled(False)
            return w

        # default = entry
        w = QLineEdit()
        w.setText(str(default))
        self._defaults[key] = str(default)
        w.textChanged.connect(self._fire_change)
        if locked:
            w.setReadOnly(True)
        return w

    # ---------------------------------------------------------- io

    @staticmethod
    def _read_widget(entry: dict[str, Any], widget: QWidget) -> str:
        type_ = SchemaForm._normalize_type(entry.get("type"))
        if type_ == "checkbutton" and isinstance(widget, QCheckBox):
            return "True" if widget.isChecked() else "False"
        if type_ == "combobox" and isinstance(widget, QComboBox):
            data = widget.currentData()
            return str(data) if data is not None else widget.currentText()
        if type_ == "spinbox" and isinstance(widget, QSpinBox):
            return str(widget.value())
        if type_ == "number_stepper" and isinstance(widget, NumberStepper):
            return str(widget.value())
        if isinstance(widget, QLineEdit):
            return widget.text()
        return ""

    @staticmethod
    def _write_widget(entry: dict[str, Any], widget: QWidget, value: Any) -> None:
        type_ = SchemaForm._normalize_type(entry.get("type"))
        try:
            if type_ == "checkbutton" and isinstance(widget, QCheckBox):
                widget.blockSignals(True)
                widget.setChecked(_truthy(value))
                widget.blockSignals(False)
                return
            if type_ == "combobox" and isinstance(widget, QComboBox):
                widget.blockSignals(True)
                idx = widget.findData(str(value))
                if idx < 0:
                    idx = widget.findText(str(value))
                key = str(entry.get("key") or "").lower()
                if idx < 0 and str(value).strip() and "device" in key:
                    widget.addItem(
                        _tr(f"Недоступно: {value}", f"Unavailable: {value}"),
                        str(value),
                    )
                    idx = widget.count() - 1
                if idx >= 0:
                    widget.setCurrentIndex(idx)
                widget.blockSignals(False)
                return
            if type_ == "spinbox" and isinstance(widget, QSpinBox):
                widget.blockSignals(True)
                try:
                    widget.setValue(int(value))
                except Exception:
                    pass
                widget.blockSignals(False)
                return
            if type_ == "number_stepper" and isinstance(widget, NumberStepper):
                widget.blockSignals(True)
                try:
                    widget.setValue(int(float(value)))
                except (TypeError, ValueError, OverflowError):
                    widget.setValue(0)
                widget.blockSignals(False)
                return
            if isinstance(widget, QLineEdit):
                widget.blockSignals(True)
                widget.setText("" if value is None else str(value))
                widget.blockSignals(False)
        except Exception:
            pass

    def _fire_change(self, *_args, **_kwargs) -> None:
        self._apply_behaviors()
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass

    def _apply_behaviors(self) -> None:
        for key, state in evaluate_setting_behaviors(self._schema, self.values()).items():
            widget = self._widgets.get(key)
            entry = next(
                (item for item in self._schema if str(item.get("key") or "") == key),
                None,
            )
            if widget is None or entry is None:
                continue
            forced = state.get("value")
            if forced is not None:
                self._write_widget(entry, widget, forced)
            widget.setEnabled(bool(state.get("enabled")) and not self._base_locked.get(key, False))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")
