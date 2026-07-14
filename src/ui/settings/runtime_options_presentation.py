from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiIntent


@dataclass(frozen=True, slots=True)
class SettingsRuntimeOptionsState:
    provider_options: tuple[Any, ...] = ()
    camera_options: tuple[str, ...] = ()
    providers_loading: bool = False
    cameras_loading: bool = False
    provider_revision: int = 0
    camera_revision: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LoadProviderOptions(UiIntent):
    force: bool = False


@dataclass(frozen=True, slots=True)
class LoadCameraOptions(UiIntent):
    force: bool = False


@dataclass(frozen=True, slots=True)
class CameraDeviceSelected(UiIntent):
    value: str
