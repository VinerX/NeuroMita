from __future__ import annotations

from typing import Dict, List, Optional, Type

from main_logger import logger
from characters.character import Character
from characters import (
    CrazyMita, KindMita, ShortHairMita, CappyMita, MilaMita, CreepyMita, SleepyMita,
    GameMaster, SpaceCartridge, DivanCartridge, GhostMita, Mitaphone
)

from managers.history_manager import HistoryManager


class CharacterManager:
    """
    Отвечает за:
    - создание персонажей
    - хранение словаря characters
    - current_character и переключение персонажа
    """

    def __init__(self, initial_character_id: Optional[str] = None):
        self.characters: Dict[str, Character] = {}
        self.current_character: Optional[Character] = None
        self.current_character_to_change: str = initial_character_id or ""

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
            logger.info(f"[CharacterManager] Current character: {self.current_character.char_id}")
        else:
            logger.error("[CharacterManager] No characters initialized!")

    def _ensure_unique_history_manager(self, ch: Character) -> None:
        char_id = str(getattr(ch, "char_id", "") or "").strip()
        name = str(getattr(ch, "name", "") or "").strip()

        if not char_id:
            return

        try:
            ch.history_manager = HistoryManager(character_name=name or char_id, character_id=char_id)
        except Exception as e:
            logger.error(f"[CharacterManager] Failed to attach unique HistoryManager for {char_id}: {e}", exc_info=True)

    def _init_characters(self) -> None:
        character_classes: List[Type[Character]] = [
            CrazyMita,
            KindMita,
            CappyMita,
            ShortHairMita,
            MilaMita,
            SleepyMita,
            CreepyMita,
            GhostMita,
            SpaceCartridge,
            DivanCartridge,
            GameMaster,
            Mitaphone,
        ]

        self.characters = {}
        for cls in character_classes:
            ch = cls()
            self._ensure_unique_history_manager(ch)
            self.characters[ch.char_id] = ch

        logger.info(f"[CharacterManager] Initialized {len(self.characters)} characters: {list(self.characters.keys())}")

    def get_all_characters(self) -> List[str]:
        return list(self.characters.keys())

    def get_character(self, char_id: str) -> Optional[Character]:
        if not char_id:
            return None
        return self.characters.get(char_id)

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
            if hasattr(self.current_character, "reload_character_data"):
                self.current_character.reload_character_data()
        except Exception as e:
            logger.error(f"[CharacterManager] Failed to reload character data for {target}: {e}", exc_info=True)