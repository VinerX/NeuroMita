from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiIntent


@dataclass(frozen=True, slots=True)
class CharacterStatState:
    value: float = 0.0
    minimum: float = 0.0
    maximum: float = 100.0


@dataclass(frozen=True, slots=True)
class CharacterParamState:
    name: str
    kind: str
    value: float | bool | str | None
    minimum: float = 0.0
    maximum: float = 100.0


@dataclass(frozen=True, slots=True)
class CharacterStatePanelState:
    character_id: str = ""
    attitude: CharacterStatState = CharacterStatState()
    boredom: CharacterStatState = CharacterStatState()
    stress: CharacterStatState = CharacterStatState()
    secret_exposed: bool = False
    custom_params: tuple[CharacterParamState, ...] = ()
    all_variables_text: str = "—"
    loading: bool = False
    revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshCharacterState(UiIntent):
    rebuild: bool = False