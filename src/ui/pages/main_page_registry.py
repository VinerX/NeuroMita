from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtWidgets import QWidget

from .developer_page import build_developer_page
from .home_page import build_home_page
from .logs_page import build_logs_page
from .news_page import build_news_page
from .sandbox_page import build_sandbox_page
from .settings_page import build_settings_page
from .wiki_page import build_wiki_page

PageFactory = Callable[[object], QWidget]


@dataclass(frozen=True, slots=True)
class MainPageSpec:
    key: str
    factory: PageFactory


MAIN_PAGE_SPECS: tuple[MainPageSpec, ...] = (
    MainPageSpec("home", build_home_page),
    MainPageSpec("news", build_news_page),
    MainPageSpec("sandbox", build_sandbox_page),
    MainPageSpec("settings", build_settings_page),
    MainPageSpec("developer", build_developer_page),
    MainPageSpec("wiki", build_wiki_page),
    MainPageSpec("logs", build_logs_page),
)

MAIN_PAGE_ORDER: tuple[str, ...] = tuple(spec.key for spec in MAIN_PAGE_SPECS)


def get_main_page_specs() -> tuple[MainPageSpec, ...]:
    return MAIN_PAGE_SPECS


def get_main_page_factory(page_key: str) -> PageFactory | None:
    for spec in MAIN_PAGE_SPECS:
        if spec.key == page_key:
            return spec.factory
    return None


def build_main_pages(window) -> dict[str, QWidget]:
    return {spec.key: spec.factory(window) for spec in MAIN_PAGE_SPECS}
