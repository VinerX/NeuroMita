from __future__ import annotations

from ui.pages.settings.section_registry import get_settings_section_specs


ALWAYS_ON_SECTIONS = frozenset({"general", "language"})
_LEGACY_SECTION_KEYS = {"data_collection": "developer"}


def _build_section_defaults() -> dict[str, bool]:
    defaults: dict[str, bool] = {}
    for spec in get_settings_section_specs():
        if spec.key in ALWAYS_ON_SECTIONS:
            continue
        defaults[spec.key] = spec.min_mode == "basic" or spec.key == "updates"
    return defaults


def _build_section_labels() -> dict[str, tuple[str, str]]:
    return {spec.key: spec.nav_label for spec in get_settings_section_specs()}


SECTION_DEFAULTS: dict[str, bool] = _build_section_defaults()
SECTION_LABELS: dict[str, tuple[str, str]] = _build_section_labels()
TOGGLEABLE_SECTIONS: tuple[str, ...] = tuple(SECTION_DEFAULTS)


def _section_key(category: str) -> str:
    return f"SECTION_{category.upper()}_ENABLED"


def migrate_legacy_section_settings(settings) -> None:
    """Keep saved section visibility when a section receives a new key."""
    getter = getattr(settings, "get", None)
    setter = getattr(settings, "set", None)
    if not callable(getter) or not callable(setter):
        return

    missing = object()
    for category, legacy_category in _LEGACY_SECTION_KEYS.items():
        try:
            current = getter(_section_key(category), missing)
            legacy = getter(_section_key(legacy_category), missing)
        except Exception:
            continue
        if current is not missing or legacy is missing:
            continue
        try:
            setter(_section_key(category), bool(legacy))
        except Exception:
            continue


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
    "migrate_legacy_section_settings",
    "is_section_enabled",
    "set_section_enabled",
]
