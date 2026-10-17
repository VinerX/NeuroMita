from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import FrozenMapping, immutable_payload


@dataclass(frozen=True, slots=True)
class CharacterSettingsState:
    selected_character_id: str | None = None
    active_character_id: str = ""
    character_names: FrozenMapping[str, str] = field(default_factory=FrozenMapping)
    provider_choices: tuple[FrozenMapping[str, Any], ...] = ()
    snapshot_loading: bool = False


class CharacterSettingsViewModel(IntentViewModel[CharacterSettingsState]):
    def __init__(self, parent=None, *, selected_character_id=None, active_character_id=""):
        super().__init__(CharacterSettingsState(
            selected_character_id=selected_character_id, active_character_id=active_character_id,
        ), parent)

    def select_character(self, character_id: str) -> None:
        self.update_state(selected_character_id=str(character_id or "").strip())

    def set_active_character(self, character_id: str) -> None:
        self.update_state(active_character_id=str(character_id or "").strip())

    def set_provider_choices(self, choices) -> None:
        self.update_state(provider_choices=tuple(immutable_payload(choice) for choice in choices))

    def set_character_names(self, names) -> None:
        self.update_state(character_names=immutable_payload(names))
