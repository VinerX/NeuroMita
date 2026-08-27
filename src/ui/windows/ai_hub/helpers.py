from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize

try:
    import qtawesome as qta
except Exception:
    qta = None

from .constants import ROW_CATEGORY_MAP


def meta_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def status_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("status")
    return value if isinstance(value, dict) else {}


def row_category(row: dict[str, Any]) -> str:
    raw = str(meta_from_row(row).get("category") or "").strip().lower()
    return ROW_CATEGORY_MAP.get(raw, raw)


def qpixmap(name: str, color: str, size: int = 16):
    if not qta:
        return None
    try:
        return qta.icon(name, color=color).pixmap(QSize(size, size))
    except Exception:
        return None


def qicon(name: str, color: str):
    if not qta:
        return None
    try:
        return qta.icon(name, color=color)
    except Exception:
        return None
