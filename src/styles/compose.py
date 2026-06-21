from __future__ import annotations

from utils import render_qss

from styles.base import BASE_QSS
from styles.components import COMPONENTS_QSS
from styles.pages.home import HOME_PAGE_QSS
from styles.pages.logs import LOGS_PAGE_QSS
from styles.pages.news import NEWS_PAGE_QSS
from styles.pages.sandbox import CHAT_SCROLL_QSS, CHAT_WIDGETS_QSS, SANDBOX_PAGE_QSS
from styles.pages.settings import SETTINGS_PAGE_QSS
from styles.shell.main_window import MAIN_WINDOW_SHELL_QSS
from styles.theme import get_theme

MAIN_WINDOW_QSS_PARTS = (
    BASE_QSS,
    COMPONENTS_QSS,
    MAIN_WINDOW_SHELL_QSS,
    SETTINGS_PAGE_QSS,
    CHAT_WIDGETS_QSS,
    CHAT_SCROLL_QSS,
    SANDBOX_PAGE_QSS,
    NEWS_PAGE_QSS,
    LOGS_PAGE_QSS,
    HOME_PAGE_QSS,
)


def build_main_window_qss() -> str:
    return "\n\n".join(part.strip("\n") for part in MAIN_WINDOW_QSS_PARTS if part.strip())


def get_main_window_stylesheet(overrides: dict[str, str] | None = None) -> str:
    theme = get_theme()
    if overrides:
        theme.update(overrides)
    return render_qss(build_main_window_qss(), theme)
