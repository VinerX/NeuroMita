from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class NewsPageState:
    repository: str = ""
    items: tuple[Any, ...] = ()
    releases: Any = ()
    content: str = ""
    loading: bool = False
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class ActivateNewsPage(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class RefreshNewsPage(UiIntent):
    force: bool = True


@dataclass(frozen=True, slots=True)
class NewsPageUpdated(UiEffect):
    pass
