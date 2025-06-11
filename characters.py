# File: NeuroMita/characters.py
import logging
from character import Character # From NeuroMita/character.py
from typing import Dict, Any, Optional
import re
# import multiprocessing # Заменяем на threading для GUI, но Queue пока оставим от multiprocessing
import multiprocessing # Оставляем для Queue, т.к. они process-safe и thread-safe
import threading # Добавляем для запуска GUI в потоке
import importlib 
import os 

logger = logging.getLogger("NeuroMita.Characters")

class CrazyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 50.0,
        "boredom": 20.0,
        "stress": 8.0,
        "current_fsm_state": "Hello",
    }

    def __init__(self, char_id: str, name: str, silero_command: str, short_name: str,
                 miku_tts_name: str = "Player", silero_turn_off_video: bool = False,
                 initial_vars_override: Dict[str, Any] | None = None):
        super().__init__(char_id, name, silero_command, short_name,
                         miku_tts_name, silero_turn_off_video, initial_vars_override)


        logger.info(f"Mita '{char_id}' fully initialized with overrides and chess attributes.")




    def process_response_nlp_commands(self, response: str) -> str:
        response = super().process_response_nlp_commands(response)

        if "<Secret!>" in response:
            if not self.get_variable("secretExposedFirst", False):
                self.set_variable("secretExposed", True)
                logger.info(f"[{self.char_id}] Secret revealed via <Secret!> tag. Attitude/boredom may be set by DSL or <p>.")
            response = response.replace("<Secret!>", "").strip()
        return response

class KindMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 90.0,
        "stress": 0.0,
        "current_fsm_state": "Default",
    }

class ShortHairMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 70.0,
        "boredom": 15.0,
        "stress": 10.0,
        "current_fsm_state": "Default",
    }

class CappyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "boredom": 25.0,
        "current_fsm_state": "Default",
    }

class MilaMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 75.0,
        "current_fsm_state": "Default",
    }

class CreepyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 40.0,
        "stress": 30.0,
        "current_fsm_state": "Default",
    }

class SleepyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "boredom": 40.0,
        "current_fsm_state": "Sleeping",
    }

class SpaceCartridge(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 50.0, "current_fsm_state": "Space"}
    # def __init__(self, char_id: str, name: str, silero_command: str, short_name: str,
    #              miku_tts_name: str = "Player", silero_turn_off_video: bool = False,
    #              initial_vars_override: Dict[str, Any] | None = None):
    #     # Cartridges might not need all the same params, adjust as necessary
    #     # Or, they are instantiated with default names if not interactive in the same way.
    #     # For now, keeping constructor consistent.
    #     super().__init__(char_id, name, silero_command, short_name,
    #                      miku_tts_name, silero_turn_off_video, initial_vars_override)

class DivanCartridge(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 50.0, "current_fsm_state": "Divan"}
    # def __init__(self, char_id: str, name: str, silero_command: str, short_name: str, 
    #              miku_tts_name: str = "Player", silero_turn_off_video: bool = False,
    #              initial_vars_override: Dict[str, Any] | None = None):
    #     super().__init__(char_id, name, silero_command, short_name,
    #                      miku_tts_name, silero_turn_off_video, initial_vars_override)

class GameMaster(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 100.0, "boredom": 0.0, "stress": 0.0}

    def _process_behavior_changes_from_llm(self, response: str) -> str:
        logger.debug(f"[{self.char_id}] GameMaster is not processing <p> tags for self.")
        response = re.sub(r"<p>.*?</p>", "", response).strip()
        return response

    def get_llm_system_prompt_string(self) -> str:
        try:
            from SettingsManager import SettingsManager as settings
            current_instruction = settings.get("GM_SMALL_PROMPT", "")
            self.set_variable("GM_INSTRUCTION", current_instruction)
        except ImportError:
            logger.warning(f"[{self.char_id}] SettingsManager not found for GameMaster's GM_INSTRUCTION.")
            self.set_variable("GM_INSTRUCTION", "")
        except Exception as e:
            logger.error(f"[{self.char_id}] Error accessing GM_SMALL_PROMPT: {e}")
            self.set_variable("GM_INSTRUCTION", "")
        return super().get_llm_system_prompt_string()