from PyQt6.QtWidgets import QWidget

from ui.windows.main_view import ChatGUI as LegacyChatGUI


def build_news_page(window) -> QWidget:
    return LegacyChatGUI._build_news_page(window)
