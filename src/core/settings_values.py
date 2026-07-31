"""Приведение значений настроек к типам.

Настройка может приехать не только из чекбокса (настоящий ``bool``), но и из
settings.json, env-переопределения или пресета — то есть строкой. ``bool("false")``
там равен True, поэтому нормализация нужна одна на всех, а не копией в каждом
модуле.
"""
from __future__ import annotations

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off", "n", "f", ""})


def as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
        return bool(default)
    try:
        return bool(value)
    except Exception:
        return bool(default)
