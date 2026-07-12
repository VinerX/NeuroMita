from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class VoiceModelsState:
    models: tuple[Any, ...] = ()
    installed_models: frozenset[str] = frozenset()
    dependencies_status: Any = ()
    loading: bool = False
    operation: str | None = None
    operation_model_id: str | None = None
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshVoiceModels(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class InstallVoiceModel(UiIntent):
    model_id: str


@dataclass(frozen=True, slots=True)
class UninstallVoiceModel(UiIntent):
    model_id: str


@dataclass(frozen=True, slots=True)
class SaveVoiceSettings(UiIntent):
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CloseVoiceModels(UiIntent):
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OpenVoiceDocumentation(UiIntent):
    path: str


@dataclass(frozen=True, slots=True)
class RequestVoiceDescription(UiIntent):
    key: str | None


@dataclass(frozen=True, slots=True)
class VoiceDescriptionEffect(UiEffect):
    text: str


@dataclass(frozen=True, slots=True)
class VoiceOperationRejectedEffect(UiEffect):
    message: str