from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class FineTuneDataState:
    statistics_lines: tuple[str, ...] = ()
    total_records: int = 0
    loading: bool = False
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshFineTuneData(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class ClearFineTuneData(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class EnforceFineTuneLimit(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SetFineTuneDirectory(UiIntent):
    directory: str


@dataclass(frozen=True, slots=True)
class FineTuneDataMessage(UiEffect):
    title: str
    message: str
    error: bool = False