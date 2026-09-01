from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class EmbedProviderState:
    preset_items: tuple[tuple[str, Any], ...] = ()
    selected_preset_id: Any = None
    config: Any = None
    loading_presets: bool = False
    loading_config: bool = False
    operation: str | None = None
    testing: bool = False
    testing_preset_id: Any = None
    status_text: str = ""
    status_kind: str = "normal"
    downloaded: bool = False
    error: str | None = None
    items_revision: int = 0
    config_revision: int = 0


@dataclass(frozen=True, slots=True)
class ActivateEmbedProvider(UiIntent):
    selected_preset_id: Any = None


@dataclass(frozen=True, slots=True)
class RefreshEmbedPresets(UiIntent):
    selected_preset_id: Any = None
    force: bool = False


@dataclass(frozen=True, slots=True)
class SelectEmbedPreset(UiIntent):
    preset_id: Any


@dataclass(frozen=True, slots=True)
class SaveEmbedPreset(UiIntent):
    payload: Any
    hf_token: str = ""


@dataclass(frozen=True, slots=True)
class AddEmbedPreset(UiIntent):
    name: str


@dataclass(frozen=True, slots=True)
class DeleteEmbedPreset(UiIntent):
    preset_id: Any


@dataclass(frozen=True, slots=True)
class ReorderEmbedPresets(UiIntent):
    custom_ids: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class TestEmbedPreset(UiIntent):
    preset_id: Any


@dataclass(frozen=True, slots=True)
class DownloadEmbedModel(UiIntent):
    payload: Any
    hf_token: str = ""


@dataclass(frozen=True, slots=True)
class EmbedProviderShowError(UiEffect):
    message: str
