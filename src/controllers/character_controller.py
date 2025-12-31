from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.events import get_event_bus, Events, Event
from main_logger import logger
from managers.character_manager import CharacterManager


class CharacterController:
    """
    Единственная точка владения персонажами:
    - хранит CharacterManager
    - даёт доступ к текущему персонажу
    - переключает текущего персонажа
    - отдаёт плоский профиль для UI/озвучки
    """

    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        initial_character_id = str(self.settings.get("CHARACTER") or "")
        self.character_manager = CharacterManager(initial_character_id=initial_character_id)

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Character.GET_ALL, self._on_get_all, weak=False)
        eb.subscribe(Events.Character.GET, self._on_get, weak=False)

        eb.subscribe(Events.Character.GET_CURRENT_PROFILE, self._on_get_current_profile, weak=False)
        eb.subscribe(Events.Character.GET_CURRENT_NAME, self._on_get_current_name, weak=False)

        eb.subscribe(Events.Character.SET_CURRENT, self._on_set_current, weak=False)

        eb.subscribe(Events.Character.RELOAD_DATA, self._on_reload_data, weak=False)
        eb.subscribe(Events.Character.RELOAD_PROMPTS, self._on_reload_prompts, weak=False)

        eb.subscribe(Events.Character.CLEAR_HISTORY, self._on_clear_history, weak=False)
        eb.subscribe(Events.Character.CLEAR_ALL_HISTORIES, self._on_clear_all_histories, weak=False)

    def get_current_ref(self):
        return self.character_manager.current_character

    def get_ref(self, character_id: str):
        if not character_id:
            return None
        return self.character_manager.get_character(str(character_id))

    def _profile_from(self, ch) -> Dict[str, Any]:
        if ch is None:
            return {}
        if hasattr(ch, "to_voice_profile"):
            return ch.to_voice_profile()
        return {
            "character_id": str(getattr(ch, "char_id", "") or ""),
            "name": str(getattr(ch, "name", "") or ""),
        }

    def _on_get_all(self, event: Event) -> List[str]:
        return self.character_manager.get_all_characters()

    def _on_get(self, event: Event):
        data = event.data or {}
        character_id = data.get("character_id")
        if not character_id:
            return None
        return self.get_ref(str(character_id))

    def _on_get_current_profile(self, event: Event):
        return self._profile_from(self.get_current_ref())

    def _on_get_current_name(self, event: Event):
        ch = self.get_current_ref()
        return str(getattr(ch, "name", "") or "")

    def _on_set_current(self, event: Event):
        data = event.data or {}
        character_id = data.get("character_id")
        if not character_id:
            return False

        before = getattr(self.character_manager.current_character, "char_id", None)
        self.character_manager.set_character_to_change(str(character_id))
        self.character_manager.check_change_current_character()
        after = getattr(self.character_manager.current_character, "char_id", None)

        if before != after:
            ch = self.character_manager.current_character
            self.event_bus.emit(Events.Character.CURRENT_CHANGED, {
                "character_id": after or "",
                "character_name": str(getattr(ch, "name", "") or "") if ch else ""
            })
        return True

    def _on_reload_data(self, event: Event):
        ch = self.get_current_ref()
        if ch and hasattr(ch, "reload_character_data"):
            ch.reload_character_data()
            return True
        return False

    def _on_reload_prompts(self, event: Event):
        data = event.data or {}
        character_id = data.get("character_id")
        ch = self.get_ref(str(character_id)) if character_id else self.get_current_ref()
        if ch and hasattr(ch, "reload_prompts"):
            ch.reload_prompts()
            return True
        return False

    def _on_clear_history(self, event: Event):
        ch = self.get_current_ref()
        if ch and hasattr(ch, "clear_history"):
            ch.clear_history()
            return True
        return False

    def _on_clear_all_histories(self, event: Event):
        for ch in self.character_manager.characters.values():
            if hasattr(ch, "clear_history"):
                ch.clear_history()
        return True