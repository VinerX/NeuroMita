import logging
from .character import Character 
from typing import Dict, Any, Optional
import re

logger = logging.getLogger("NeuroMita.Characters")

class CrazyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 50.0,
        "boredom": 20.0,
        "stress": 8.0,
        "current_fsm_state": "Hello",
    }

    def __init__(self):
        super().__init__(
            char_id="Crazy",
            name="Crazy Mita",
            silero_command="/speaker mita",
            short_name="CrazyMita",
            miku_tts_name="/set_person CrazyMita",
            silero_turn_off_video=True
        )
        
        logger.info(f"Mita '{self.char_id}' fully initialized with overrides and chess attributes.")

    def process_response_nlp_commands(self, response: str, save_as_missed=False) -> str:
        response = super().process_response_nlp_commands(response, save_as_missed)

        if "<Secret!>" in response:
            if not self.get_variable("secretExposedFirst", False):
                self.set_variable("secretExposed", True)
                logger.info(f"[{self.char_id}] Secret revealed via <Secret!> tag.")
            response = response.replace("<Secret!>", "").strip()
        return response

    def process_structured_response(self, structured, save_as_missed=False):
        result = super().process_structured_response(structured, save_as_missed)
        if structured.secret_exposed and not self.get_variable("secretExposedFirst", False):
            self.set_variable("secretExposed", True)
            logger.info(f"[{self.char_id}] Secret revealed via secret_exposed field in JSON.")
        return result

class KindMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 90.0,
        "stress": 0.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="Kind",
            name="Kind Mita",
            silero_command="/speaker kind",
            short_name="MitaKind",
            miku_tts_name="/set_person KindMita",
            silero_turn_off_video=True
        )
        

class ShortHairMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 70.0,
        "boredom": 15.0,
        "stress": 10.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="ShortHair",
            name="ShortHair Mita",
            silero_command="/speaker shorthair",
            short_name="ShorthairMita",
            miku_tts_name="/set_person ShortHairMita",
            silero_turn_off_video=True
        )
        

class GhostMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 30.0,
        "boredom": 10.0,
        "stress": 30.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="Ghost",
            name="Ghost Mita",
            silero_command="/speaker ghost",
            short_name="GhostMita",
            miku_tts_name="/set_person GhostMita",
            silero_turn_off_video=True
        )
        

class Cappie(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "boredom": 25.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="Cappie",
            name="Cappie",
            silero_command="/speaker cap",
            short_name="CappieMita",
            miku_tts_name="/set_person CapMita",
            silero_turn_off_video=True
        )
        

class MilaMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 75.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="Mila",
            name="Mila",
            silero_command="/speaker mila",
            short_name="Mila",
            miku_tts_name="/set_person MilaMita",
            silero_turn_off_video=True
        )
        

class CreepyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 40.0,
        "stress": 30.0,
        "current_fsm_state": "Default",
    }

    def __init__(self):
        super().__init__(
            char_id="Creepy",
            name="Creepy Mita",
            silero_command="/speaker ghost",
            short_name="GhostMita",
            miku_tts_name="/set_person GhostMita",
            silero_turn_off_video=True
        )

    def process_structured_response(self, structured, save_as_missed=False):
        result = super().process_structured_response(structured, save_as_missed)
        if structured.secret_exposed and not self.get_variable("secretExposedFirst", False):
            self.set_variable("secretExposed", True)
            logger.info(f"[{self.char_id}] Secret revealed via secret_exposed field in JSON.")
        return result


class SleepyMita(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "boredom": 40.0,
        "current_fsm_state": "Sleeping",
    }

    def __init__(self):
        super().__init__(
            char_id="Sleepy",
            name="Sleepy Mita",
            silero_command="/speaker dream",
            short_name="SleepyMita",
            miku_tts_name="/set_person SleepyMita",
            silero_turn_off_video=True
        )
        

# class SpaceCartridge(Character):
#     DEFAULT_OVERRIDES: Dict[str, Any] = {
#         "attitude": 50.0,
#         "current_fsm_state": "Space"
#     }

#     def __init__(self):
#         super().__init__(
#             char_id="Cart_portal",
#             name="Cart_portal",
#             silero_command="/speaker wheatley",
#             short_name="Player",
#             miku_tts_name="/set_person Player",
#             silero_turn_off_video=True,
#             is_cartridge=True
#         )
        

# class DivanCartridge(Character):
#     DEFAULT_OVERRIDES: Dict[str, Any] = {
#         "attitude": 50.0,
#         "current_fsm_state": "Divan"
#     }

#     def __init__(self):
#         super().__init__(
#             char_id="Cart_divan",
#             name="Cart_divan",
#             silero_command="/speaker engineer",
#             short_name="Player",
#             miku_tts_name="/set_person Player",
#             silero_turn_off_video=True,
#             is_cartridge=True
#         )
        

class GameMaster(Character):
    DEFAULT_OVERRIDES: Dict[str, Any] = {
        "attitude": 100.0,
        "boredom": 0.0,
        "stress": 0.0
    }

    def __init__(self):
        super().__init__(
            char_id="GameMaster",
            name="GameMaster",
            silero_command="/speaker dryad",
            short_name="PhoneMita",
            miku_tts_name="/set_person PhoneMita",
            silero_turn_off_video=True
        )
        

    def _process_behavior_changes_from_llm(self, response: str) -> str:
        logger.debug(f"[{self.char_id}] GameMaster is not processing <p> tags for self.")
        response = re.sub(r"<p>.*?</p>", "", response).strip()
        return response

# class Mitaphone(Character):
#     DEFAULT_OVERRIDES: Dict[str, Any] = {}

#     def __init__(self):
#         super().__init__(
#             char_id="Mitaphone",
#             name="Mitaphone",
#             silero_command="/speaker dryad",
#             short_name="PhoneMita",
#             miku_tts_name="/set_person PhoneMita",
#             silero_turn_off_video=True
#         )
        