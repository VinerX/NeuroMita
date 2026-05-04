from __future__ import annotations

from styles.compose import get_main_window_stylesheet
from styles.theme import THEME, get_theme


def get_stylesheet(overrides: dict[str, str] | None = None) -> str:
    return get_main_window_stylesheet(overrides)


__all__ = [
    "THEME",
    "get_theme",
    "get_stylesheet",
]
