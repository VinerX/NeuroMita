from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ui.pages.settings.section_registry import get_settings_section_specs
from ui.pages.settings.settings_page_widget import SettingsPage, normalize_mode
from ui.settings.settings_access import settings_store

# ---------------------------------------------------------------------------
# Per-section enable/disable
# ---------------------------------------------------------------------------
# The old INTERFACE_MODE (Basic/Advanced/Full) dropdown is replaced by
# independent per-section toggles. Each toggleable category gets a setting
# key in the SettingsManager (SECTION_<CAT>_ENABLED). Defaults reproduce the
# old "Basic" set: sections whose registry spec.min_mode == "basic" start
# enabled, the rest start disabled. "general" is always on (it hosts the
# section toggles themselves, so it must stay reachable).

ALWAYS_ON_SECTIONS = frozenset({"general", "language"})

# The launcher's main-nav "developer" page is gated the same way as a
# settings section even though it is not part of the settings registry.
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
    labels: dict[str, tuple[str, str]] = {}
    for spec in get_settings_section_specs():
        labels[spec.key] = spec.nav_label
    labels.update(_EXTRA_SECTION_LABELS)
    return labels


SECTION_DEFAULTS: dict[str, bool] = _build_section_defaults()
SECTION_LABELS: dict[str, tuple[str, str]] = _build_section_labels()
TOGGLEABLE_SECTIONS: tuple[str, ...] = tuple(SECTION_DEFAULTS.keys())


def _section_key(cat: str) -> str:
    return f"SECTION_{cat.upper()}_ENABLED"


def is_section_enabled(cat: str, settings) -> bool:
    """Whether the category should appear in the UI.

    'general' is always enabled (it hosts the section toggles). Unknown
    categories stay visible so we never accidentally hide something new."""
    if cat in ALWAYS_ON_SECTIONS:
        return True
    if cat not in SECTION_DEFAULTS:
        return True
    default = SECTION_DEFAULTS[cat]
    return bool(settings.get(_section_key(cat), default))


def set_section_enabled(cat: str, enabled: bool, settings) -> None:
    if cat in ALWAYS_ON_SECTIONS or cat not in SECTION_DEFAULTS:
        return
    settings.set(_section_key(cat), bool(enabled))


def apply_section_visibility(gui) -> None:
    """Refresh every consumer of the per-section toggles."""
    page = getattr(gui, "settings_page", None)
    if page is not None and hasattr(page, "apply_section_visibility"):
        page.apply_section_visibility()
        return

    # Fallback for early-startup / detached usage: drive raw button maps.
    for cat, btn in getattr(gui, "settings_buttons", {}).items():
        btn.setVisible(is_section_enabled(cat, settings_store(gui)))

    active = getattr(gui, "current_settings_category", None)
    if active and not is_section_enabled(active, settings_store(gui)) and hasattr(gui, "show_settings_category"):
        gui.show_settings_category(active)

    try:
        from ui.widgets.status_indicators_widget import apply_capture_visibility

        apply_capture_visibility(gui)
    except Exception:
        pass

    sidebar = getattr(gui, "shell_sidebar", None)
    if sidebar is not None and hasattr(sidebar, "apply_section_visibility"):
        sidebar.apply_section_visibility(lambda key: is_section_enabled(key, settings_store(gui)))


def apply_interface_mode(gui, mode_value=None):
    """Back-compat shim. The interface is now driven by per-section toggles,
    so the mode argument is ignored — we just re-apply the visibility map."""
    apply_section_visibility(gui)


def create_settings_page(gui, view_model, section_builder) -> QWidget:
    page = SettingsPage(gui, view_model, section_builder)
    view_model.setParent(page)
    gui.settings_page = page
    return page


__all__ = [
    "ALWAYS_ON_SECTIONS",
    "SECTION_DEFAULTS",
    "SECTION_LABELS",
    "TOGGLEABLE_SECTIONS",
    "_section_key",
    "is_section_enabled",
    "set_section_enabled",
    "apply_section_visibility",
    "apply_interface_mode",
    "normalize_mode",
    "create_settings_page",
]
