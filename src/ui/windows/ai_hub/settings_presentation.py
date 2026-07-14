from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class AIHubSettingsState:
    components: tuple[tuple[str, str], ...] = ()
    selected_component_id: str = ""
    schema: Any = ()
    values: Any = ()
    field_errors: Any = ()
    loading: bool = False
    saving: bool = False
    dirty: bool = False
    status_text: str = ""
    components_revision: int = 0
    form_revision: int = 0
    errors_revision: int = 0


@dataclass(frozen=True, slots=True)
class ApplyAIHubSettingsRows(UiIntent):
    rows: Any
    category: str | None


@dataclass(frozen=True, slots=True)
class SelectAIHubSettingsComponent(UiIntent):
    component_id: str


@dataclass(frozen=True, slots=True)
class AIHubSettingsChanged(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SaveAIHubSettings(UiIntent):
    values: Any


@dataclass(frozen=True, slots=True)
class ResetAIHubSettings(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class AIHubSettingsWarning(UiEffect):
    message: str
