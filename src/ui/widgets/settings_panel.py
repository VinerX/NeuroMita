from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ui.pages.settings.section_access import (
    ALWAYS_ON_SECTIONS,
    SECTION_DEFAULTS,
    SECTION_LABELS,
    TOGGLEABLE_SECTIONS,
    _section_key,
    is_section_enabled,
    set_section_enabled,
)
from ui.pages.settings.settings_page_widget import SettingsPage, normalize_mode
from ui.settings.settings_access import settings_store


def apply_section_visibility(gui) -> None:
    """Refresh every consumer of the per-section toggles."""
    page = getattr(gui, "settings_page", None)
    if page is not None and hasattr(page, "apply_section_visibility"):
        page.apply_section_visibility()
        return

    for category, button in getattr(gui, "settings_buttons", {}).items():
        button.setVisible(is_section_enabled(category, settings_store(gui)))

    active = getattr(gui, "current_settings_category", None)
    if (
        active
        and not is_section_enabled(active, settings_store(gui))
        and hasattr(gui, "show_settings_category")
    ):
        gui.show_settings_category(active)

    try:
        from ui.widgets.status_indicators_widget import apply_capture_visibility

        apply_capture_visibility(gui)
    except Exception:
        pass

    sidebar = getattr(gui, "shell_sidebar", None)
    if sidebar is not None and hasattr(sidebar, "apply_section_visibility"):
        sidebar.apply_section_visibility(
            lambda key: is_section_enabled(key, settings_store(gui))
        )


def apply_interface_mode(gui, mode_value=None):
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
