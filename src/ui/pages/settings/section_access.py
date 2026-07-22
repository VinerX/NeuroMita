from __future__ import annotations

from ui.pages.settings.section_registry import get_settings_section_specs


ALWAYS_ON_SECTIONS = frozenset({"general", "language"})
_EXTRA_SECTION_DEFAULTS = {"developer": False}
_EXTRA_SECTION_LABELS = {"developer": ("Дев", "Dev")}


def _build_section_defaults() -> dict[str, bool]:
    defaults: dict[str, bool] = {}
    for spec in get_settings_section_specs():
        if spec.key in ALWAYS_ON_SECTIONS:
            continue
        defaults[spec.key] = spec.min_mode == "basic" or spec.key == "updates"
    for key, value in _EXTRA_SECTION_DEFAULTS.items():
        defaults.setdefault(key, value)
    return defaults


def _build_section_labels() -> dict[str, tuple[str, str]]:
    labels = {spec.key: spec.nav_label for spec in get_settings_section_specs()}
    labels.update(_EXTRA_SECTION_LABELS)
    return labels


SECTION_DEFAULTS: dict[str, bool] = _build_section_defaults()
SECTION_LABELS: dict[str, tuple[str, str]] = _build_section_labels()
TOGGLEABLE_SECTIONS: tuple[str, ...] = tuple(SECTION_DEFAULTS)


def _section_key(category: str) -> str:
    return f"SECTION_{category.upper()}_ENABLED"


def is_section_enabled(category: str, settings) -> bool:
    if category in ALWAYS_ON_SECTIONS:
        return True
    if category not in SECTION_DEFAULTS:
        return True
    return bool(settings.get(_section_key(category), SECTION_DEFAULTS[category]))


def set_section_enabled(category: str, enabled: bool, settings) -> None:
    if category in ALWAYS_ON_SECTIONS or category not in SECTION_DEFAULTS:
        return
    settings.set(_section_key(category), bool(enabled))


__all__ = [
    "ALWAYS_ON_SECTIONS",
    "SECTION_DEFAULTS",
    "SECTION_LABELS",
    "TOGGLEABLE_SECTIONS",
    "_section_key",
    "is_section_enabled",
    "set_section_enabled",
]
