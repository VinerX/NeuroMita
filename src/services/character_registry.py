from __future__ import annotations

from typing import Any, Dict, List

from services.contracts import CharacterRegistry, SettingsService


class ManagedCharacterRegistry(CharacterRegistry):
    """CharacterRegistry поверх CharacterManager. Владелец — CharacterController."""

    def __init__(self, character_manager) -> None:
        self._manager = character_manager

    def get(self, character_id: str) -> Any:
        if not character_id:
            return None
        return self._manager.get_character(str(character_id))

    def all_ids(self) -> List[str]:
        return list(self._manager.get_all_characters())

    def current(self) -> Any:
        return self._manager.current_character

    def current_id(self) -> str:
        return str(getattr(self.current(), "char_id", "") or "")

    def current_profile(self) -> Dict[str, Any]:
        ref = self.current()
        if ref is None:
            return {}
        if hasattr(ref, "to_voice_profile"):
            return ref.to_voice_profile()
        return {
            "character_id": str(getattr(ref, "char_id", "") or ""),
            "name": str(getattr(ref, "name", "") or ""),
        }

    def current_name(self) -> str:
        return str(getattr(self.current(), "name", "") or "")


class SettingsOnlyCharacterRegistry(CharacterRegistry):
    """GUI-only режим: персонажи не загружены, известен только выбранный id."""

    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings

    def _selected_id(self) -> str:
        return str(self._settings.get("CHARACTER", "") or "").strip()

    def get(self, character_id: str) -> Any:
        return None

    def all_ids(self) -> List[str]:
        selected = self._selected_id()
        return [selected] if selected else []

    def current(self) -> Any:
        return None

    def current_id(self) -> str:
        return self._selected_id()

    def current_profile(self) -> Dict[str, Any]:
        selected = self._selected_id()
        if not selected:
            return {}
        return {"character_id": selected, "name": selected}

    def current_name(self) -> str:
        return self._selected_id()

    def name_of(self, character_id: str) -> str:
        return str(character_id or "")
