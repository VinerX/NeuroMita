from PyQt6.QtWidgets import QWidget

from ui.pages.settings.section_registry import build_settings_containers
from ui.widgets.settings_panel import create_settings_page


def build_settings_page(window) -> QWidget:
    page = create_settings_page(window)
    build_settings_containers(window)
    return page
