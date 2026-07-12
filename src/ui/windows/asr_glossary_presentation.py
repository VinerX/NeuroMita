from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ui.mvvm import FrozenMapping, UiIntent


@dataclass(frozen=True, slots=True)
class AsrGlossaryState:
    models: tuple[FrozenMapping, ...] = ()
    loading: bool = False
    error: str | None = None
    catalog_revision: int = 0
    settings_engine_id: str | None = None
    settings_schema: tuple[FrozenMapping, ...] = ()
    settings_values: FrozenMapping = field(default_factory=FrozenMapping)
    settings_loading: bool = False
    settings_error: str | None = None
    settings_revision: int = 0
    installing_model_id: str | None = None
    install_progress: int | None = None
    install_status: str = ""
    install_error: str | None = None
    install_revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshAsrGlossary(UiIntent):
    force: bool = True


@dataclass(frozen=True, slots=True)
class LoadAsrSettings(UiIntent):
    engine_id: str


@dataclass(frozen=True, slots=True)
class InstallAsrModel(UiIntent):
    engine_id: str


@dataclass(frozen=True, slots=True)
class SetAsrOption(UiIntent):
    engine_id: str
    key: str
    value: Any