from PyQt6.QtWidgets import QWidget

from ui.pages.settings.settings_page_widget import SettingsPage


def build_settings_page(parent, view_model, page_actions, settings) -> QWidget:
    page = SettingsPage(parent, view_model, page_actions, settings)
    view_model.setParent(page)
    return page
