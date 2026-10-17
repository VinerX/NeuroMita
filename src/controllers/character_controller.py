from __future__ import annotations

from core.events import get_event_bus, Events, Event
from core.services import services
from main_logger import logger
from managers.character_manager import CharacterManager
from services.character_registry import ManagedCharacterRegistry
from services.contracts import CharacterRegistry


class CharacterController:
    """
    Единственная точка владения персонажами:
    - хранит CharacterManager
    - регистрирует CharacterRegistry (чтение)
    - обрабатывает команды-события (переключение, reload, clear)
    """

    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        initial_character_id = str(self.settings.get("CHARACTER") or "")
        self.character_manager = CharacterManager(initial_character_id=initial_character_id)

        self.registry = services().register(
            CharacterRegistry, ManagedCharacterRegistry(self.character_manager), replace=True
        )

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Character.SET_CURRENT, self._on_set_current, weak=False)

        eb.subscribe(Events.Character.RELOAD_DATA, self._on_reload_data, weak=False)
        eb.subscribe(Events.Character.RELOAD_ALL_DATA, self._on_reload_all_data, weak=False)
        eb.subscribe(Events.Character.RELOAD_PROMPTS, self._on_reload_prompts, weak=False)

        eb.subscribe(Events.Character.CLEAR_HISTORY, self._on_clear_history, weak=False)
        eb.subscribe(Events.Character.CLEAR_ALL_HISTORIES, self._on_clear_all_histories, weak=False)

    def get_current_ref(self):
        return self.character_manager.current_character

    def get_ref(self, character_id: str):
        if not character_id:
            return None
        return self.character_manager.get_character(str(character_id))

    def _on_set_current(self, event: Event):
        data = event.data or {}
        character_id = str(data.get("character_id") or "").strip()
        if not character_id:
            return False

        before = getattr(self.character_manager.current_character, "char_id", None)
        self.character_manager.set_character_to_change(str(character_id))
        self.character_manager.check_change_current_character()
        after = getattr(self.character_manager.current_character, "char_id", None)
        if after != character_id:
            return False

        if before == after and data.get("reload_data", False):
            self._on_reload_data(Event(Events.Character.RELOAD_DATA, {"character_id": after}))

        if before != after:
            ch = self.character_manager.current_character
            self.event_bus.emit(Events.Character.CURRENT_CHANGED, {
                "character_id": after or "",
                "character_name": str(getattr(ch, "display_name", "") or "") if ch else ""
            })
        return True

    def _character_for_event(self, event: Event):
        data = event.data or {}
        if "character_id" in data:
            return self.get_ref(str(data.get("character_id") or "").strip())
        return self.get_current_ref()

    def _on_reload_data(self, event: Event):
        ch = self._character_for_event(event)
        if ch and hasattr(ch, "reload_character_data"):
            ch.reload_character_data()
            self.event_bus.emit(Events.Character.DATA_RELOADED, {"character_id": ch.char_id})
            return True
        return False

    def _on_reload_all_data(self, event: Event):
        success = True
        for ch in self.character_manager.get_loaded_characters():
            try:
                ch.reload_character_data()
                self.event_bus.emit(Events.Character.DATA_RELOADED, {"character_id": ch.char_id})
            except Exception:
                success = False
                logger.exception("Failed to reload character %s", ch.char_id)
        return success

    def _on_reload_prompts(self, event: Event):
        return self._on_reload_data(event)

    def _on_clear_history(self, event: Event):
        ch = self._character_for_event(event)
        if ch and hasattr(ch, "clear_history"):
            ch.clear_history()
            self.event_bus.emit(Events.Character.HISTORY_CLEARED, {"character_id": ch.char_id})
            return True
        return False

    def _on_clear_all_histories(self, event: Event):
        self.character_manager.clear_all_histories()
        self.event_bus.emit(Events.Character.HISTORY_CLEARED, {"all_characters": True})
        return True
