from PyQt6.QtWidgets import QWidget

from ui.pages.settings.settings_page_widget import SettingsPage


def build_settings_page(window) -> QWidget:
    view_model = window.presentation.view_models.settings_page(window)
    page = SettingsPage(window, view_model)
    view_model.setParent(page)
    return page
