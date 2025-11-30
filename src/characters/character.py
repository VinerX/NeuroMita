# File: NeuroMita/character.py
import datetime
import re
import os
import sys # For traceback
import traceback # For traceback
from typing import Dict, List, Any, Optional
import json

# Assuming dsl_engine.py is in a DSL folder within NeuroMita
from DSL.dsl_engine import DslInterpreter # PROMPTS_ROOT is managed by DslInterpreter
from DSL.path_resolver import LocalPathResolver
from DSL.post_dsl_engine import PostDslInterpreter
from managers.memory_manager import MemoryManager
from managers.history_manager import HistoryManager
from utils import clamp, SH # SH for masking keys if needed elsewhere
from core.events import get_event_bus, Events
import os

from managers.game_manager import GameManager

# Setup logger for this module
from main_logger import logger

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
         silero_command: str, 
         short_name: str,
         miku_tts_name: str = "Player", 
         silero_turn_off_video: bool = False,
         initial_vars_override: Dict[str, Any] | None = None,
         is_cartridge = False
         ):
        self.event_bus = get_event_bus()
    
        self.char_id = char_id
        self.name = name

        self.silero_command = silero_command
        self.silero_turn_off_video = silero_turn_off_video
        self.miku_tts_name = miku_tts_name
        self.short_name = short_name
        self.prompts_root = os.path.abspath("Prompts") if not is_cartridge else os.path.abspath("Prompts/Cartridges")
        self.base_data_path = os.path.join(self.prompts_root, self.char_id)
        self.main_template_path_relative = "main_template.txt"

        self.variables: Dict[str, Any] = {}
        self.is_cartridge = is_cartridge
        self.system_messages = []

        self._cached_system_setup: List[Dict] = []
        self.app_vars: Dict[str, Any] = {}

        composed_initials = Character.BASE_DEFAULTS.copy()
        if hasattr(self, "DEFAULT_OVERRIDES"):
            composed_initials.update(self.DEFAULT_OVERRIDES)
        if initial_vars_override:
            composed_initials.update(initial_vars_override)
        
        for key, value in composed_initials.items():
            self.set_variable(key, value)

        self.load_config()

        logger.info(
            "\n\nCharacter '%s' (%s) initialized. Initial effective vars: %s\n\n",
            self.char_id, self.name,
            ", ".join(f"\n • {k} = {v}" for k, v in self.variables.items() if k in composed_initials)
        )
        
        self.history_manager = HistoryManager(self.char_id)
        self.memory_system = MemoryManager(self.char_id)

        self.load_history()

        from managers.dsl_manager import create_dsl_interpreter
        self.dsl_interpreter = create_dsl_interpreter(self)

        self.post_dsl_interpreter = PostDslInterpreter(self, LocalPathResolver(
                global_prompts_root=self.prompts_root, 
                character_base_data_path=self.base_data_path
            ))
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))

        self.set_variable("playingGame", False)
        self.set_variable("game_id", None)
        self.game_manager = GameManager(self)

    def load_config(self):
        """
        Загружает кастомные настройки из config.json в папке персонажа.
        Если файла нет - создаёт его с базовыми значениями из DEFAULT_OVERRIDES.
        Добавляет и поддерживает 6 новых статичных переменных с ограничениями:
        - attitude_min / attitude_max
        - boredom_min / boredom_max
        - stress_min / stress_max
        null (None) допускается — означает отсутствие ограничения.
        Логируем ошибку, если max < min.
        """
        config_path = os.path.join(self.base_data_path, "config.json")

        bounds_defaults = {
            "attitude_min": 0.0, "attitude_max": 100.0,
            "boredom_min": 0.0,  "boredom_max": 100.0,
            "stress_min": 0.0,   "stress_max": 100.0,
        }

        def _validate_pairs(cfg: Dict[str, Any]):
            def _check_pair(min_key: str, max_key: str, label: str):
                vmin = cfg.get(min_key)
                vmax = cfg.get(max_key)
                if isinstance(vmin, (int, float)) and isinstance(vmax, (int, float)) and vmax < vmin:
                    logger.error(f"[{self.char_id}] Config error: {label} max ({vmax}) < min ({vmin}).")
            _check_pair("attitude_min", "attitude_max", "attitude")
            _check_pair("boredom_min",  "boredom_max",  "boredom")
            _check_pair("stress_min",   "stress_max",   "stress")

        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                # Гарантируем наличие новых ключей с дефолтами
                changed = False
                for k, v in bounds_defaults.items():
                    if k not in config_data:
                        config_data[k] = v
                        changed = True

                _validate_pairs(config_data)

                logger.info(f"[{self.char_id}] Loading custom config from {config_path}")
                for key, value in config_data.items():
                    self.set_variable(key, value)
                    logger.debug(f"[{self.char_id}] Set custom variable {key} = {value}")

                # Если добавили новые ключи — перезапишем файл
                if changed:
                    try:
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f, indent=4, ensure_ascii=False)
                        logger.info(f"[{self.char_id}] Missing config keys added and saved to {config_path}")
                    except Exception as e:
                        logger.error(f"[{self.char_id}] Failed to update config.json with missing keys: {e}")

            else:
                logger.info(f"[{self.char_id}] config.json not found at {config_path}, creating with default values")

                base_config = self.BASE_DEFAULTS.copy()
                if hasattr(self, "DEFAULT_OVERRIDES"):
                    base_config.update(self.DEFAULT_OVERRIDES)

                # Новые статичные ключи ограничений
                for k, v in bounds_defaults.items():
                    base_config.setdefault(k, v)

                os.makedirs(os.path.dirname(config_path), exist_ok=True)

                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(base_config, f, indent=4, ensure_ascii=False)

                # Применяем значения и в рантайме
                for key, value in base_config.items():
                    self.set_variable(key, value)

                logger.info(f"[{self.char_id}] Default config saved to {config_path}")

        except json.JSONDecodeError as e:
            logger.error(f"[{self.char_id}] Error parsing config.json: {e}, creating new config")

            base_config = self.BASE_DEFAULTS.copy()
            if hasattr(self, "DEFAULT_OVERRIDES"):
                base_config.update(self.DEFAULT_OVERRIDES)

            for k, v in bounds_defaults.items():
                base_config.setdefault(k, v)

            os.makedirs(os.path.dirname(config_path), exist_ok=True)

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(base_config, f, indent=4, ensure_ascii=False)

            for key, value in base_config.items():
                self.set_variable(key, value)

            logger.info(f"[{self.char_id}] New config created with defaults after JSON error")

        except Exception as e:
            logger.error(f"[{self.char_id}] Error loading/creating config.json: {e}")

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


    def _get_llm_system_prompts_for_template(self, template_relative: str) -> list[str]:
        """
        Базовая реализация получения системных промптов по указанному main_template.
        Используется как для обычного main_template.txt, так и для react_template.txt.
        """
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().strftime("%Y %B %d (%A) %H:%M"))
        try:
            results = self.event_bus.emit_and_wait(Events.Settings.GET_APP_VARS, timeout=1.0)
            app_vars: Dict[str, Any] = {}
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
            self.update_app_vars(app_vars)
        except Exception as e:
            logger.warning(f"[{self.char_id}] Не удалось получить app_vars через события: {e}")
            self.update_app_vars({})

        try:
            blocks, system_infos = self.dsl_interpreter.process_main_template(template_relative)
            if system_infos:
                self.system_messages.extend(system_infos)
            return blocks or []
        except Exception as e:
            logger.error(f"Critical error during DSL processing for {self.char_id}: {e}", exc_info=True)
            print(f"{RED_COLOR}Critical error in get_llm_system_prompts for {self.char_id}: {e}{RESET_COLOR}\n{traceback.format_exc()}", file=sys.stderr)
            return []

    def get_llm_system_prompts(self) -> list[str]:
        """
        Стандартный путь — использовать main_template.txt
        """
        return self._get_llm_system_prompts_for_template(self.main_template_path_relative)

    def get_llm_system_prompts_for_template(self, template_relative: str) -> list[str]:
        """
        Публичный метод для получения промптов по произвольному template_relative
        (наприме��, 'react_template.txt').
        """
        return self._get_llm_system_prompts_for_template(template_relative)

    def get_full_system_setup_for_llm(self, separate_prompts = False):
        """
        Собирает системные сообщения для LLM на основе массива строк из DSL.
        Если separate_prompts=True — по одному сообщению на блок; иначе — один общий промпт.
        """
        from utils.prompt_builder import build_system_prompts

        messages = []
        dsl_blocks = self.get_llm_system_prompts()

        messages.extend(build_system_prompts(dsl_blocks, separate=separate_prompts))

        memory_message_content = self.memory_system.get_memories_formatted()
        if memory_message_content and memory_message_content.strip():
            messages.append({"role": "system", "content": memory_message_content})

        self._cached_system_setup = [m.copy() for m in messages]
        return messages
    
    def get_full_system_setup_for_llm_template(self, template_relative: str, separate_prompts=False):
        """
        Собирает системные сообщения для LLM на основе указанного шаблона (template_relative).
        Например, 'react_template.txt'.
        """
        from utils.prompt_builder import build_system_prompts

        messages = []
        dsl_blocks = self.get_llm_system_prompts_for_template(template_relative)

        messages.extend(build_system_prompts(dsl_blocks, separate=separate_prompts))

        memory_message_content = self.memory_system.get_memories_formatted()
        if memory_message_content and memory_message_content.strip():
            messages.append({"role": "system", "content": memory_message_content})

        self._cached_system_setup = [m.copy() for m in messages]
        return messages
    
    def get_cached_system_setup(self) -> List[Dict]:
        return [m.copy() for m in self._cached_system_setup]  # пустой список, если ещё не считали

    def get_system_infos(self,clear=True):
        messages = self.system_messages.copy()
        if clear:
            self.system_messages.clear()
        return messages

    def process_response_nlp_commands(self, response: str,save_as_missed = False) -> str:
        original_response_for_log = response[:200] + "..." if len(response) > 200 else response
        logger.info(f"[{self.char_id}] Original LLM response: {original_response_for_log}")

        try:
            response = self.post_dsl_interpreter.process(response)
            processed_response_for_log = response[:200] + "..." if len(response) > 200 else response
            logger.info(f"[{self.char_id}] Response after Post-DSL: {processed_response_for_log}")
        except Exception as e:
            logger.error(f"[{self.char_id}] Error during Post-DSL processing: {e}", exc_info=True)

        self.set_variable("LongMemoryRememberCount", self.get_variable("LongMemoryRememberCount", 0) + 1)
        try:
            results = self.event_bus.emit_and_wait(Events.Settings.GET_APP_VARS, timeout=1.0)
            app_vars: Dict[str, Any] = {}
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
            self.update_app_vars(app_vars)
        except Exception as e:
            logger.warning(f"[{self.char_id}] Не удалось получить app_vars через события: {e}")
            self.update_app_vars({})
        response = self.extract_and_process_memory_data(response,save_as_missed)
        try:
            response = self._process_behavior_changes_from_llm(response)
        except Exception as e:
            logger.warning(f"Error processing built-in behavior changes from LLM for {self.char_id}: {e}",
                           exc_info=True)

        try:
            response = self._process_game_tags(response)
        except Exception as e:
            logger.error(f"[{self.char_id}] Error during game tag processing: {e}", exc_info=True)

        final_response_for_log = response[:200] + "..." if len(response) > 200 else response
        logger.debug(f"[{self.char_id}] Final response after all processing: {final_response_for_log}")

        return response

    def _process_game_tags(self, response: str) -> str:
        """
        Обрабатывает общие игровые теги, такие как <StartGame> и <EndGame>,
        и делегирует их обработку игровому менеджеру.
        """
        start_match = re.search(r'<StartGame id="([^"]*)"/>', response, re.DOTALL | re.IGNORECASE)
        if start_match:
            full_id_str = start_match.group(1).strip()
            self.game_manager.start_game(full_id_str)
            response = response.replace(start_match.group(0), "", 1).strip()
            logger.info(f"[{self.char_id}] Запрошен запуск игры с ID: '{full_id_str}'.")

        end_match = re.search(r'<EndGame id="([^"]*)"/>', response, re.DOTALL | re.IGNORECASE)
        if end_match:
            full_id_str = end_match.group(1).strip()
            self.game_manager.stop_game(full_id_str)
            response = response.replace(end_match.group(0), "", 1).strip()
            logger.info(f"[{self.char_id}] Запрошена остановка игры с ID: '{full_id_str}'.")

        if self.get_variable("playingGame", False):
            response = self.game_manager.process_active_game_tags(response)

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


    def extract_and_process_memory_data(self, response: str,save_as_missed = False) -> str:
        """
        Extracts memory operation tags (<+memory>, <#memory>, <-memory>)
        from the LLM response, processes them, and removes them from the response string.
        """
        memory_pattern = r"<([+#-])memory(?:_([a-zA-Z]+))?>(.*?)</\1?memory>"
        
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
                            if num_str.isdigit(): self.memory_system.delete_memory(int(num_str),save_as_missed)
                    elif "-" in content_cleaned:
                        start_end = [s.strip() for s in content_cleaned.split("-")]
                        if len(start_end) == 2 and start_end[0].isdigit() and start_end[1].isdigit():
                            for num_to_del in range(int(start_end[0]), int(start_end[1]) + 1):
                                self.memory_system.delete_memory(num_to_del,save_as_missed)
                    elif content_cleaned.isdigit():
                        self.memory_system.delete_memory(int(content_cleaned),save_as_missed)
                    else:
                        logger.warning(f"[{self.char_id}] Invalid format for memory deletion: {content_cleaned}")
            
            except Exception as e:
                logger.error(f"[{self.char_id}] Error processing memory command <{operation}memory>: {content}. Error: {str(e)}", exc_info=True)

            #return "" # Remove the tag from the response
            return match_obj.group(0)

        return re.sub(memory_pattern, memory_processor, response, flags=re.DOTALL).strip()

    # In OpenMita/character.py, class Character
    def reload_character_data(self):
        logger.info(f"[{self.char_id}] Reloading character data from disk (config + history).")

        # Сначала перезагружаем config, затем историю (история может переопределить значения)
        self.load_config()
        self.load_history()
        self.memory_system.load_memories()
        self.set_variable("SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes"))

        if hasattr(self, 'post_dsl_interpreter') and self.post_dsl_interpreter:
            self.post_dsl_interpreter._load_rules_and_configs()
            logger.info(f"[{self.char_id}] Post-DSL rules reloaded.")
        else:
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
        
        self.variables.clear()
        for key, value in composed_initials.items():
            self.set_variable(key, value)

        # Перезагружаем конфиг после сброса — чтобы применить новые/актуальные значения
        self.load_config()

        self.memory_system.clear_memories()
        self._cached_system_setup = []
        self.history_manager.clear_history()
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


    def update_app_vars(self, app_vars: Dict[str, Any]):
        """Обновляет переменные программы для исползования в логике DSL """
        self.app_vars = app_vars.copy()  # Копируем, чтобы избежать мутаций
        logger.debug(f"[{self.char_id}] App vars updated: {list(self.app_vars.keys())}")

    def adjust_attitude(self, amount: float):
        current = self.get_variable("attitude", 60.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)  # ограничение шага изменения

        # Динамические границы (None = без ограничения)
        min_bound = self.get_variable("attitude_min", 0.0)
        max_bound = self.get_variable("attitude_max", 100.0)

        def to_num_or_none(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            try:
                return float(v)
            except Exception:
                return None

        min_val = to_num_or_none(min_bound)
        max_val = to_num_or_none(max_bound)

        if (min_val is not None and max_val is not None) and max_val < min_val:
            logger.error(f"[{self.char_id}] Invalid config: attitude_max ({max_val}) is less than attitude_min ({min_val}).")
            min_val, max_val = None, None  # отключаем ограничение при некорректной паре

        new_value = current + amount
        if min_val is None and max_val is None:
            pass
        elif min_val is None:
            if new_value > max_val:
                new_value = max_val
        elif max_val is None:
            if new_value < min_val:
                new_value = min_val
        else:
            new_value = clamp(new_value, min_val, max_val)

        self.set_variable("attitude", new_value)
        logger.info(f"[{self.char_id}] Attitude changed by {amount:.2f} to {self.get_variable('attitude'):.2f}")


    def adjust_boredom(self, amount: float):
        current = self.get_variable("boredom", 10.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)

        min_bound = self.get_variable("boredom_min", 0.0)
        max_bound = self.get_variable("boredom_max", 100.0)

        def to_num_or_none(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            try:
                return float(v)
            except Exception:
                return None

        min_val = to_num_or_none(min_bound)
        max_val = to_num_or_none(max_bound)

        if (min_val is not None and max_val is not None) and max_val < min_val:
            logger.error(f"[{self.char_id}] Invalid config: boredom_max ({max_val}) is less than boredom_min ({min_val}).")
            min_val, max_val = None, None

        new_value = current + amount
        if min_val is None and max_val is None:
            pass
        elif min_val is None:
            if new_value > max_val:
                new_value = max_val
        elif max_val is None:
            if new_value < min_val:
                new_value = min_val
        else:
            new_value = clamp(new_value, min_val, max_val)

        self.set_variable("boredom", new_value)
        logger.info(f"[{self.char_id}] Boredom changed by {amount:.2f} to {self.get_variable('boredom'):.2f}")


    def adjust_stress(self, amount: float):
        current = self.get_variable("stress", 5.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)

        min_bound = self.get_variable("stress_min", 0.0)
        max_bound = self.get_variable("stress_max", 100.0)

        def to_num_or_none(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            try:
                return float(v)
            except Exception:
                return None

        min_val = to_num_or_none(min_bound)
        max_val = to_num_or_none(max_bound)

        if (min_val is not None and max_val is not None) and max_val < min_val:
            logger.error(f"[{self.char_id}] Invalid config: stress_max ({max_val}) is less than stress_min ({min_val}).")
            min_val, max_val = None, None

        new_value = current + amount
        if min_val is None and max_val is None:
            pass
        elif min_val is None:
            if new_value > max_val:
                new_value = max_val
        elif max_val is None:
            if new_value < min_val:
                new_value = min_val
        else:
            new_value = clamp(new_value, min_val, max_val)

        self.set_variable("stress", new_value)
        logger.info(f"[{self.char_id}] Stress changed by {amount:.2f} to {self.get_variable('stress'):.2f}")
        
    def __str__(self):
        return f"Character(id='{self.char_id}', name='{self.name}')"
