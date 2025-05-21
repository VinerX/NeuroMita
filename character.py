# File: NeuroMita/character.py
import datetime
import re
import os
import logging # Use standard logging
import sys # For traceback
import traceback # For traceback
from typing import Dict, List, Any

# Assuming dsl_engine.py is in a DSL folder within NeuroMita
from DSL.dsl_engine import DslInterpreter # PROMPTS_ROOT is managed by DslInterpreter
from DSL.path_resolver import LocalPathResolver
from MemorySystem import MemorySystem
from HistoryManager import HistoryManager
from utils import clamp, SH # SH for masking keys if needed elsewhere

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
                 initial_vars_override: Dict[str, Any] | None = None): # For explicit initial values passed in
        
        self.char_id = char_id # For DSL logging and Prompts path
        self.name = name # Display name

        # NeuroMita specific attributes
        self.silero_command = silero_command
        self.silero_turn_off_video = silero_turn_off_video
        self.miku_tts_name = miku_tts_name
        self.short_name = short_name
        self.prompts_root = os.path.abspath("Prompts")
        self.base_data_path = os.path.join(self.prompts_root, self.char_id) # Path for character's DSL files
        self.main_template_path_relative = "main_template.txt"

        self.variables: Dict[str, Any] = {} # Initialize first
        
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

        # Set initial dynamic variables
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))


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

    def process_response_nlp_commands(self, response: str) -> str:
        """
        Processes commands embedded in the LLM's response (<p>, memory tags).
        Subclasses can override to add more specific parsing.
        """
        self.set_variable("LongMemoryRememberCount", self.get_variable("LongMemoryRememberCount", 0) + 1)

        response = self.extract_and_process_memory_data(response)
        try:
            response = self._process_behavior_changes_from_llm(response) # Handles <p> tags
        except Exception as e:
            logger.warning(f"Error processing behavior changes from LLM for {self.char_id}: {e}", exc_info=True)
        
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
            return "" # Remove the tag

        response = re.sub(f"{re.escape(start_tag)}(.*?){re.escape(end_tag)}", p_tag_processor, response)
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
            return "" # Remove the tag from the response

        return re.sub(memory_pattern, memory_processor, response, flags=re.DOTALL).strip()

    def reload_character_data(self):
        logger.info(f"[{self.char_id}] Reloading character data from history file.")
        self.load_history() 
        self.memory_system.load_memories() 
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))
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

    def current_variables_string(self) -> str:
        """Returns a string representation of key variables for UI/debug display."""
        vars_to_display = {
            "Attitude": self.get_variable("attitude", "N/A"),
            "Boredom": self.get_variable("boredom", "N/A"),
            "Stress": self.get_variable("stress", "N/A"),
        }

        if self.char_id == "Crazy":
            vars_to_display["Secret Exposed"] = self.get_variable("secretExposed", "N/A")
            vars_to_display["FSM State"] = self.get_variable("current_fsm_state", "N/A")

        display_str = f"Character: {self.name} ({self.char_id})\n"
        for key, val in vars_to_display.items():
            display_str += f"- {key}: {val}\n"
        return display_str.strip()
        
    def adjust_attitude(self, amount: float):
        current = self.get_variable("attitude", 60.0)
        amount = clamp(float(amount), -6.0, 6.0) # Max adjustment per original prompt
        self.set_variable("attitude", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Attitude changed by {amount:.2f} to {self.get_variable('attitude'):.2f}")

    def adjust_boredom(self, amount: float):
        current = self.get_variable("boredom", 10.0)
        amount = clamp(float(amount), -6.0, 6.0)
        self.set_variable("boredom", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Boredom changed by {amount:.2f} to {self.get_variable('boredom'):.2f}")

    def adjust_stress(self, amount: float):
        current = self.get_variable("stress", 5.0)
        amount = clamp(float(amount), -6.0, 6.0)
        self.set_variable("stress", clamp(current + amount, 0.0, 100.0))
        logger.info(f"[{self.char_id}] Stress changed by {amount:.2f} to {self.get_variable('stress'):.2f}")

    def __str__(self):
        return f"Character(id='{self.char_id}', name='{self.name}')"