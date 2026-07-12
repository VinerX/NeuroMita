from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class SandboxModelItem:
    preset_id: int
    label: str


@dataclass(frozen=True, slots=True)
class SandboxMemoryState:
    messages: str = "—"
    memories: str = "—"
    forgotten: str = "—"
    missing: str = "—"
    trash: str = "—"
    last: str = "—"
    db_size: str = "—"
    loading: bool = False


@dataclass(frozen=True, slots=True)
class SandboxBudgetState:
    used: int = 0
    maximum: int = 32000
    estimated_cost: float = 0.0
    loading: bool = False


@dataclass(frozen=True, slots=True)
class SandboxLastRequestState:
    status: str = "idle"
    error: str = ""
    latency_seconds: float | None = None
    model_name: str = ""
    context_tokens: int = 0
    finished_at: str = ""


@dataclass(frozen=True, slots=True)
class SandboxStatusState:
    rag_preset_name: str = "Custom"
    rag_model_name: str = ""
    indicators: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class SandboxState:
    settings: tuple[tuple[str, Any], ...] = ()
    model_items: tuple[SandboxModelItem, ...] = ()
    current_model_id: int | None = None
    prompt_items: tuple[str, ...] = ()
    current_prompt: str = ""
    character_items: tuple[str, ...] = ()
    current_character_id: str = ""
    memory: SandboxMemoryState = field(default_factory=SandboxMemoryState)
    budget: SandboxBudgetState = field(default_factory=SandboxBudgetState)
    last_request: SandboxLastRequestState = field(default_factory=SandboxLastRequestState)
    status: SandboxStatusState = field(default_factory=SandboxStatusState)
    selectors_loading: bool = False
    error: str | None = None
    revision: int = 0


@dataclass(frozen=True, slots=True)
class SandboxActivated(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SandboxRefreshRequested(UiIntent):
    section: str = "all"


@dataclass(frozen=True, slots=True)
class SandboxModelSelected(UiIntent):
    preset_id: int


@dataclass(frozen=True, slots=True)
class SandboxPromptSelected(UiIntent):
    prompt_set: str


@dataclass(frozen=True, slots=True)
class SandboxCharacterSelected(UiIntent):
    character_id: str
    reload_data: bool = True


@dataclass(frozen=True, slots=True)
class SandboxSettingChanged(UiIntent):
    key: str
    value: Any


@dataclass(frozen=True, slots=True)
class SandboxClearHistoryRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SandboxOpenHistoryRequested(UiIntent):
    character_id: str


@dataclass(frozen=True, slots=True)
class SandboxRefreshVoicePanelsRequested(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class SandboxHistoryCleared(UiEffect):
    pass


@dataclass(frozen=True, slots=True)
class SandboxOpenHistory(UiEffect):
    character_id: str


@dataclass(frozen=True, slots=True)
class SandboxShowError(UiEffect):
    title: str
    message: str