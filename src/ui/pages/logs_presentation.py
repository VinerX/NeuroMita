from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class LogsPageState:
    text: str = ""
    loading: bool = False


@dataclass(frozen=True, slots=True)
class RefreshLogs(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class OpenLogsFolder(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class LogsShowError(UiEffect):
    title: str
    message: str