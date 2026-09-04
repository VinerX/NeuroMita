from __future__ import annotations
from core.error_utils import format_exception

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from characters import (
    Cappie,
    CrazyMita,
    CreepyMita,
    GameMaster,
    GhostMita,
    KindMita,
    MilaMita,
    ShortHairMita,
    SleepyMita,
)
from characters.character import Character
from main_logger import logger
from managers.character_resource_manager import (
    CharacterResourceManager,
    get_character_resource_manager,
)


@dataclass(frozen=True)
class CharacterDefinition:
    character_id: str
    character_name: str
    factory: Type[Character]


_CHARACTER_DEFINITIONS: tuple[CharacterDefinition, ...] = (
    CharacterDefinition("Crazy", "Crazy Mita", CrazyMita),
    CharacterDefinition("Kind", "Kind Mita", KindMita),
    CharacterDefinition("Cappie", "Cappie", Cappie),
    CharacterDefinition("ShortHair", "ShortHair Mita", ShortHairMita),
    CharacterDefinition("Mila", "Mila", MilaMita),
    CharacterDefinition("Sleepy", "Sleepy Mita", SleepyMita),
    CharacterDefinition("Creepy", "Creepy Mita", CreepyMita),
    CharacterDefinition("Ghost", "Ghost Mita", GhostMita),
    CharacterDefinition("GameMaster", "GameMaster", GameMaster),
)


class CharacterManager:
    """Owns lightweight definitions and lazily materialized Character runtimes."""

    def __init__(
        self,
        initial_character_id: Optional[str] = None,
        resources: Optional[CharacterResourceManager] = None,
    ):
        self._lock = threading.RLock()
        self._definitions = {
            definition.character_id: definition
            for definition in _CHARACTER_DEFINITIONS
        }
        self.characters: Dict[str, Character] = {}
        self.current_character: Optional[Character] = None
        self.current_character_to_change = str(initial_character_id or "")
        self.resources = resources or get_character_resource_manager()

        for definition in _CHARACTER_DEFINITIONS:
            self.resources.register_character(
                definition.character_id,
                definition.character_name,
            )

        initial_id = (
            self.current_character_to_change
            if self.current_character_to_change in self._definitions
            else "Crazy"
        )
        self.current_character_to_change = ""
        self.current_character = self.get_character(initial_id)

        if self.current_character:
            logger.info(
                f"[CharacterManager] Current character: {self.current_character.char_id}; "
                f"loaded={list(self.characters)} available={list(self._definitions)}"
            )
        else:
            logger.error("[CharacterManager] No characters initialized!")

    @property
    def crazy_mita_character(self) -> Optional[Character]:
        return self.get_loaded_character("Crazy") or (
            self.get_character("Crazy") if self.current_character is None else None
        )

    @property
    def GameMaster(self) -> Optional[Character]:
        return self.get_loaded_character("GameMaster")

    def _create_character(self, definition: CharacterDefinition) -> Character:
        character = definition.factory()
        character.bind_resource_manager(self.resources)
        self.characters[definition.character_id] = character
        logger.info(
            f"[CharacterManager] Materialized {definition.character_id}; "
            f"loaded={list(self.characters)}"
        )
        return character

    def get_all_characters(self) -> List[str]:
        return list(self._definitions)

    def get_loaded_characters(self) -> List[Character]:
        with self._lock:
            return list(self.characters.values())

    def get_loaded_character(self, char_id: str) -> Optional[Character]:
        with self._lock:
            return self.characters.get(str(char_id or ""))

    def get_character(self, char_id: str) -> Optional[Character]:
        key = str(char_id or "").strip()
        if not key:
            return None
        definition = self._definitions.get(key)
        if definition is None:
            return None

        with self._lock:
            character = self.characters.get(key)
            if character is None:
                character = self._create_character(definition)

        character.ensure_runtime_loaded()
        return character

    def set_character_to_change(self, char_id: str) -> None:
        self.current_character_to_change = str(char_id or "")

    def check_change_current_character(self) -> None:
        if not self.current_character_to_change:
            return

        target = self.current_character_to_change
        self.current_character_to_change = ""

        current_id = str(getattr(self.current_character, "char_id", "") or "")
        if current_id == target:
            return

        if target not in self._definitions:
            logger.warning(
                f"[CharacterManager] Attempted to change to unknown character: {target}"
            )
            return

        was_loaded = self.get_loaded_character(target) is not None
        character = self.get_character(target)
        if character is None:
            return
        self.current_character = character
        logger.info(f"[CharacterManager] Changing character to {target}")
        if not was_loaded:
            return
        try:
            character.reload_character_data()
        except Exception as exc:
            logger.error(
                f"[CharacterManager] Failed to reload character data for {target}: {format_exception(exc)}",
                exc_info=True,
            )

    def clear_all_histories(self) -> None:
        loaded_ids = set(self.characters)
        for character in self.get_loaded_characters():
            character.clear_history()

        for character_id in self._definitions:
            if character_id in loaded_ids:
                continue
            try:
                self.resources.history_for(character_id).clear_history()
                self.resources.memory_for(character_id).clear_memories()
                self.resources.working_state_for(character_id).clear()
            except Exception as exc:
                logger.error(
                    f"[CharacterManager] Failed to clear resources for {character_id}: {format_exception(exc)}",
                    exc_info=True,
                )
            try:
                from managers.database_manager import DatabaseManager
                from managers.rag.graph.graph_store import GraphStore

                GraphStore(DatabaseManager(), character_id).clear_for_character()
            except Exception as exc:
                logger.warning(
                    f"[{character_id}] Graph clear failed (ignored): {format_exception(exc)}",
                    exc_info=True,
                )

    def shutdown(self) -> None:
        self.resources.shutdown()
