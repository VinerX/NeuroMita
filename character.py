# File: NeuroMita/character.py
import datetime
import re
import os
import logging # Use standard logging
import sys # For traceback
import traceback # For traceback
from typing import Dict, List, Any, Optional

# Assuming dsl_engine.py is in a DSL folder within NeuroMita
from DSL.dsl_engine import DslInterpreter # PROMPTS_ROOT is managed by DslInterpreter
from DSL.path_resolver import LocalPathResolver
from DSL.post_dsl_engine import PostDslInterpreter
from MemorySystem import MemorySystem
from HistoryManager import HistoryManager
from utils import clamp, SH # SH for masking keys if needed elsewhere

import multiprocessing # Оставляем для Queue, т.к. они process-safe и thread-safe
import threading # Добавляем для запуска GUI в потоке
import importlib
import os


# Setup logger for this module
logger = logging.getLogger("NeuroMita.Character") # More specific logger name

# ANSI Escape Codes
RED_COLOR = "\033[91m"
RESET_COLOR = "\033[0m"

class Character:
    BASE_DEFAULTS: Dict[str, Any] = {
        "attitude": 60.0, # Use floats for consistency with adjustments
        "boredom": 10.0,
        "stress": 5.0,
        "secretExposed": False,
        "current_fsm_state": "Hello", # Default FSM-like state
        "available_action_level": 1,  # For command availability in DSL
        "PlayingFirst": False,
        "secretExposedFirst": False,
        "secret_exposed_event_text_shown": False,
        "LongMemoryRememberCount": 0,
        "player_name": "Игрок",
        "player_name_known": False,
        # Add any other truly common defaults for ALL characters
    }

    def __init__(self, 
                 char_id: str, 
                 name: str, 
                 # For NeuroMita specific constructor params:
                 silero_command: str, 
                 short_name: str, # NeuroMita used this
                 miku_tts_name: str = "Player", 
                 silero_turn_off_video: bool = False,
                 initial_vars_override: Dict[str, Any] | None = None,
                 is_cartridge = False
                 ): # For explicit initial values passed in
        
        self.char_id = char_id # For DSL logging and Prompts path
        self.name = name # Display name

        # NeuroMita specific attributes
        self.silero_command = silero_command
        self.silero_turn_off_video = silero_turn_off_video
        self.miku_tts_name = miku_tts_name
        self.short_name = short_name
        self.prompts_root = os.path.abspath("Prompts") if not is_cartridge else os.path.abspath("Prompts/Cartridges")
        self.base_data_path = os.path.join(self.prompts_root, self.char_id) # Path for character's DSL files
        self.main_template_path_relative = "main_template.txt"

        self.variables: Dict[str, Any] = {} # Initialize first
        self.is_cartridge = is_cartridge


        # Compose initial variables: Base -> Subclass Overrides -> Passed-in Overrides
        composed_initials = Character.BASE_DEFAULTS.copy()
        # Subclass overrides (defined in subclasses like CrazyMita)
        if hasattr(self, "DEFAULT_OVERRIDES"):
            composed_initials.update(self.DEFAULT_OVERRIDES) # type: ignore
        if initial_vars_override:
            composed_initials.update(initial_vars_override)
        
        # Set all composed initial variables
        for key, value in composed_initials.items():
            self.set_variable(key, value) # Use set_variable for normalization

        logger.info(
            "Character '%s' (%s) initialized. Initial effective vars: %s",
            self.char_id, self.name,
            ", ".join(f"{k}={v}" for k, v in self.variables.items() if k in composed_initials)
        )
        
        # Initialize History and Memory Systems
        self.history_manager = HistoryManager(self.char_id) # Use char_id for history folder
        self.memory_system = MemorySystem(self.char_id)    # Use char_id for memory file

        self.load_history() # Load persisted variables and message history
                                                 # This will overwrite defaults if history exists.

        # Initialize DSL interpreter
        path_resolver_instance = LocalPathResolver(
                global_prompts_root=self.prompts_root, 
                character_base_data_path=self.base_data_path
            )
        self.dsl_interpreter = DslInterpreter(self, path_resolver_instance)
        self.post_dsl_interpreter = PostDslInterpreter(self, path_resolver_instance)  # Use same resolver
        # Set initial dynamic variables
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))


        # Region ChessVars
        self.set_variable("playingChess", False)
        self.chess_gui_thread: Optional[threading.Thread] = None # Изменено с Process на Thread
        self.chess_command_queue: Optional[multiprocessing.Queue] = None # Оставляем multiprocessing.Queue, он thread-safe
        self.chess_state_queue: Optional[multiprocessing.Queue] = None   # Оставляем multiprocessing.Queue
        self.current_chess_elo: Optional[int] = None
        self.elo_mapping: Dict[str, int] = {"easy": 1100, "medium": 1500, "hard": 1900}
        # Endregion



    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any):
        if isinstance(value, str):
            val_lower = value.lower()
            if val_lower == "true": value = True
            elif val_lower == "false": value = False

            elif value.isdigit(): 
                 try: value = int(value)
                 except ValueError: pass 
            elif re.fullmatch(r"-?\d+(\.\d+)?", value): 
                 try: value = float(value)
                 except ValueError: pass 
            else: 
                if (value.startswith("'") and value.endswith("'")) or \
                   (value.startswith('"') and value.endswith('"')):
                    value = value[1:-1]
        
        self.variables[name] = value
        # logger.debug(f"Variable '{name}' set to: {value} (type: {type(value)}) for char '{self.char_id}'")


    def get_llm_system_prompt_string(self) -> str:
        """
        Generates the main system prompt string using the DSL engine.
        """
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().strftime("%Y %B %d (%A) %H:%M"))
        
        if hasattr(self.dsl_interpreter, 'char_ctx_filter'):
            self.dsl_interpreter.char_ctx_filter.set_character_id(self.char_id) # type: ignore
            
        try:
            generated_prompt = self.dsl_interpreter.process_main_template_file(self.main_template_path_relative)
            return generated_prompt
        except Exception as e:
            logger.error(f"Critical error during DSL processing for {self.char_id}: {e}", exc_info=True)
            print(f"{RED_COLOR}Critical error in get_llm_system_prompt_string for {self.char_id}: {e}{RESET_COLOR}\n{traceback.format_exc()}", file=sys.stderr)
            return f"[CRITICAL PYTHON ERROR GENERATING SYSTEM PROMPT FOR {self.char_id} - CHECK LOGS]"

    def get_full_system_setup_for_llm(self) -> List[Dict[str, str]]:
        """
        Prepares all system messages for the LLM.
        """
        messages = []
        dsl_generated_content = self.get_llm_system_prompt_string()
        if dsl_generated_content and dsl_generated_content.strip():
            messages.append({"role": "system", "content": dsl_generated_content})
        
        memory_message_content = self.memory_system.get_memories_formatted()
        if memory_message_content and memory_message_content.strip():
            messages.append({"role": "system", "content": memory_message_content})
        return messages

    # In OpenMita/character.py, class Character
    def process_response_nlp_commands(self, response: str) -> str:
        original_response_for_log = response[:200] + "..." if len(response) > 200 else response
        logger.info(f"[{self.char_id}] Original LLM response: {original_response_for_log}")

        # 1. Run custom Post-Processing DSL
        try:
            response = self.post_dsl_interpreter.process(response)
            processed_response_for_log = response[:200] + "..." if len(response) > 200 else response
            logger.info(f"[{self.char_id}] Response after Post-DSL: {processed_response_for_log}")
        except Exception as e:
            logger.error(f"[{self.char_id}] Error during Post-DSL processing: {e}", exc_info=True)
            # Decide: return original response or an error indicator? For now, continue with (potentially partially) processed response.

        # 2. Existing hardcoded logic (memory, <p> tags)
        # These could eventually be migrated to be rules in .postscript files too for full flexibility.
        # For now, they run *after* the custom Post-DSL.
        self.set_variable("LongMemoryRememberCount", self.get_variable("LongMemoryRememberCount", 0) + 1)
        response = self.extract_and_process_memory_data(response)
        try:
            response = self._process_behavior_changes_from_llm(response)
        except Exception as e:
            logger.warning(f"Error processing built-in behavior changes from LLM for {self.char_id}: {e}",
                           exc_info=True)

        final_response_for_log = response[:200] + "..." if len(response) > 200 else response
        logger.debug(f"[{self.char_id}] Final response after all processing: {final_response_for_log}")

        # Region ChessGameTags
        start_match = re.search(r"<StartChessGame>(.*?)</StartChessGame>", response, re.DOTALL)
        if start_match:
            difficulty_str = start_match.group(1).strip().lower()
            elo = self.elo_mapping.get(difficulty_str, self.elo_mapping["medium"])
            # Важно: playingChess установится в True внутри _start_chess_game_process
            self._start_chess_game_process(elo=elo, player_is_white=True)
            response = response.replace(start_match.group(0), "", 1).strip()
            logger.info(f"[{self.char_id}] Chess game start requested with difficulty '{difficulty_str}' (ELO: {elo}).")

        change_diff_match = re.search(r"<ChangeChessDifficulty>(.*?)</ChangeChessDifficulty>", response, re.DOTALL)
        if change_diff_match:
            if self.get_variable("playingChess", False):
                difficulty_str = change_diff_match.group(1).strip().lower()
                new_elo = self.elo_mapping.get(difficulty_str)
                if new_elo:
                    # self.current_chess_elo = new_elo # ELO изменится внутри контроллера после команды
                    self._send_chess_command({"action": "change_elo", "elo": new_elo})
                    logger.info(
                        f"[{self.char_id}] Requested chess difficulty change to '{difficulty_str}' (ELO: {new_elo}).")
                else:
                    logger.warning(f"[{self.char_id}] Invalid difficulty for ChangeChessDifficulty: {difficulty_str}")
            else:
                logger.warning(f"[{self.char_id}] Received ChangeChessDifficulty but no game is active.")
            response = response.replace(change_diff_match.group(0), "", 1).strip()

        if "<RequestBestChessMove!>" in response:
            if self.get_variable("playingChess", False):
                self._send_chess_command({"action": "engine_move"})
                logger.info(f"[{self.char_id}] Requested best chess move from Maia engine.")
            else:
                logger.warning(f"[{self.char_id}] Received RequestBestChessMove but no game is active.")
            response = response.replace("<RequestBestChessMove!>", "", 1).strip()

        llm_move_match = re.search(r"<MakeChessMoveAsLLM>(.*?)</MakeChessMoveAsLLM>", response, re.DOTALL)
        if llm_move_match:
            if self.get_variable("playingChess", False):
                uci_move = llm_move_match.group(1).strip().lower()
                if uci_move:
                    self._send_chess_command({"action": "force_engine_move", "move": uci_move})
                    logger.info(f"[{self.char_id}] LLM specified chess move: {uci_move}.")
                else:
                    logger.warning(f"[{self.char_id}] LLM specified empty chess move.")
            else:
                logger.warning(f"[{self.char_id}] Received MakeChessMoveAsLLM but no game is active.")
            response = response.replace(llm_move_match.group(0), "", 1).strip()

        if "<ResignChessGame!>" in response:
            if self.get_variable("playingChess", False):
                logger.info(f"[{self.char_id}] LLM resigns the chess game. Stopping process...")
                self._stop_chess_game_process(resign=True)  # Это вызовет cleanup и установит playingChess=False
            else:
                logger.warning(f"[{self.char_id}] Received ResignChessGame but no game is active.")
            response = response.replace("<ResignChessGame!>", "", 1).strip()

        if "<StopChessGame!>" in response:
            if self.get_variable("playingChess", False):
                logger.info(f"[{self.char_id}] LLM stops the chess game. Stopping process...")
                self._stop_chess_game_process(resign=False)  # Это вызовет cleanup и установит playingChess=False
            else:
                logger.debug(f"[{self.char_id}] Received StopChessGame but no game was active. Tag removed.")
            response = response.replace("<StopChessGame!>", "", 1).strip()

        # Endregion


        return response

    def _process_behavior_changes_from_llm(self, response: str) -> str:
        """
        Processes <p>attitude,boredom,stress</p> tags from LLM response.
        Updates self.variables.
        """
        start_tag = "<p>"
        end_tag = "</p>"
        
        # Use re.sub to find and remove the tag while processing its content
        def p_tag_processor(match_obj):
            changes_str = match_obj.group(1)
            try:
                changes = [float(x.strip()) for x in changes_str.split(",")]
                if len(changes) == 3:
                    self.adjust_attitude(changes[0])
                    self.adjust_boredom(changes[1])
                    self.adjust_stress(changes[2])
                else:
                    logger.warning(f"Invalid format in <p> tag for {self.char_id}: '{changes_str}'. Expected 3 values.")
            except ValueError:
                logger.warning(f"Invalid numeric values in <p> tag for {self.char_id}: '{changes_str}'")
            return "" # Keep the content, remove the tags

        # Не убираю пока что
        re.sub(f"{re.escape(start_tag)}(.*?){re.escape(end_tag)}", p_tag_processor, response)

        return response.strip()


    def extract_and_process_memory_data(self, response: str) -> str:
        """
        Extracts memory operation tags (<+memory>, <#memory>, <-memory>)
        from the LLM response, processes them, and removes them from the response string.
        """
        memory_pattern = r"<([+#-])memory(?:_([a-zA-Z]+))?>(.*?)</memory>" # Added optional priority in tag itself
        
        def memory_processor(match_obj):
            operation, tag_priority, content = match_obj.groups()
            content = content.strip()
            
            try:
                if operation == "+":
                    parts = [p.strip() for p in content.split('|', 1)]
                    priority = tag_priority or (parts[0] if len(parts) == 2 and parts[0] in ["low", "normal", "high", "critical"] else "normal")
                    mem_content = parts[-1] # Last part is always content

                    if priority not in ["low", "normal", "high", "critical"] and len(parts) == 2: # If priority was actually content
                        mem_content = content # Take full content if first part wasn't a valid priority
                        priority = tag_priority or "normal"

                    self.memory_system.add_memory(priority=priority, content=mem_content)
                    logger.info(f"[{self.char_id}] Added memory (P: {priority}): {mem_content[:50]}...")

                elif operation == "#":
                    parts = [p.strip() for p in content.split('|', 2)]
                    if len(parts) >= 2: # number | new_content OR number | new_priority | new_content
                        mem_num_str = parts[0]
                        new_priority = tag_priority
                        new_content = ""

                        if len(parts) == 2: # number | new_content (priority from tag or keep old)
                            new_content = parts[1]
                        elif len(parts) == 3: # number | new_priority | new_content
                            new_priority = parts[1] # Override tag_priority if explicitly given
                            new_content = parts[2]
                        
                        if mem_num_str.isdigit():
                            self.memory_system.update_memory(number=int(mem_num_str), priority=new_priority, content=new_content)
                            logger.info(f"[{self.char_id}] Updated memory #{mem_num_str} (New P: {new_priority or 'kept'}).")
                        else:
                            logger.warning(f"[{self.char_id}] Invalid number for memory update: {mem_num_str}")
                    else:
                        logger.warning(f"[{self.char_id}] Invalid format for memory update: {content}")
                
                elif operation == "-":
                    content_cleaned = content.strip()
                    if "," in content_cleaned:
                        numbers_str = [num.strip() for num in content_cleaned.split(",")]
                        for num_str in numbers_str:
                            if num_str.isdigit(): self.memory_system.delete_memory(number=int(num_str))
                    elif "-" in content_cleaned:
                        start_end = [s.strip() for s in content_cleaned.split("-")]
                        if len(start_end) == 2 and start_end[0].isdigit() and start_end[1].isdigit():
                            for num_to_del in range(int(start_end[0]), int(start_end[1]) + 1):
                                self.memory_system.delete_memory(number=num_to_del)
                    elif content_cleaned.isdigit():
                        self.memory_system.delete_memory(number=int(content_cleaned))
                    else:
                        logger.warning(f"[{self.char_id}] Invalid format for memory deletion: {content_cleaned}")
            
            except Exception as e:
                logger.error(f"[{self.char_id}] Error processing memory command <{operation}memory>: {content}. Error: {str(e)}", exc_info=True)

            #return "" # Remove the tag from the response
            return match_obj.group(0)

        return re.sub(memory_pattern, memory_processor, response, flags=re.DOTALL).strip()

    # In OpenMita/character.py, class Character
    def reload_character_data(self):
        logger.info(f"[{self.char_id}] Reloading character data from history file.")
        self.load_history()
        self.memory_system.load_memories()
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))

        if hasattr(self, 'post_dsl_interpreter') and self.post_dsl_interpreter:
            self.post_dsl_interpreter._load_rules_and_configs()  # Ensure _load_rules can be called to refresh
            logger.info(f"[{self.char_id}] Post-DSL rules reloaded.")
        else:  # Initialize if it wasn't (e.g. loading an old character state)
            path_resolver_instance = LocalPathResolver(
                global_prompts_root=self.prompts_root,
                character_base_data_path=self.base_data_path
            )
            self.post_dsl_interpreter = PostDslInterpreter(self, path_resolver_instance)
            logger.info(f"[{self.char_id}] Post-DSL interpreter initialized and rules loaded during reload.")

        logger.info(f"[{self.char_id}] Character data reloaded.")

    #region History

    def load_history(self): # RENAMED from load_character_state_from_history
        """Loads variables from history into self.variables.
           This is called after defaults and overrides are set during __init__.
           Persisted variables will overwrite the initial composed ones.
        """
        data = self.history_manager.load_history()
        loaded_vars = data.get("variables", {})
        
        if loaded_vars: 
            for key, value in loaded_vars.items():
                self.set_variable(key, value) 
            logger.info(f"[{self.char_id}] Loaded variables from history, overriding defaults/initials.")
        else:
            logger.info(f"[{self.char_id}] No variables found in history, using composed initial values.")
        return data 
    

    def save_character_state_to_history(self, messages: List[Dict[str, str]]): 
        history_data = {
            'messages': messages,
            'variables': self.variables.copy() 
        }
        self.history_manager.save_history(history_data)
        logger.debug(f"[{self.char_id}] Saved character state and {len(messages)} messages to history.")

    def clear_history(self):
        logger.info(f"[{self.char_id}] Clearing history and resetting state.")
        
        composed_initials = Character.BASE_DEFAULTS.copy()
        if hasattr(self, "DEFAULT_OVERRIDES"):
            subclass_overrides = getattr(self, "DEFAULT_OVERRIDES", {})
            composed_initials.update(subclass_overrides) 
        
        self.variables.clear() # Clear current vars
        for key, value in composed_initials.items(): # Set back to composed initials
            self.set_variable(key, value)

        self.memory_system.clear_memories()
        self.history_manager.clear_history() # This saves an empty history file
        logger.info(f"[{self.char_id}] History cleared and state reset to initial defaults/overrides.")

    def add_message_to_history(self, message: Dict[str, str]): 
        current_history_data = self.history_manager.load_history()
        messages = current_history_data.get("messages", [])
        messages.append(message)
        self.save_character_state_to_history(messages)
    #endregion

    # In OpenMita/character.py, class Character
    def current_variables_string(self) -> str:
        """Returns a string representation of key variables for UI/debug display,
           customizable via Post-DSL DEBUG_DISPLAY section."""
        display_str = f"Character: {self.name} ({self.char_id})\n"

        vars_to_display = {}
        # Используем конфигурацию из PostDslInterpreter, если она есть
        if hasattr(self, 'post_dsl_interpreter') and self.post_dsl_interpreter.debug_display_config:
            for label, var_name in self.post_dsl_interpreter.debug_display_config.items():
                vars_to_display[label] = self.get_variable(var_name, "N/A")
        else:
            # Фоллбэк на старую логику, если конфигурации нет
            vars_to_display = {
                "Attitude": self.get_variable("attitude", "N/A"),
                "Boredom": self.get_variable("boredom", "N/A"),
                "Stress": self.get_variable("stress", "N/A"),
            }
            if self.char_id == "Crazy":  # Пример специфичной для персонажа логики (лучше тоже в DEBUG_DISPLAY)
                vars_to_display["Secret Exposed"] = self.get_variable("secretExposed", "N/A")
                vars_to_display["FSM State"] = self.get_variable("current_fsm_state", "N/A")

        for key, val in vars_to_display.items():
            display_str += f"- {key}: {val}\n"

        return display_str.strip()
        
    def adjust_attitude(self, amount: float):
        current = self.get_variable("attitude", 60.0)
        amount = round(amount,2)
        amount = clamp(float(amount), -6.0, 6.0) # Max adjustment per original prompt
        self.set_variable("attitude", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Attitude changed by {amount:.2f} to {self.get_variable('attitude'):.2f}")

    def adjust_boredom(self, amount: float):
        current = self.get_variable("boredom", 10.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)
        self.set_variable("boredom", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Boredom changed by {amount:.2f} to {self.get_variable('boredom'):.2f}")

    def adjust_stress(self, amount: float):
        current = self.get_variable("stress", 5.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)
        self.set_variable("stress", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Stress changed by {amount:.2f} to {self.get_variable('stress'):.2f}")

    def __str__(self):
        return f"Character(id='{self.char_id}', name='{self.name}')"



    # Region ChessGameFunctions
    def _start_chess_game_process(self, elo: int,
                                  player_is_white: bool = True):  # Название метода можно оставить для совместимости
        if self.chess_gui_thread and self.chess_gui_thread.is_alive():
            logger.warning(f"[{self.char_id}] Chess game thread already running. Stopping it first.")
            self._stop_chess_game_process()

        try:
            from Modules.Chess.chess_board import run_chess_gui_process

            self.current_chess_elo = elo
            self.set_variable("playingChess", True)  # Устанавливаем флаг игры

            # Инициализируем очереди здесь, если они еще не созданы или для новой игры
            # Важно, чтобы controller внутри GUI потока получал эти очереди
            if self.chess_command_queue is None:
                self.chess_command_queue = multiprocessing.Queue()
            if self.chess_state_queue is None:
                self.chess_state_queue = multiprocessing.Queue()

            logger.info(
                f"[{self.char_id}] Starting chess GUI in a new thread. ELO: {elo}, Player White: {player_is_white}")

            self.chess_gui_thread = threading.Thread(
                target=run_chess_gui_process,
                args=(self.chess_command_queue, self.chess_state_queue, elo, player_is_white),
                daemon=True  # Поток-демон завершится, когда завершится основной поток
            )
            self.chess_gui_thread.start()

            logger.info(f"[{self.char_id}] Chess GUI thread started.")

            # Убираем отладочный прямой вызов, который передавал None в качестве очередей
            # logger.info(f"[{self.char_id}] DEBUG: Calling run_chess_gui_process directly for debugging.")
            # dummy_command_q = None
            # dummy_state_q = None
            # try:
            #     run_chess_gui_process(dummy_command_q, dummy_state_q, elo, player_is_white)
            #     logger.info(f"[{self.char_id}] DEBUG: run_chess_gui_process finished (if it's blocking).")
            # except Exception as e_direct_run:
            #     logger.error(f"[{self.char_id}] DEBUG: Error calling run_chess_gui_process directly: {e_direct_run}", exc_info=True)

        except ImportError as e_imp:
            logger.error(
                f"[{self.char_id}] Failed to import chess_board module from 'Modules.Chess.chess_board'. Chess game cannot start. Error details: {e_imp}",
                exc_info=True
            )
            self._cleanup_chess_resources()
        except AttributeError as e_attr:  # Например, если run_chess_gui_process не найдена
            logger.error(
                f"[{self.char_id}] Attribute error related to chess_board module (e.g., 'run_chess_gui_process' not found). Error: {e_attr}. Chess game cannot start.",
                exc_info=True)
            self._cleanup_chess_resources()
        except Exception as e:
            logger.error(f"[{self.char_id}] Error starting chess game thread: {e}", exc_info=True)
            self._cleanup_chess_resources()

    def _send_chess_command(self, command_data: Dict[str, Any]):
        if self.get_variable("playingChess",
                             False) and self.chess_command_queue and self.chess_gui_thread and self.chess_gui_thread.is_alive():
            try:
                self.chess_command_queue.put(command_data)
                logger.debug(f"[{self.char_id}] Sent command to chess thread: {command_data}")
            except Exception as e:
                logger.error(f"[{self.char_id}] Error sending command to chess command_queue: {e}")
        elif not self.get_variable("playingChess", False):
            logger.warning(f"[{self.char_id}] Cannot send chess command: game not active.")
        else:
            logger.warning(f"[{self.char_id}] Cannot send chess command: command_queue or thread not available/alive.")

    def _stop_chess_game_process(self, resign: bool = False):  # Название метода можно оставить
        if self.get_variable("playingChess", False):
            logger.info(f"[{self.char_id}] Stopping chess game (resign={resign}). Sending command to GUI thread.")
            # Отправляем команду на закрытие GUI процесса/потока через очередь
            # run_chess_gui_process должен обработать "stop_gui_process" или "resign"/"stop"
            # и корректно завершить свой цикл и ресурсы Tkinter.
            if resign:
                self._send_chess_command({"action": "resign"})  # Это приведет к закрытию GUI в run_chess_gui_process
            else:
                # Если просто останавливаем, то GUI должен получить команду "stop_gui_process"
                # или "stop", чтобы знать, что нужно закрыться.
                # "stop_gui_process" - более явная команда для самого GUI потока
                self._send_chess_command({"action": "stop_gui_process"})

            if self.chess_gui_thread and self.chess_gui_thread.is_alive():
                logger.info(f"[{self.char_id}] Waiting for chess GUI thread to join...")
                self.chess_gui_thread.join(timeout=10)  # Даем потоку время на завершение
                if self.chess_gui_thread.is_alive():
                    logger.warning(f"[{self.char_id}] Chess GUI thread did not terminate gracefully after 10s.")
                    # Для потоков нет метода terminate(). Поток должен сам завершиться.
                    # Если он не завершился, это может указывать на проблему в run_chess_gui_process.
        self._cleanup_chess_resources()  # Это установит playingChess в False и обнулит ресурсы

    def _cleanup_chess_resources(self):
        logger.debug(f"[{self.char_id}] Cleaning up chess resources.")
        self.set_variable("playingChess", False)

        # Закрывать очереди multiprocessing.Queue нужно осторожно,
        # особенно если поток-читатель еще может быть жив.
        # Но если поток уже завершен (или мы считаем его таковым), то можно.
        # if self.chess_command_queue:
        #     try:
        #         self.chess_command_queue.close() # Предотвращает добавление новых элементов
        #         # self.chess_command_queue.join_thread() # Ожидает, пока все элементы из буфера не будут обработаны
        #     except Exception as e:
        #         logger.warning(f"[{self.char_id}] Error closing command_queue: {e}")
        # if self.chess_state_queue:
        #     try:
        #         self.chess_state_queue.close()
        #         # self.chess_state_queue.join_thread()
        #     except Exception as e:
        #         logger.warning(f"[{self.char_id}] Error closing state_queue: {e}")

        # Просто обнуляем ссылки. Потоки-демоны и сборщик мусора должны справиться.
        # Или, если очереди создаются заново каждый раз, это тоже решает проблему.
        self.chess_gui_thread = None
        self.chess_command_queue = None  # Можно пересоздавать их в _start_chess_game_process
        self.chess_state_queue = None
        self.current_chess_elo = None

    # Endregion