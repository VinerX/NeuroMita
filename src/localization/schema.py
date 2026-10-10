"""Localization of declarative combobox options, independent of provider IDs."""

from . import translate


def option_label(field: dict, value: str) -> str:
    source = (field.get("option_label_sources") or {}).get(value)
    if source is None:
        return str((field.get("option_labels") or {}).get(value, value))
    label = translate(*source)
    return field.get("option_label_format", "{label}").format(label=label, value=value)


def bind_option_labels(combo, field: dict) -> None:
    from PyQt6.QtCore import QSignalBlocker
    from .live import register

    def refresh(widget):
        with QSignalBlocker(widget):
            for index in range(widget.count()):
                value = widget.itemData(index)
                if value in (field.get("option_label_sources") or {}):
                    widget.setItemText(index, option_label(field, value))

    refresh(combo)
    if field.get("option_label_sources"):
        register(combo, refresh)
