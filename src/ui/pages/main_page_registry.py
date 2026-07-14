from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from PyQt6.QtWidgets import QWidget

PageFactory = Callable[[object], QWidget]


@dataclass(frozen=True, slots=True)
class MainPageSpec:
    key: str
    module_name: str
    factory_name: str

    def load_factory(self) -> PageFactory:
        module = import_module(self.module_name)
        return getattr(module, self.factory_name)

    @property
    def factory(self) -> PageFactory:
        return self.load_factory()


MAIN_PAGE_SPECS: tuple[MainPageSpec, ...] = (
    MainPageSpec("home", "ui.pages.home_page", "build_home_page"),
    MainPageSpec("news", "ui.pages.news_page", "build_news_page"),
    MainPageSpec("sandbox", "ui.pages.sandbox_page", "build_sandbox_page"),
    MainPageSpec("settings", "ui.pages.settings_page", "build_settings_page"),
    MainPageSpec("developer", "ui.pages.developer_page", "build_developer_page"),
    MainPageSpec("wiki", "ui.pages.wiki_page", "build_wiki_page"),
    MainPageSpec("logs", "ui.pages.logs_page", "build_logs_page"),
)

MAIN_PAGE_ORDER: tuple[str, ...] = tuple(spec.key for spec in MAIN_PAGE_SPECS)
_SPEC_BY_KEY = {spec.key: spec for spec in MAIN_PAGE_SPECS}


def get_main_page_specs() -> tuple[MainPageSpec, ...]:
    return MAIN_PAGE_SPECS


def get_main_page_factory(page_key: str) -> PageFactory | None:
    spec = _SPEC_BY_KEY.get(str(page_key or ""))
    return spec.load_factory() if spec is not None else None


def build_main_pages(window) -> dict[str, QWidget]:
    return {spec.key: spec.load_factory()(window) for spec in MAIN_PAGE_SPECS}
