import datetime
import re
import os
from typing import Dict, List, Any, Optional
import json

from DSL.path_resolver import LocalPathResolver
from DSL.post_dsl_engine import PostDslInterpreter
from managers.memory_manager import MemoryManager
from managers.history_manager import HistoryManager
from utils import clamp
from core.events import get_event_bus, Events
import os

from managers.game_manager import GameManager
from schemas.structured_response import StructuredResponse

from main_logger import logger

RED_COLOR = "\033[91m"
RESET_COLOR = "\033[0m"


class Character:
    BASE_DEFAULTS: Dict[str, Any] = {
        "attitude": 60.0,
        "boredom": 10.0,
        "stress": 5.0,
        "secretExposed": False,
        "current_fsm_state": "Hello",
        "available_action_level": 1,
        "PlayingFirst": False,
        "secretExposedFirst": False,
        "secret_exposed_event_text_shown": False,
        "LongMemoryRememberCount": 0,
        "player_name": "Игрок",
        "player_name_known": False,
    }

    def __init__(
        self,
        char_id: str,
        name: str,
        silero_command: str,
        short_name: str,
        miku_tts_name: str = "Player",
        silero_turn_off_video: bool = False,
        initial_vars_override: Dict[str, Any] | None = None,
        is_cartridge=False,
        ):
        self.event_bus = get_event_bus()

        self.char_id = char_id
        self.name = name

        self.silero_command = silero_command
        self.silero_turn_off_video = silero_turn_off_video
        self.miku_tts_name = miku_tts_name
        self.short_name = short_name

        self.prompts_root = (
            os.path.abspath("Prompts")
            if not is_cartridge
            else os.path.abspath("Prompts/Cartridges")
        )

        self.main_template_path_relative = "main_template.txt"

        self.variables: Dict[str, Any] = {}
        self._dirty_vars: set = set()
        self.is_cartridge = is_cartridge
        self.app_vars: Dict[str, Any] = {}

        self.prompt_set_name: str | None = None
        self.base_data_path = self._character_prompts_root()

        try:
            resolved = self._resolve_prompt_set_name()
            self._apply_prompt_set(resolved)
        except Exception as e:
            msg = f"[{self.char_id}] Failed to resolve/apply prompt set: {e}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)
            self._apply_prompt_set("Default")

        self._log_prompt_set_problems_if_any()

        composed_initials = Character.BASE_DEFAULTS.copy()
        if hasattr(self, "DEFAULT_OVERRIDES"):
            composed_initials.update(self.DEFAULT_OVERRIDES)
        if initial_vars_override:
            composed_initials.update(initial_vars_override)

        for key, value in composed_initials.items():
            self.set_variable(key, value)

        self.load_config()

        logger.info(
            "\n\nCharacter '%s' (%s) initialized. Prompt set: %s. Base path: %s. Initial effective vars: %s\n\n",
            self.char_id,
            self.name,
            self.prompt_set_name,
            self.base_data_path,
            ", ".join(
                f"\n • {k} = {v}"
                for k, v in self.variables.items()
                if k in composed_initials
            ),
        )

        self._pending_targets: list[str] = []

        self.history_manager = HistoryManager(character_name=self.name, character_id=self.char_id)
        self.memory_system = MemoryManager(self.char_id)
        self.memory_system.prompt_set_path = self.base_data_path

        from managers.reminder_manager import ReminderManager
        self.reminder_system = ReminderManager(self.char_id)

        self.load_history()

        from managers.dsl_manager import create_dsl_interpreter
        self.dsl_interpreter = create_dsl_interpreter(self)

        self.post_dsl_interpreter = PostDslInterpreter(
            self,
            LocalPathResolver(
                global_prompts_root=self.prompts_root,
                character_base_data_path=self.base_data_path,
            ),
        )

        self.set_variable(
            "SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes")
        )

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
            "attitude_min": 0.0,
            "attitude_max": 100.0,
            "boredom_min": 0.0,
            "boredom_max": 100.0,
            "stress_min": 0.0,
            "stress_max": 100.0,
        }

        def _validate_pairs(cfg: Dict[str, Any]):
            def _check_pair(min_key: str, max_key: str, label: str):
                vmin = cfg.get(min_key)
                vmax = cfg.get(max_key)
                if (
                    isinstance(vmin, (int, float))
                    and isinstance(vmax, (int, float))
                    and vmax < vmin
                ):
                    logger.error(
                        f"[{self.char_id}] Config error: {label} max ({vmax}) < min ({vmin})."
                    )

            _check_pair("attitude_min", "attitude_max", "attitude")
            _check_pair("boredom_min", "boredom_max", "boredom")
            _check_pair("stress_min", "stress_max", "stress")

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

                changed = False
                for k, v in bounds_defaults.items():
                    if k not in config_data:
                        config_data[k] = v
                        changed = True

                _validate_pairs(config_data)

                logger.info(
                    f"[{self.char_id}] Loading custom config from {config_path}"
                )
                for key, value in config_data.items():
                    self.set_variable(key, value)
                    logger.debug(
                        f"[{self.char_id}] Set custom variable {key} = {value}"
                    )

                if changed:
                    try:
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config_data, f, indent=4, ensure_ascii=False)
                        logger.info(
                            f"[{self.char_id}] Missing config keys added and saved to {config_path}"
                        )
                    except Exception as e:
                        logger.error(
                            f"[{self.char_id}] Failed to update config.json with missing keys: {e}"
                        )

            else:
                logger.info(
                    f"[{self.char_id}] config.json not found at {config_path}, creating with default values"
                )

                base_config = self.BASE_DEFAULTS.copy()
                if hasattr(self, "DEFAULT_OVERRIDES"):
                    base_config.update(self.DEFAULT_OVERRIDES)

                for k, v in bounds_defaults.items():
                    base_config.setdefault(k, v)

                os.makedirs(os.path.dirname(config_path), exist_ok=True)

                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(base_config, f, indent=4, ensure_ascii=False)

                for key, value in base_config.items():
                    self.set_variable(key, value)

                logger.info(f"[{self.char_id}] Default config saved to {config_path}")

        except json.JSONDecodeError as e:
            logger.error(
                f"[{self.char_id}] Error parsing config.json: {e}, creating new config"
            )

            base_config = self.BASE_DEFAULTS.copy()
            if hasattr(self, "DEFAULT_OVERRIDES"):
                base_config.update(self.DEFAULT_OVERRIDES)

            for k, v in bounds_defaults.items():
                base_config.setdefault(k, v)

            os.makedirs(os.path.dirname(config_path), exist_ok=True)

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(base_config, f, indent=4, ensure_ascii=False)

            for key, value in base_config.items():
                self.set_variable(key, value)

            logger.info(
                f"[{self.char_id}] New config created with defaults after JSON error"
            )

        except Exception as e:
            logger.error(f"[{self.char_id}] Error loading/creating config.json: {e}")

    def get_stats_dict(self) -> Dict[str, float]:
        return {
            "attitude": float(self.get_variable("attitude", 60.0)),
            "boredom": float(self.get_variable("boredom", 10.0)),
            "stress": float(self.get_variable("stress", 5.0)),
        }

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any):
        if isinstance(value, str):
            val_lower = value.lower()
            if val_lower == "true":
                value = True
            elif val_lower == "false":
                value = False
            elif value.isdigit():
                try:
                    value = int(value)
                except ValueError:
                    pass
            elif re.fullmatch(r"-?\d+(\.\d+)?", value):
                try:
                    value = float(value)
                except ValueError:
                    pass
            else:
                if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
                    value = value[1:-1]

        self.variables[name] = value
        self._dirty_vars.add(name)

    def flush_variables(self):
        """Batch-write all dirty variables to DB in a single transaction."""
        if not self._dirty_vars or not hasattr(self, "history_manager"):
            return
        to_flush = {k: self.variables[k] for k in self._dirty_vars if k in self.variables}
        if to_flush:
            self.history_manager.update_variables_batch(to_flush)
        self._dirty_vars.clear()

    def consume_pending_targets(self) -> list[str]:
        targets = getattr(self, "_pending_targets", [])
        self._pending_targets = []
        return targets

    def _extract_to_tag(self, response: str) -> tuple[str, str | None]:
        if not isinstance(response, str) or not response:
            return response, None

        m = re.search(r"<To>\s*([^<]+?)\s*</To>", response, flags=re.IGNORECASE)
        target = m.group(1).strip() if m else None

        if m:
            response = re.sub(r"<To>\s*([^<]+?)\s*</To>", "", response, flags=re.IGNORECASE).strip()

        return response, target

    def _get_prompt_set_setting_key(self) -> str:
        return f"PROMPT_SET_{self.char_id}"
    
    def _character_prompts_root(self) -> str:
        return os.path.join(self.prompts_root, self.char_id)

    def _discover_prompt_set_names(self) -> List[str]:
        root = self._character_prompts_root()
        try:
            if not os.path.isdir(root):
                return []
            names = [
                d
                for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d))
            ]
            names = [d for d in names if d and not d.startswith(".") and d not in {"System", "__pycache__", "SystemPrompts"}]
            return sorted(names)
        except Exception:
            return []

    def _resolve_prompt_set_name(self) -> str:
        key = self._get_prompt_set_setting_key()
        selected = ""

        try:
            res = self.event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {"key": key, "default": ""},
                timeout=0.5,
            )
            if res:
                selected = str(res[0] or "").strip()
        except Exception:
            selected = ""

        char_root = self._character_prompts_root()
        discovered = self._discover_prompt_set_names()

        def _norm(s: str) -> str:
            return (s or "").strip().casefold()

        if selected:
            selected_path = os.path.join(char_root, selected)
            if os.path.isdir(selected_path):
                return selected

            variants = {
                _norm(selected),
                _norm(selected.rstrip("_")),
                _norm(selected.rstrip("/\\")),
                _norm(selected.rstrip("/\\").rstrip("_")),
            }

            for s in discovered:
                if _norm(s) in variants:
                    return s

            msg = f"[{self.char_id}] Selected prompt set '{selected}' not found at: {selected_path}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)

        for s in discovered:
            if _norm(s) == "default":
                return s

        default_path = os.path.join(char_root, "Default")
        if os.path.isdir(default_path):
            return "Default"

        if discovered:
            return discovered[0]

        msg = (
            f"[{self.char_id}] No prompt sets found in: {char_root}. "
            f"Expected structure: Prompts/{self.char_id}/<SetName>/..."
        )
        try:
            logger.notify(msg)
        except Exception:
            logger.error(msg)

        return "Default"

    def _apply_prompt_set(self, set_name: str):
        self.prompt_set_name = str(set_name or "").strip() or "Default"
        self.base_data_path = os.path.join(self._character_prompts_root(), self.prompt_set_name)
        self.set_variable("PROMPT_SET_NAME", self.prompt_set_name)
        self.set_variable("PROMPT_SET_PATH", self.base_data_path)

    def _log_prompt_set_problems_if_any(self):
        base = str(getattr(self, "base_data_path", "") or "")
        if not base:
            msg = f"[{self.char_id}] base_data_path is empty (prompt set path not resolved)."
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)
            return

        if not os.path.isdir(base):
            msg = f"[{self.char_id}] Prompt set folder does not exist: {base}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)
            return

        main_tpl = os.path.join(base, self.main_template_path_relative)
        if not os.path.exists(main_tpl):
            msg = f"[{self.char_id}] main_template not found: {main_tpl}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)

    def process_response_nlp_commands(self, response: str, save_as_missed=False) -> str:
        original_response_for_log = (
            response[:200] + "..." if len(response) > 200 else response
        )
        logger.info(
            f"[{self.char_id}] Original LLM response: {original_response_for_log}"
        )

        try:
            response = self.post_dsl_interpreter.process(response)
            processed_response_for_log = (
                response[:200] + "..." if len(response) > 200 else response
            )
            logger.info(
                f"[{self.char_id}] Response after Post-DSL: {processed_response_for_log}"
            )
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error during Post-DSL processing: {e}", exc_info=True
            )

        self.set_variable(
            "LongMemoryRememberCount",
            self.get_variable("LongMemoryRememberCount", 0) + 1,
        )
        try:
            results = self.event_bus.emit_and_wait(
                Events.Settings.GET_APP_VARS, timeout=1.0
            )
            app_vars: Dict[str, Any] = {}
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
            self.update_app_vars(app_vars)
        except Exception as e:
            logger.warning(
                f"[{self.char_id}] Не удалось получить app_vars через события: {e}"
            )
            self.update_app_vars({})

        response = self.extract_and_process_memory_data(response, save_as_missed)

        try:
            response = self._process_behavior_changes_from_llm(response)
        except Exception as e:
            logger.warning(
                f"Error processing built-in behavior changes from LLM for {self.char_id}: {e}",
                exc_info=True,
            )

        try:
            response = self._process_game_tags(response)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error during game tag processing: {e}", exc_info=True
            )

        response, target = self._extract_to_tag(response)
        self._pending_targets = [target] if target else []

        final_response_for_log = (
            response[:200] + "..." if len(response) > 200 else response
        )
        logger.debug(
            f"[{self.char_id}] Final response after all processing: {final_response_for_log}"
        )

        return response

    def process_structured_response(self, structured: StructuredResponse, save_as_missed: bool = False) -> StructuredResponse:
        """
        Process a StructuredResponse: apply global fields (behavior changes,
        memory operations) and game tags from segments.

        This is the structured-output counterpart of process_response_nlp_commands.
        It modifies character state in-place and returns the (possibly modified)
        StructuredResponse.
        """
        logger.info(
            f"[{self.char_id}] Processing structured response: "
            f"{len(structured.segments)} segment(s), "
            f"attitude_change={structured.attitude_change}, "
            f"boredom_change={structured.boredom_change}, "
            f"stress_change={structured.stress_change}"
        )

        self.set_variable(
            "LongMemoryRememberCount",
            self.get_variable("LongMemoryRememberCount", 0) + 1,
        )
        try:
            results = self.event_bus.emit_and_wait(
                Events.Settings.GET_APP_VARS, timeout=1.0
            )
            app_vars: Dict[str, Any] = {}
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
            self.update_app_vars(app_vars)
        except Exception as e:
            logger.warning(
                f"[{self.char_id}] Could not get app_vars via events: {e}"
            )
            self.update_app_vars({})

        # Apply behavior changes from global fields
        try:
            if structured.attitude_change:
                self.adjust_attitude(structured.attitude_change)
            if structured.boredom_change:
                self.adjust_boredom(structured.boredom_change)
            if structured.stress_change:
                self.adjust_stress(structured.stress_change)
        except Exception as e:
            logger.warning(
                f"[{self.char_id}] Error applying behavior changes from structured response: {e}",
                exc_info=True,
            )

        # Apply memory operations from global fields
        try:
            self._apply_structured_memory_ops(structured, save_as_missed)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error applying memory ops from structured response: {e}",
                exc_info=True,
            )

        # Apply reminder operations from global fields
        try:
            self._apply_structured_reminder_ops(structured)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error applying reminder ops from structured response: {e}",
                exc_info=True,
            )

        # Process game tags from segments (start_game / end_game)
        try:
            self._process_structured_game_tags(structured)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error processing game tags from structured response: {e}",
                exc_info=True,
            )

        # Collect all unique targets from all segments (preserving order)
        seen: set[str] = set()
        targets: list[str] = []
        for seg in structured.segments:
            if seg.target and seg.target not in seen:
                seen.add(seg.target)
                targets.append(seg.target)
        self._pending_targets = targets

        return structured

    def _apply_structured_memory_ops(self, structured: StructuredResponse, save_as_missed: bool = False):
        """Apply memory add/update/delete operations from a StructuredResponse."""
        for mem_text in structured.memory_add:
            mem_text = (mem_text or "").strip()
            if not mem_text:
                continue
            # Support priority prefix: "priority|content"
            parts = [p.strip() for p in mem_text.split("|", 1)]
            if len(parts) == 2 and parts[0] in ("low", "normal", "high", "critical"):
                priority, content = parts
            else:
                priority, content = "normal", mem_text
            try:
                self.memory_system.add_memory(priority=priority, content=content)
                logger.info(f"[{self.char_id}] Structured: added memory (P: {priority}): {content[:50]}...")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error adding memory: {e}")

        for update_str in structured.memory_update:
            update_str = (update_str or "").strip()
            if not update_str or "|" not in update_str:
                continue
            parts = [p.strip() for p in update_str.split("|", 1)]
            if len(parts) == 2 and parts[0].isdigit():
                try:
                    self.memory_system.update_memory(
                        number=int(parts[0]),
                        priority=None,
                        content=parts[1],
                    )
                    logger.info(f"[{self.char_id}] Structured: updated memory #{parts[0]}")
                except Exception as e:
                    logger.error(f"[{self.char_id}] Structured: error updating memory #{parts[0]}: {e}")

        for delete_str in structured.memory_delete:
            delete_str = (delete_str or "").strip()
            if not delete_str:
                continue
            try:
                if "," in delete_str:
                    for num_str in delete_str.split(","):
                        num_str = num_str.strip()
                        if num_str.isdigit():
                            self.memory_system.delete_memory(int(num_str), save_as_missed)
                        elif "-" in num_str:
                            sub = [s.strip() for s in num_str.split("-")]
                            if len(sub) == 2 and sub[0].isdigit() and sub[1].isdigit():
                                for n in range(int(sub[0]), int(sub[1]) + 1):
                                    self.memory_system.delete_memory(n, save_as_missed)
                elif "-" in delete_str:
                    parts = [s.strip() for s in delete_str.split("-")]
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        for n in range(int(parts[0]), int(parts[1]) + 1):
                            self.memory_system.delete_memory(n, save_as_missed)
                elif delete_str.isdigit():
                    self.memory_system.delete_memory(int(delete_str), save_as_missed)
                logger.info(f"[{self.char_id}] Structured: deleted memory(ies): {delete_str}")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error deleting memory '{delete_str}': {e}")

    def _apply_structured_reminder_ops(self, structured: StructuredResponse):
        """Apply reminder add/delete operations from a StructuredResponse."""
        for entry in structured.reminder_add:
            entry = (entry or "").strip()
            if not entry:
                continue
            if "|" not in entry:
                logger.warning(f"[{self.char_id}] Structured: reminder_add bad format (missing '|'): {entry!r}")
                continue
            due_iso, text = entry.split("|", 1)
            try:
                self.reminder_system.add_reminder(text.strip(), due_iso.strip())
                logger.info(f"[{self.char_id}] Structured: added reminder due={due_iso.strip()}: {text.strip()[:50]}")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error adding reminder: {e}")

        for delete_str in structured.reminder_delete:
            delete_str = (delete_str or "").strip()
            if delete_str.isdigit():
                try:
                    self.reminder_system.delete_reminder(int(delete_str))
                    logger.info(f"[{self.char_id}] Structured: deleted reminder #{delete_str}")
                except Exception as e:
                    logger.error(f"[{self.char_id}] Structured: error deleting reminder #{delete_str}: {e}")
            elif delete_str:
                logger.warning(f"[{self.char_id}] Structured: reminder_delete bad format: {delete_str!r}")

    def _process_structured_game_tags(self, structured: StructuredResponse):
        """Process start_game / end_game from segments."""
        for seg in structured.segments:
            if seg.start_game:
                started = self.game_manager.start_game(seg.start_game)
                if started:
                    logger.info(f"[{self.char_id}] Structured: started game '{seg.start_game}'")
                else:
                    logger.info(f"[{self.char_id}] Structured: game start '{seg.start_game}' blocked by settings")

            if seg.end_game:
                self.game_manager.stop_game(seg.end_game)
                logger.info(f"[{self.char_id}] Structured: ended game '{seg.end_game}'")

    def _process_game_tags(self, response: str) -> str:
        """
        Обрабатывает общие игровые теги, такие как <StartGame> и <EndGame>,
        и делегирует их обработку игровому менеджеру.
        """
        start_match = re.search(
            r'<StartGame id="([^"]*)"/>', response, re.DOTALL | re.IGNORECASE
        )
        if start_match:
            full_id_str = start_match.group(1).strip()
            started = self.game_manager.start_game(full_id_str)
            response = response.replace(start_match.group(0), "", 1).strip()
            if started:
                logger.info(f"[{self.char_id}] Запрошен запуск игры с ID: '{full_id_str}'.")
            else:
                logger.info(f"[{self.char_id}] Запуск игры с ID '{full_id_str}' отклонён (заблокировано настройками).")

        end_match = re.search(
            r'<EndGame id="([^"]*)"/>', response, re.DOTALL | re.IGNORECASE
        )
        if end_match:
            full_id_str = end_match.group(1).strip()
            self.game_manager.stop_game(full_id_str)
            response = response.replace(end_match.group(0), "", 1).strip()
            logger.info(
                f"[{self.char_id}] Запрошена остановка игры с ID: '{full_id_str}'."
            )

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

        def p_tag_processor(match_obj):
            changes_str = match_obj.group(1)
            try:
                changes = [float(x.strip()) for x in changes_str.split(",")]
                if len(changes) == 3:
                    self.adjust_attitude(changes[0])
                    self.adjust_boredom(changes[1])
                    self.adjust_stress(changes[2])
                else:
                    logger.warning(
                        f"Invalid format in <p> tag for {self.char_id}: '{changes_str}'. Expected 3 values."
                    )
            except ValueError:
                logger.warning(
                    f"Invalid numeric values in <p> tag for {self.char_id}: '{changes_str}'"
                )
            return ""

        # Не убираю пока что
        re.sub(
            f"{re.escape(start_tag)}(.*?){re.escape(end_tag)}",
            p_tag_processor,
            response,
        )

        return response.strip()

    def extract_and_process_memory_data(
        self, response: str, save_as_missed=False
    ) -> str:
        """
        Extracts memory operation tags (<+memory>, <#memory>, <-memory>)
        from the LLM response, processes them, and removes them from the response string.
        """
        self._last_created_memory_ids: list[int] = []
        memory_pattern = r"<([+#~-])memory(?:_([a-zA-Z]+))?>(.*?)</\1?memory>"

        def memory_processor(match_obj):
            operation, tag_priority, content = match_obj.groups()
            content = content.strip()

            try:
                if operation == "+":
                    parts = [p.strip() for p in content.split("|", 1)]
                    priority = tag_priority or (
                        parts[0]
                        if len(parts) == 2
                        and parts[0] in ["low", "normal", "high", "critical"]
                        else "normal"
                    )
                    mem_content = parts[-1]

                    if (
                        priority not in ["low", "normal", "high", "critical"]
                        and len(parts) == 2
                    ):
                        mem_content = content
                        priority = tag_priority or "normal"

                    eid = self.memory_system.add_memory(
                        priority=priority, content=mem_content
                    )
                    if eid is not None:
                        self._last_created_memory_ids.append(eid)
                    logger.info(
                        f"[{self.char_id}] Added memory (P: {priority}): {mem_content[:50]}..."
                    )

                elif operation == "#":
                    parts = [p.strip() for p in content.split("|", 2)]
                    if len(parts) >= 2:
                        mem_num_str = parts[0]
                        new_priority = tag_priority
                        new_content = ""

                        if len(parts) == 2:
                            new_content = parts[1]
                        elif len(parts) == 3:
                            new_priority = parts[1]
                            new_content = parts[2]

                        if mem_num_str.isdigit():
                            self.memory_system.update_memory(
                                number=int(mem_num_str),
                                priority=new_priority,
                                content=new_content,
                            )
                            logger.info(
                                f"[{self.char_id}] Updated memory #{mem_num_str} (New P: {new_priority or 'kept'})."
                            )
                        else:
                            logger.warning(
                                f"[{self.char_id}] Invalid number for memory update: {mem_num_str}"
                            )
                    else:
                        logger.warning(
                            f"[{self.char_id}] Invalid format for memory update: {content}"
                        )

                elif operation == "~":
                    # Format: <~memory>SOURCE→TARGET:new_content</~memory>
                    # Arrow can be → (U+2192) or ->; new_content is optional
                    arrow = "→" if "→" in content else "->"
                    arrow_parts = content.split(arrow, 1)
                    if len(arrow_parts) != 2:
                        logger.warning(
                            f"[{self.char_id}] Invalid format for memory merge (expected SOURCE→TARGET[:content]): {content}"
                        )
                    else:
                        source_str = arrow_parts[0].strip()
                        rest = arrow_parts[1].strip()
                        colon_idx = rest.find(":")
                        if colon_idx >= 0:
                            target_str = rest[:colon_idx].strip()
                            new_content = rest[colon_idx + 1:].strip() or None
                        else:
                            target_str = rest.strip()
                            new_content = None

                        if source_str.isdigit() and target_str.isdigit():
                            source_id = int(source_str)
                            target_id = int(target_str)
                            ok = self.memory_system.merge_memories(source_id, target_id, new_content)
                            if ok:
                                logger.info(
                                    f"[{self.char_id}] Merged memory #{source_id} into #{target_id}"
                                )
                            else:
                                logger.warning(
                                    f"[{self.char_id}] Failed to merge memory #{source_id} into #{target_id}"
                                )
                        else:
                            logger.warning(
                                f"[{self.char_id}] Invalid IDs for memory merge: source='{source_str}', target='{target_str}'"
                            )

                elif operation == "-":

                    content_cleaned = content.strip()
                    if "," in content_cleaned:
                        numbers_str = [
                            num.strip() for num in content_cleaned.split(",")
                        ]
                        for num_str in numbers_str:
                            if num_str.isdigit():
                                self.memory_system.delete_memory(
                                    int(num_str), save_as_missed
                                )
                    elif "-" in content_cleaned:
                        start_end = [s.strip() for s in content_cleaned.split("-")]
                        if (
                            len(start_end) == 2
                            and start_end[0].isdigit()
                            and start_end[1].isdigit()
                        ):
                            for num_to_del in range(
                                int(start_end[0]), int(start_end[1]) + 1
                            ):
                                self.memory_system.delete_memory(
                                    num_to_del, save_as_missed
                                )
                    elif content_cleaned.isdigit():
                        self.memory_system.delete_memory(
                            int(content_cleaned), save_as_missed
                        )
                    else:
                        logger.warning(
                            f"[{self.char_id}] Invalid format for memory deletion: {content_cleaned}"
                        )

            except Exception as e:
                logger.error(
                    f"[{self.char_id}] Error processing memory command <{operation}memory>: {content}. Error: {str(e)}",
                    exc_info=True,
                )

            return match_obj.group(0)

        return re.sub(
            memory_pattern, memory_processor, response, flags=re.DOTALL
        ).strip()

    def reload_character_data(self):
        logger.info(
            f"[{self.char_id}] Reloading character data from disk (config + history)."
        )

        try:
            resolved = self._resolve_prompt_set_name()
            self._apply_prompt_set(resolved)
        except Exception as e:
            msg = f"[{self.char_id}] Failed to resolve/apply prompt set during reload: {e}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)
            self._apply_prompt_set("Default")

        self._log_prompt_set_problems_if_any()

        self.load_config()
        self.load_history()
        self.memory_system.load_memories()
        self.set_variable(
            "SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes")
        )

        try:
            from managers.dsl_manager import create_dsl_interpreter
            self.dsl_interpreter = create_dsl_interpreter(self)
        except Exception as e:
            logger.warning(f"[{self.char_id}] Failed to recreate DSL interpreter during reload: {e}", exc_info=True)

        try:
            path_resolver_instance = LocalPathResolver(
                global_prompts_root=self.prompts_root,
                character_base_data_path=self.base_data_path,
            )
            self.post_dsl_interpreter = PostDslInterpreter(self, path_resolver_instance)
            logger.info(f"[{self.char_id}] Post-DSL interpreter re-initialized and rules loaded during reload.")
        except Exception as e:
            logger.warning(f"[{self.char_id}] Failed to recreate Post-DSL interpreter during reload: {e}", exc_info=True)

        logger.info(f"[{self.char_id}] Character data reloaded.")

    # region History

    def load_history(self):
        """Loads variables from history into self.variables.
        This is called after defaults and overrides are set during __init__.
        Persisted variables will overwrite the initial composed ones.
        """
        data = self.history_manager.load_history()
        loaded_vars = data.get("variables", {})

        if loaded_vars:
            for key, value in loaded_vars.items():
                self.set_variable(key, value)
            logger.info(
                f"[{self.char_id}] Loaded variables from history, overriding defaults/initials."
            )
        else:
            logger.info(
                f"[{self.char_id}] No variables found in history, using composed initial values."
            )
        return data

    def save_character_state_to_history(self, messages: List[Dict[str, str]]):
        """Force-sync full state to DB: flushes dirty variables, then persists
        all messages and variables. Called at end-of-turn and on explicit saves."""
        self.flush_variables()
        history_data = {"messages": messages, "variables": self.variables.copy()}
        self.history_manager.save_history(history_data)

    def clear_history(self):
        logger.info(f"[{self.char_id}] Clearing history and resetting state.")

        composed_initials = Character.BASE_DEFAULTS.copy()
        if hasattr(self, "DEFAULT_OVERRIDES"):
            subclass_overrides = getattr(self, "DEFAULT_OVERRIDES", {})
            composed_initials.update(subclass_overrides)

        self.variables.clear()
        for key, value in composed_initials.items():
            self.set_variable(key, value)

        self.load_config()

        self.memory_system.clear_memories()
        self.history_manager.clear_history()
        logger.info(
            f"[{self.char_id}] History cleared and state reset to initial defaults/overrides."
        )

    # --- ИЗМЕНЕНИЯ В add_message_to_history ---
    def add_message_to_history(self, message: Dict[str, str]):
        # [NEW] Используем точечное добавление вместо перезаписи всего списка
        # Это сильно ускорит работу на длинных историях
        self.history_manager.add_message(message)

        # Обновлять локальный список в памяти (если он нужен для контекста) можно перезагрузкой
        # или просто не хранить его в классе Character, полагаясь на history_manager.load_history()
        # Но чтобы не ломать старую логику, которая может ожидать messages внутри history_data,
        # оставим всё как есть, просто база обновляется инкрементально.

    # endregion

    def current_variables_string(self) -> str:
        """Returns a string representation of key variables for UI/debug display,
        customizable via Post-DSL DEBUG_DISPLAY section."""
        display_str = f"Character: {self.name} ({self.char_id})\n"

        vars_to_display = {}
        if (
            hasattr(self, "post_dsl_interpreter")
            and self.post_dsl_interpreter.debug_display_config
        ):
            for (
                label,
                var_name,
            ) in self.post_dsl_interpreter.debug_display_config.items():
                vars_to_display[label] = self.get_variable(var_name, "N/A")
        else:
            vars_to_display = {
                "Attitude": self.get_variable("attitude", "N/A"),
                "Boredom": self.get_variable("boredom", "N/A"),
                "Stress": self.get_variable("stress", "N/A"),
            }
            if self.char_id == "Crazy":
                vars_to_display["Secret Exposed"] = self.get_variable(
                    "secretExposed", "N/A"
                )
                vars_to_display["FSM State"] = self.get_variable(
                    "current_fsm_state", "N/A"
                )

        for key, val in vars_to_display.items():
            display_str += f"- {key}: {val}\n"

        return display_str.strip()

    def update_app_vars(self, app_vars: Dict[str, Any]):
        """Обновляет переменные программы для исползования в логике DSL"""
        self.app_vars = app_vars.copy()
        logger.debug(f"[{self.char_id}] App vars updated: {list(self.app_vars.keys())}")

    def adjust_attitude(self, amount: float):
        current = self.get_variable("attitude", 60.0)
        amount = round(amount, 2)
        amount = clamp(float(amount), -6.0, 6.0)

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
            logger.error(
                f"[{self.char_id}] Invalid config: attitude_max ({max_val}) is less than attitude_min ({min_val})."
            )
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

        self.set_variable("attitude", new_value)
        logger.info(
            f"[{self.char_id}] Attitude changed by {amount:.2f} to {self.get_variable('attitude'):.2f}"
        )

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
            logger.error(
                f"[{self.char_id}] Invalid config: boredom_max ({max_val}) is less than boredom_min ({min_val})."
            )
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
        logger.info(
            f"[{self.char_id}] Boredom changed by {amount:.2f} to {self.get_variable('boredom'):.2f}"
        )

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
            logger.error(
                f"[{self.char_id}] Invalid config: stress_max ({max_val}) is less than stress_min ({min_val})."
            )
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
        logger.info(
            f"[{self.char_id}] Stress changed by {amount:.2f} to {self.get_variable('stress'):.2f}"
        )

    def to_voice_profile(self) -> Dict[str, Any]:
        """
        Плоский профиль персонажа для озвучки и внешних контроллеров.
        Не содержит тяжёлых ссылок/менеджеров и безопасен для передачи по EventBus.
        """
        return {
            "character_id": str(getattr(self, "char_id", "") or ""),
            "name": str(getattr(self, "name", "") or ""),
            "is_cartridge": bool(getattr(self, "is_cartridge", False)),
            "silero_command": str(getattr(self, "silero_command", "") or ""),
            "short_name": str(getattr(self, "short_name", "") or ""),
            "miku_tts_name": str(getattr(self, "miku_tts_name", "Player") or "Player"),
            "silero_turn_off_video": bool(getattr(self, "silero_turn_off_video", False)),
        }

    def __str__(self):
        return f"Character(id='{self.char_id}', name='{self.name}')"

