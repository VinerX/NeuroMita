"""Generic renderer for ConfigurableComponent.settings_schema().

Schema entries are plain dicts with keys:
    key           — settings key (str)
    label         — human label (str)
    type          — "entry" | "combobox" | "checkbutton" | "spinbox" | ...
    options       — type-specific config:
        entry:        {"default": str}
        combobox:     {"values": list[str], "default": str}
        checkbutton:  {"default": bool}
        spinbox:      {"default": int, "min": int, "max": int, "step": int}
    help          — tooltip / inline help (optional)
    locked        — if True, the input is rendered disabled

Anything not understood is rendered as a read-only QLineEdit so the field
isn't silently dropped.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SchemaForm(QWidget):
    """Renders a list of schema entries into a vertical form.

    Public API:
        values()              -> dict[str, str]   — current values
        set_values(values)    -> None              — bulk apply (for load)
        set_field_error(k, m) -> None              — show validation error
        clear_field_errors()  -> None
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
        self._on_change = on_change

        self._form_box = QVBoxLayout(self)
        self._form_box.setContentsMargins(0, 0, 0, 0)
        self._form_box.setSpacing(14)

        self._form_host = QFrame(self)
        self._form_host.setObjectName("AIHubSchemaForm")
        self._form_layout = QFormLayout(self._form_host)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setHorizontalSpacing(16)
        self._form_layout.setVerticalSpacing(10)
        self._form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._form_box.addWidget(self._form_host, 1)

        if schema:
            self.set_schema(schema)

    # ---------------------------------------------------------- public

    def set_schema(self, schema: list[dict[str, Any]]) -> None:
        self._clear()
        self._schema = list(schema or [])
        for entry in self._schema:
            self._build_row(entry)

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
        self._original = {}
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
            self._original[key] = str(raw)

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
        while self._form_layout.rowCount() > 0:
            self._form_layout.removeRow(0)
        self._widgets.clear()
        self._error_labels.clear()
        self._defaults.clear()
        self._original.clear()
        self._schema = []

    def _build_row(self, entry: dict[str, Any]) -> None:
        key = str(entry.get("key") or "")
        if not key:
            return
        type_ = str(entry.get("type") or "entry").lower()
        opts = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        locked = bool(entry.get("locked"))

        widget = self._build_widget(type_, opts, locked, key)
        if widget is None:
            return
        self._widgets[key] = widget

        label_text = str(entry.get("label") or key)
        help_text = str(entry.get("help") or "")
        label = QLabel(label_text)
        label.setObjectName("AIHubFormLabel")
        if help_text:
            label.setToolTip(help_text)

        # Right column: widget + (optional) help line + error line
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)

        widget_wrap = QHBoxLayout()
        widget_wrap.setContentsMargins(0, 0, 0, 0)
        widget_wrap.setSpacing(8)
        widget_wrap.addWidget(widget, 1)
        right_col.addLayout(widget_wrap)

        if help_text:
            help_lbl = QLabel(help_text)
            help_lbl.setObjectName("AIHubFormHelp")
            help_lbl.setWordWrap(True)
            right_col.addWidget(help_lbl)

        err_lbl = QLabel("")
        err_lbl.setObjectName("AIHubFormError")
        err_lbl.setWordWrap(True)
        err_lbl.setVisible(False)
        right_col.addWidget(err_lbl)
        self._error_labels[key] = err_lbl

        right_host = QFrame()
        right_host.setLayout(right_col)
        self._form_layout.addRow(label, right_host)

    def _build_widget(
        self,
        type_: str,
        opts: dict[str, Any],
        locked: bool,
        key: str,
    ) -> QWidget | None:
        default = opts.get("default", "")

        if type_ == "checkbutton":
            w = QCheckBox()
            w.setChecked(bool(default))
            self._defaults[key] = "True" if default else "False"
            w.toggled.connect(self._fire_change)
            if locked:
                w.setEnabled(False)
            return w

        if type_ == "combobox":
            w = QComboBox()
            values = [str(v) for v in (opts.get("values") or []) if str(v).strip()]
            w.addItems(values)
            default_str = str(default or (values[0] if values else ""))
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
        type_ = str(entry.get("type") or "entry").lower()
        if type_ == "checkbutton" and isinstance(widget, QCheckBox):
            return "True" if widget.isChecked() else "False"
        if type_ == "combobox" and isinstance(widget, QComboBox):
            return widget.currentText()
        if type_ == "spinbox" and isinstance(widget, QSpinBox):
            return str(widget.value())
        if isinstance(widget, QLineEdit):
            return widget.text()
        return ""

    @staticmethod
    def _write_widget(entry: dict[str, Any], widget: QWidget, value: Any) -> None:
        type_ = str(entry.get("type") or "entry").lower()
        try:
            if type_ == "checkbutton" and isinstance(widget, QCheckBox):
                widget.blockSignals(True)
                widget.setChecked(_truthy(value))
                widget.blockSignals(False)
                return
            if type_ == "combobox" and isinstance(widget, QComboBox):
                widget.blockSignals(True)
                idx = widget.findText(str(value))
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
            if isinstance(widget, QLineEdit):
                widget.blockSignals(True)
                widget.setText("" if value is None else str(value))
                widget.blockSignals(False)
        except Exception:
            pass

    def _fire_change(self, *_args, **_kwargs) -> None:
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                pass


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")
