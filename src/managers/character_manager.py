from __future__ import annotations

from typing import Dict, List, Optional, Type

from main_logger import logger
from characters.character import Character
from characters import (
    CrazyMita,
    KindMita,
    ShortHairMita,
    Cappie,
    MilaMita,
    CreepyMita,
    SleepyMita,
    GameMaster,
    GhostMita,
)
from managers.character_resource_manager import CharacterResourceManager


class CharacterManager:
    """Владеет персонажами и единым реестром их runtime-ресурсов."""

    def __init__(self, initial_character_id: Optional[str] = None):
        self.characters: Dict[str, Character] = {}
        self.current_character: Optional[Character] = None
        self.current_character_to_change: str = initial_character_id or ""
        self.resources = CharacterResourceManager()

        self._init_characters()

        self.crazy_mita_character: Optional[Character] = self.characters.get("Crazy")
        self.GameMaster: Optional[Character] = self.characters.get("GameMaster")

        self.current_character = (
            self.characters.get(self.current_character_to_change)
            or self.crazy_mita_character
            or next(iter(self.characters.values()), None)
        )
        self.current_character_to_change = ""

        if self.current_character:
            self.current_character.ensure_runtime_loaded()
            logger.info(f"[CharacterManager] Current character: {self.current_character.char_id}")
        else:
            logger.error("[CharacterManager] No characters initialized!")

    def _init_characters(self) -> None:
        character_classes: List[Type[Character]] = [
            CrazyMita,
            KindMita,
            Cappie,
            ShortHairMita,
            MilaMita,
            SleepyMita,
            CreepyMita,
            GhostMita,
            GameMaster,
        ]

        self.characters = {}
        for cls in character_classes:
            character = cls()
            character.bind_resource_manager(self.resources)
            self.characters[character.char_id] = character

        logger.info(
            f"[CharacterManager] Initialized {len(self.characters)} characters: "
            f"{list(self.characters.keys())}"
        )

    def get_all_characters(self) -> List[str]:
        return list(self.characters.keys())

    def get_character(self, char_id: str) -> Optional[Character]:
        if not char_id:
            return None
        character = self.characters.get(char_id)
        if character is not None:
            character.ensure_runtime_loaded()
        return character

    def set_character_to_change(self, char_id: str) -> None:
        self.current_character_to_change = str(char_id or "")

    def check_change_current_character(self) -> None:
        if not self.current_character_to_change:
            return

        target = self.current_character_to_change
        self.current_character_to_change = ""

        if target not in self.characters:
            logger.warning(f"[CharacterManager] Attempted to change to unknown character: {target}")
            return

        self.current_character = self.characters[target]
        logger.info(f"[CharacterManager] Changing character to {target}")
        try:
            self.current_character.reload_character_data()
        except Exception as exc:
            logger.error(
                f"[CharacterManager] Failed to reload character data for {target}: {exc}",
                exc_info=True,
            )

    def shutdown(self) -> None:
        self.resources.shutdown()
