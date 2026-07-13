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


_BACKEND_COMPAT: dict[str, set[str]] = {
    # GPU vendor (uppercase) -> backends that are compatible with the
    # detected hardware. "none"/"cpu" backends are always compatible.
    "NVIDIA": {"cuda", "onnx", "cpu", "none", ""},
    "AMD":    {"onnx", "cpu", "none", ""},
    "INTEL":  {"onnx", "cpu", "none", ""},
    "CPU":    {"cpu", "none", ""},
}


def is_backend_compatible(component_backend: str, gpu_vendor: str) -> bool:
    """Return True if `component_backend` (cuda/onnx/cpu/none) can run on
    hardware that `check_gpu_provider()` reported as `gpu_vendor`."""
    backend = str(component_backend or "").strip().lower()
    vendor = str(gpu_vendor or "CPU").strip().upper()
    allowed = _BACKEND_COMPAT.get(vendor, _BACKEND_COMPAT["CPU"])
    return backend in allowed
