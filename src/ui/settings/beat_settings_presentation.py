from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class BeatSettingsState:
    preferred_backend: str = "auto"
    resolved_backend: str = "dsp_fallback"
    available_backends: tuple[str, ...] = ("auto", "dsp_fallback")
    backend_labels: tuple[tuple[str, str], ...] = ()
    beat_this_installed: bool = False
    cache_entries: int = 0
    cache_bytes: int = 0
    cache_directory: str = ""
    busy: bool = False
    message: str = ""
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class BeatSettingsActivated(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class BeatBackendSelected(UiIntent):
    backend_id: str


@dataclass(frozen=True, slots=True)
class BeatOpenHubRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class BeatOpenCacheRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class BeatRebuildCacheRequested(UiIntent):
    directory: str


@dataclass(frozen=True, slots=True)
class BeatOpenDirectory(UiEffect):
    directory: str


@dataclass(frozen=True, slots=True)
class BeatShowMessage(UiEffect):
    title: str
    message: str
    error: bool = False