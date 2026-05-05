from PyQt6.QtWidgets import QWidget

from ui.pages.settings.settings_page_widget import SettingsPage, normalize_mode

_MODE_RANK = {"basic": 0, "advanced": 1, "full": 2}


def apply_interface_mode(gui, mode_value):
    page = getattr(gui, "settings_page", None)
    if page is not None and hasattr(page, "apply_interface_mode"):
        page.apply_interface_mode(mode_value)
        return

    mode = normalize_mode(mode_value)
    cur_rank = _MODE_RANK[mode]

    for cat, btn in getattr(gui, "settings_buttons", {}).items():
        need = _MODE_RANK[getattr(gui, "_category_modes", {}).get(cat, "basic")]
        btn.setVisible(need <= cur_rank)

    active = getattr(gui, "current_settings_category", None)
    if active:
        active_rank = _MODE_RANK[getattr(gui, "_category_modes", {}).get(active, "basic")]
        if active_rank > cur_rank and hasattr(gui, "show_settings_category"):
            gui.show_settings_category(active)

    try:
        from ui.widgets.status_indicators_widget import apply_capture_visibility

        apply_capture_visibility(gui, mode)
    except Exception:
        pass

    sidebar = getattr(gui, "shell_sidebar", None)
    if sidebar is not None and hasattr(sidebar, "apply_nav_mode"):
        sidebar.apply_nav_mode(cur_rank)


def create_settings_page(gui) -> QWidget:
    page = SettingsPage(gui)
    gui.settings_page = page
    return page
