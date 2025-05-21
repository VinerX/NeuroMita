# File: NeuroMita/characters.py
import logging
from character import Character # From NeuroMita/character.py
from typing import Dict, Any
import re

logger = logging.getLogger("NeuroMita.Characters")

class CrazyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 50.0, # Floats for consistency
        "boredom": 20.0,
        "stress": 8.0,
        "current_fsm_state": "Hello", # Specific initial FSM state for CrazyMita
    }

    def __init__(self, char_id: str, name: str, silero_command: str, short_name: str, 
                 miku_tts_name: str = "Player", silero_turn_off_video: bool = False,
                 initial_vars_override: Dict[str, Any] | None = None):
        super().__init__(char_id, name, silero_command, short_name, 
                         miku_tts_name, silero_turn_off_video, initial_vars_override)
        logger.info(f"CrazyMita '{char_id}' fully initialized with overrides.")

    def process_response_nlp_commands(self, response: str) -> str:
        # Base class handles <p> and <memory>
        response = super().process_response_nlp_commands(response)

        # CrazyMita specific: <Secret!> tag
        if "<Secret!>" in response:
            # secretExposedFirst is set by DSL (personality_selector.script) when it first sees secretExposed=True
            # This tag essentially forces secretExposed to True earlier if LLM emits it.
            if not self.get_variable("secretExposedFirst", False):
                self.set_variable("secretExposed", True)
                logger.info(f"[{self.char_id}] Secret revealed via <Secret!> tag. Attitude/boredom may be set by DSL or <p>.")
                # Direct attitude/boredom changes here might conflict with <p> tags or DSL logic.
                # The DSL's personality_selector should react to secretExposed=True.
                # If LLM provides <p>0,0,0</p><Secret!>, then these would be overridden.
                # self.set_variable("attitude", 15.0) 
                # self.set_variable("boredom", 20.0)
            response = response.replace("<Secret!>", "").strip()
        return response


class KindMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 90.0,
        "stress": 0.0,
        "current_fsm_state": "Default",
    }
    # __init__ can be inherited if no extra params are needed beyond Character's

class ShortHairMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 70.0, 
        "boredom": 15.0, 
        "stress": 10.0,
        "current_fsm_state": "Default",
    }
    # Add specific process_response_nlp_commands if ShortHairMita has unique tags

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
        "current_fsm_state": "Default", # Or a more creepy state
    }

class SleepyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "boredom": 40.0,
        "current_fsm_state": "Sleeping", # Example
    }

# Cartridges and GameMaster would also be defined here, inheriting from Character
# and potentially having their own DEFAULT_OVERRIDES.

class SpaceCartridge(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 50.0, "current_fsm_state": "Space"}
    def __init__(self, char_id: str, name: str, silero_command: str, short_name: str, 
                 miku_tts_name: str = "Player", silero_turn_off_video: bool = False,
                 initial_vars_override: Dict[str, Any] | None = None):
        # Cartridges might not need all the same params, adjust as necessary
        # Or, they are instantiated with default names if not interactive in the same way.
        # For now, keeping constructor consistent.
        super().__init__(char_id, name, silero_command, short_name, 
                         miku_tts_name, silero_turn_off_video, initial_vars_override)

class DivanCartridge(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 50.0, "current_fsm_state": "Divan"}
    # ... similar __init__ if needed

class GameMaster(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {"attitude": 100.0, "boredom": 0.0, "stress": 0.0}
    
    def _process_behavior_changes_from_llm(self, response: str) -> str:
        # GameMaster does not use <p> tags for its own attitude/boredom/stress
        logger.debug(f"[{self.char_id}] GameMaster is not processing <p> tags for self.")
        # We still need to remove the tag if present, just don't apply changes.
        response = re.sub(r"<p>.*?</p>", "", response).strip()
        return response
    
    def get_llm_system_prompt_string(self) -> str:
        # Example: Inject GM_SMALL_PROMPT from settings if it's a global or accessible way
        try:
            from SettingsManager import SettingsManager as settings # Ensure this import works in your structure
            current_instruction = settings.get("GM_SMALL_PROMPT", "")
            self.set_variable("GM_INSTRUCTION", current_instruction)
        except ImportError:
            logger.warning(f"[{self.char_id}] SettingsManager not found for GameMaster's GM_INSTRUCTION.")
            self.set_variable("GM_INSTRUCTION", "")
        return super().get_llm_system_prompt_string()