from PyQt6.QtWidgets import QWidget

from ui.pages.settings.settings_page_widget import SettingsPage


def build_settings_page(window) -> QWidget:
    return SettingsPage(window)
