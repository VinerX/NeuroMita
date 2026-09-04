from core.error_utils import format_exception
import datetime
import re
import os
import threading
from typing import Dict, List, Any, Optional
import json

from DSL.path_resolver import LocalPathResolver
from DSL.post_dsl_engine import PostDslInterpreter
from utils import clamp
from core.character_locks import character_lock
from core.events import get_event_bus, Events
from core.safe_eval import safe_eval_expression
from core.services import use
from domain.dialogue_identity import DialogueActorKind
from services.contracts import AppVarsService, HistoryService, SettingsService

from managers.game_manager import GameManager
from managers.memory_manager import is_island
from schemas.structured_response import StructuredResponse

from main_logger import logger

RED_COLOR = "\033[91m"
RESET_COLOR = "\033[0m"

_CUSTOM_PARAM_FORMULA_CALLS = {
    "max": max,
    "min": min,
    "abs": abs,
    "int": int,
    "float": float,
    "round": round,
}


def _evaluate_custom_param_formula(
    formula: str,
    *,
    variables: Dict[str, Any],
    current: Any,
    value: Any,
    change_command: str,
    variable_name: str,
) -> Any:
    eval_ctx = dict(variables)
    eval_ctx["current"] = current
    eval_ctx["value"] = value
    eval_ctx[change_command] = value
    eval_ctx[variable_name] = current
    return safe_eval_expression(
        formula,
        names=eval_ctx,
        allowed_calls=_CUSTOM_PARAM_FORMULA_CALLS,
    )


class Character:
    dialogue_actor_kind = DialogueActorKind.CHARACTER
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

        _prompts_dir = os.environ.get("NEUROMITA_PROMPTS_DIR", os.path.abspath("Prompts"))
        self.prompts_root = (
            _prompts_dir
            if not is_cartridge
            else os.path.join(_prompts_dir, "Cartridges")
        )

        self.main_template_path_relative = "main_template.txt"

        self.variables: Dict[str, Any] = {}
        self._dirty_vars: set = set()
        # Поколение истории. Растёт при каждом сбросе; всё, что читало историю до
        # сброса (фоновое сжатие, кандидаты в память), обязано сверить эпоху перед
        # записью — иначе результат многосекундного LLM-вызова воскрешает удалённое.
        self.history_epoch: int = 0
        self.is_cartridge = is_cartridge
        self.app_vars: Dict[str, Any] = {}

        self.prompt_set_name: str | None = None
        self.base_data_path = self._character_prompts_root()

        try:
            resolved = self._resolve_prompt_set_name()
            self._apply_prompt_set(resolved)
        except Exception as e:
            msg = f"[{self.char_id}] Failed to resolve/apply prompt set: {format_exception(e)}"
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

        self.custom_params: List[Dict[str, Any]] = []
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

        self._resource_manager = None
        self._runtime_loaded = False
        self._runtime_load_lock = threading.RLock()

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

    def bind_resource_manager(self, manager) -> None:
        self._resource_manager = manager
        manager.register_character(self.char_id, self.name, self.base_data_path)

    def _resources(self):
        manager = self._resource_manager
        if manager is None:
            from managers.character_resource_manager import get_character_resource_manager

            manager = get_character_resource_manager()
            self.bind_resource_manager(manager)
        return manager

    @property
    def history_manager(self):
        return self._resources().history_for(self.char_id, self.name)

    @property
    def memory_system(self):
        return self._resources().memory_for(self.char_id, self.name)

    @property
    def reminder_system(self):
        return self._resources().reminders_for(self.char_id, self.name)

    @property
    def working_state(self):
        return self._resources().working_state_for(self.char_id, self.name)

    def ensure_runtime_loaded(self) -> None:
        if self._runtime_loaded:
            return
        with self._runtime_load_lock:
            if self._runtime_loaded:
                return
            self.load_history()
            self.memory_system.load_memories()
            self._runtime_loaded = True

    def load_config(self):
        from managers.character_config_manager import CharacterConfigManager

        try:
            cm = CharacterConfigManager(
                character_id=self.char_id,
                base_data_path=self.base_data_path,
                logger=logger,
            )
            cfg = cm.load_or_create()

            self.custom_params = list(cfg.custom_params or [])

            # Применяем initial значения для кастомных параметров.
            # load_history() вызывается ПОСЛЕ load_config() и перезапишет их
            # сохранёнными значениями — так что при перезапуске переменные не сбросятся.
            for param in self.custom_params:
                param_name = param.get("name")
                initial = param.get("initial")
                if param_name and initial is not None:
                    self.set_variable(param_name, initial)

            reserved = {"PROMPT_SET_NAME", "PROMPT_SET_PATH"}
            for k, v in (cfg.variables or {}).items():
                if str(k) in reserved:
                    continue
                self.set_variable(str(k), v)

        except Exception as e:
            logger.error(f"[{self.char_id}] Error loading config via CharacterConfigManager: {format_exception(e)}", exc_info=True)

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
        if not self._dirty_vars:
            return
        to_flush = {k: self.variables[k] for k in self._dirty_vars if k in self.variables}
        if to_flush:
            self.history_manager.update_variables_batch(to_flush)
        self._dirty_vars.clear()

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

        selected = str(use(SettingsService).get(key, "") or "").strip()

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
        manager = getattr(self, "_resource_manager", None)
        if manager is not None:
            manager.update_prompt_set_path(self.char_id, self.base_data_path)

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
                f"[{self.char_id}] Error during Post-DSL processing: {format_exception(e)}", exc_info=True
            )

        self.set_variable(
            "LongMemoryRememberCount",
            self.get_variable("LongMemoryRememberCount", 0) + 1,
        )
        self.update_app_vars(use(AppVarsService).snapshot())

        response = self.extract_and_process_memory_data(response, save_as_missed)

        try:
            response = self._process_behavior_changes_from_llm(response)
        except Exception as e:
            logger.warning(
                f"Error processing built-in behavior changes from LLM for {self.char_id}: {format_exception(e)}",
                exc_info=True,
            )

        try:
            response = self._process_game_tags(response)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error during game tag processing: {format_exception(e)}", exc_info=True
            )

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
        self.update_app_vars(use(AppVarsService).snapshot())

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
                f"[{self.char_id}] Error applying behavior changes from structured response: {format_exception(e)}",
                exc_info=True,
            )

        # Apply memory operations from global fields
        try:
            self._apply_structured_memory_ops(structured, save_as_missed)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error applying memory ops from structured response: {format_exception(e)}",
                exc_info=True,
            )

        # Apply reminder operations from global fields
        try:
            self._apply_structured_reminder_ops(structured)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error applying reminder ops from structured response: {format_exception(e)}",
                exc_info=True,
            )

        # Process game tags from segments (start_game / end_game)
        try:
            self._process_structured_game_tags(structured)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error processing game tags from structured response: {format_exception(e)}",
                exc_info=True,
            )

        # 1. Apply text PostDSL rules (Remove Asterisks etc.) to each segment
        try:
            for seg in structured.segments:
                seg.text = self.post_dsl_interpreter.process(seg.text)
        except Exception as e:
            logger.error(
                f"[{self.char_id}] Error in PostDSL text processing for segments: {format_exception(e)}",
                exc_info=True,
            )

        # Normalize custom_fields to a plain dict (it may be a Pydantic model when
        # build_structured_response_model() creates an ExtendedStructuredResponse).
        _cf_raw = structured.custom_fields
        if _cf_raw is not None and hasattr(_cf_raw, "model_dump"):
            _cf_raw = _cf_raw.model_dump(exclude_none=True)
        elif _cf_raw is not None and not isinstance(_cf_raw, dict):
            _cf_raw = dict(_cf_raw)

        # 2. Apply custom_params from config (порядок по гайду):
        #    1) клам change_min/change_max → 2) клам max_change (add) →
        #    3) formula или op → 4) клам min/max
        if _cf_raw:
            for param in self.custom_params:
                var_name = param.get("name")
                if not var_name:
                    continue
                change_cmd = param.get("change_command") or var_name
                if change_cmd not in _cf_raw:
                    continue
                raw_value = _cf_raw[change_cmd]
                if raw_value is None:
                    continue
                try:
                    # Приводим к числу для числовых типов
                    p_type = param.get("type", "float")
                    if p_type in ("float", "double", "number"):
                        value = float(raw_value)
                    elif p_type in ("int", "integer"):
                        value = int(raw_value)
                    else:
                        value = raw_value

                    # Шаг 2: клам входного значения в [change_min, change_max]
                    if isinstance(value, (int, float)):
                        c_min = param.get("change_min")
                        c_max = param.get("change_max")
                        if c_min is not None:
                            value = max(float(c_min), value)
                        if c_max is not None:
                            value = min(float(c_max), value)

                    # Шаг 3: клам в [-max_change, +max_change] только для op=add
                    op = param.get("op")
                    max_change = param.get("max_change")
                    if op == "add" and max_change is not None and isinstance(value, (int, float)):
                        mc = float(max_change)
                        value = max(-mc, min(mc, value))

                    current = self.get_variable(var_name, 0)
                    formula = param.get("formula")

                    # Шаг 4: применяем формулу или op
                    if formula:
                        new_val = _evaluate_custom_param_formula(
                            formula,
                            variables=self.variables,
                            current=current,
                            value=value,
                            change_command=change_cmd,
                            variable_name=var_name,
                        )
                    elif op == "add":
                        new_val = current + value
                    elif op == "set":
                        new_val = value
                    else:
                        logger.warning(
                            f"[{self.char_id}] custom_param '{var_name}': нет op или formula, пропускаем"
                        )
                        continue

                    # Шаг 5: клам результата в [min, max]
                    if isinstance(new_val, (int, float)):
                        pmin = param.get("min")
                        pmax = param.get("max")
                        if pmin is not None:
                            new_val = max(float(pmin), new_val)
                        if pmax is not None:
                            new_val = min(float(pmax), new_val)

                    self.set_variable(var_name, new_val)
                    logger.info(
                        f"[{self.char_id}] custom_param '{change_cmd}' → {var_name}={new_val}"
                    )
                except Exception as e:
                    logger.error(
                        f"[{self.char_id}] Error applying custom_param '{var_name}': {format_exception(e)}"
                    )

        # 3. Apply MATCH FIELD PostDSL rules (complex logic with expressions)
        if _cf_raw:
            try:
                self.post_dsl_interpreter.process_structured_fields(_cf_raw)
            except Exception as e:
                logger.error(
                    f"[{self.char_id}] Error in PostDSL field processing: {format_exception(e)}",
                    exc_info=True,
                )

        return structured

    def _apply_structured_memory_ops(self, structured: StructuredResponse, save_as_missed: bool = False):
        """Apply memory add/update/delete operations from a StructuredResponse."""
        self._last_created_memory_ids = []
        for mem_text in (structured.memory_add or []):
            mem_text = (mem_text or "").strip()
            if not mem_text:
                continue
            # Format: "priority|content" or "priority|content|entity1,entity2,..."
            parts = [p.strip() for p in mem_text.split("|", 2)]
            # Island upsert: "island:<type>|content" updates the single running
            # summary of that type instead of adding a duplicate memory.
            if parts and is_island(parts[0]):
                island_content = parts[1] if len(parts) >= 2 else ""
                try:
                    eid = self.memory_system.upsert_island(parts[0], island_content)
                    if eid is not None:
                        self._last_created_memory_ids.append(eid)
                    logger.info(f"[{self.char_id}] Structured: upserted {parts[0]} island")
                except Exception as e:
                    logger.error(f"[{self.char_id}] Structured: error upserting island: {format_exception(e)}")
                continue
            if len(parts) >= 2 and parts[0] in ("low", "normal", "high", "critical"):
                priority = parts[0]
                content = parts[1]
                ents = [e.strip() for e in parts[2].split(",")] if len(parts) == 3 and parts[2] else None
            else:
                priority, content, ents = "normal", mem_text, None
            try:
                eid = self.memory_system.add_memory(priority=priority, content=content, entities=ents)
                if eid is not None:
                    self._last_created_memory_ids.append(eid)
                logger.info(f"[{self.char_id}] Structured: added memory (P: {priority}): {content[:50]}...")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error adding memory: {format_exception(e)}")

        for update_str in (structured.memory_update or []):
            update_str = (update_str or "").strip()
            if not update_str or "|" not in update_str:
                continue
            # Format: "number|priority|content" or legacy "number|content"
            parts = [p.strip() for p in update_str.split("|", 2)]
            if not parts[0].isdigit():
                continue
            number = int(parts[0])
            valid_priorities = {"low", "normal", "high", "critical"}
            if len(parts) == 3 and parts[1].lower() in valid_priorities:
                priority, content = parts[1].lower(), parts[2]
            else:
                priority, content = None, "|".join(parts[1:])
            try:
                self.memory_system.update_memory(number=number, priority=priority, content=content)
                logger.info(f"[{self.char_id}] Structured: updated memory #{number}")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error updating memory #{number}: {format_exception(e)}")

        for delete_str in (structured.memory_delete or []):
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
                logger.error(f"[{self.char_id}] Structured: error deleting memory '{delete_str}': {format_exception(e)}")

        for merge_str in (structured.memory_merge or []):
            merge_str = (merge_str or "").strip()
            # Format: "id1,id2,..." or "id1,id2,...:merged content"
            ids_part, _, merged_content = merge_str.partition(":")
            id_strs = [s.strip() for s in ids_part.split(",")]
            if len(id_strs) < 2 or not all(s.isdigit() for s in id_strs):
                logger.warning(f"[{self.char_id}] Structured: memory_merge bad format: {merge_str!r}")
                continue
            tgt_id = int(id_strs[0])
            src_ids = [int(s) for s in id_strs[1:]]
            try:
                if not merged_content.strip():
                    parts = [self.memory_system.get_memory_content(tgt_id) or ""]
                    for sid in src_ids:
                        c = self.memory_system.get_memory_content(sid) or ""
                        if c:
                            parts.append(c)
                    merged_content = " | ".join(p for p in parts if p)
                ok = self.memory_system.update_memory(number=tgt_id, content=merged_content.strip())
                if not ok:
                    logger.error(f"[{self.char_id}] Structured: memory_merge target #{tgt_id} not found — aborting merge, sources NOT deleted")
                    continue
                for sid in src_ids:
                    self.memory_system.delete_memory(sid, save_as_missed)
                logger.info(f"[{self.char_id}] Structured: merged memories {src_ids} → #{tgt_id}")
            except Exception as e:
                logger.error(f"[{self.char_id}] Structured: error merging {src_ids}→#{tgt_id}: {format_exception(e)}")

    def _apply_structured_reminder_ops(self, structured: StructuredResponse):
        """Apply reminder add/delete operations from a StructuredResponse."""
        for entry in (structured.reminder_add or []):
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
                logger.error(f"[{self.char_id}] Structured: error adding reminder: {format_exception(e)}")

        for delete_str in (structured.reminder_delete or []):
            delete_str = (delete_str or "").strip()
            if delete_str.isdigit():
                try:
                    self.reminder_system.delete_reminder(int(delete_str))
                    logger.info(f"[{self.char_id}] Structured: deleted reminder #{delete_str}")
                except Exception as e:
                    logger.error(f"[{self.char_id}] Structured: error deleting reminder #{delete_str}: {format_exception(e)}")
            elif delete_str:
                logger.warning(f"[{self.char_id}] Structured: reminder_delete bad format: {delete_str!r}")

    def _process_structured_game_tags(self, structured: StructuredResponse):
        """Process start_game / end_game from segments, and dispatch commands to active game."""
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

            if seg.commands and self.get_variable("playingGame", False):
                self.game_manager.process_active_game_structured_commands(seg.commands)

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
                    f"[{self.char_id}] Error processing memory command <{operation}memory>: {content}. Error: {format_exception(e)}",
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
            msg = f"[{self.char_id}] Failed to resolve/apply prompt set during reload: {format_exception(e)}"
            try:
                logger.notify(msg)
            except Exception:
                logger.error(msg)
            self._apply_prompt_set("Default")

        self._log_prompt_set_problems_if_any()

        self.load_config()
        self._resources().update_prompt_set_path(self.char_id, self.base_data_path)
        self.load_history()
        self.memory_system.load_memories()
        self._runtime_loaded = True
        self.set_variable(
            "SYSTEM_DATETIME", datetime.datetime.now().isoformat(" ", "minutes")
        )

        try:
            from managers.dsl_manager import create_dsl_interpreter
            self.dsl_interpreter = create_dsl_interpreter(self)
        except Exception as e:
            logger.warning(f"[{self.char_id}] Failed to recreate DSL interpreter during reload: {format_exception(e)}", exc_info=True)

        try:
            path_resolver_instance = LocalPathResolver(
                global_prompts_root=self.prompts_root,
                character_base_data_path=self.base_data_path,
            )
            self.post_dsl_interpreter = PostDslInterpreter(self, path_resolver_instance)
            logger.info(f"[{self.char_id}] Post-DSL interpreter re-initialized and rules loaded during reload.")
        except Exception as e:
            logger.warning(f"[{self.char_id}] Failed to recreate Post-DSL interpreter during reload: {format_exception(e)}", exc_info=True)

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

        # Эпоху двигаем под тем же замком, что держит сжатие при записи результата:
        # либо сжатие успело записаться до сброса, либо увидит новую эпоху и выбросит
        # свой результат. Середины, в которой сводка переживает очистку, нет.
        with character_lock(self.char_id):
            self.history_epoch = int(getattr(self, "history_epoch", 0)) + 1
        try:
            use(HistoryService).on_history_reset(self.char_id)
        except Exception as e:
            logger.warning(f"[{self.char_id}] Не удалось снять отложенное сжатие: {format_exception(e)}", exc_info=True)

        # Sticky core-memory triggers (e.g. code 23) are session/chat-scoped.
        try:
            from managers.core_memory_triggers import reset as reset_core_triggers
            reset_core_triggers(self.char_id)
        except Exception:
            pass
        try:
            self.working_state.clear()
        except Exception:
            pass

        composed_initials = Character.BASE_DEFAULTS.copy()
        if hasattr(self, "DEFAULT_OVERRIDES"):
            subclass_overrides = getattr(self, "DEFAULT_OVERRIDES", {})
            composed_initials.update(subclass_overrides)

        # Переменные, которых после сброса не останется (сводка истории, её граница,
        # прогресс сюжета), надо удалить и из БД: чистка только in-memory значила, что
        # после перезапуска они воскресали поверх пустой истории.
        previous_keys = set(self.variables.keys())

        self.variables.clear()
        for key, value in composed_initials.items():
            self.set_variable(key, value)

        self.load_config()

        stale_keys = previous_keys - set(self.variables.keys())
        if stale_keys:
            try:
                self.history_manager.delete_variables(stale_keys)
            except Exception as e:
                logger.warning(f"[{self.char_id}] Не удалось удалить переменные при сбросе: {format_exception(e)}", exc_info=True)
        self.flush_variables()

        self.memory_system.clear_memories()
        self.history_manager.clear_history()

        try:
            from managers.rag.graph.graph_store import GraphStore
            from managers.database_manager import DatabaseManager
            GraphStore(DatabaseManager(), self.char_id).clear_for_character()
        except Exception as e:
            logger.warning(f"[{self.char_id}] Graph clear failed (ignored): {format_exception(e)}", exc_info=True)

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

    def add_messages_to_history(self, messages: List[Dict[str, str]]):
        """Atomically append one completed dialog turn for this character."""
        return self.history_manager.add_messages(messages)

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

    def _stat_change_hard_limit(self) -> float:
        """Absolute per-response change cap (existing scale, configurable).

        Defaults to 6.0 — the prior hard-coded bound. A normal reply is expected
        to stay well within this (about -2..+2, enforced softly through the
        prompt); larger jumps remain possible for genuinely significant moments.
        """
        try:
            return abs(float(self.get_variable("STAT_CHANGE_HARD_LIMIT", 6.0)))
        except Exception:
            return 6.0

    def _stat_bound(self, key: str, default: float):
        value = self.get_variable(key, default)
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _adjust_bounded_stat(self, name: str, amount: float, default_current: float) -> None:
        """Apply a per-response delta to a bounded stat.

        A zero delta is a valid, common outcome and leaves the value unchanged.
        The delta is clamped to the configurable hard limit; the result is
        clamped to the stat's [min, max] bounds so totals never leave the scale.
        """
        current = self.get_variable(name, default_current)
        try:
            current = float(current)
        except Exception:
            current = float(default_current)

        limit = self._stat_change_hard_limit()
        amount = clamp(round(float(amount), 2), -limit, limit)

        min_val = self._stat_bound(f"{name}_min", 0.0)
        max_val = self._stat_bound(f"{name}_max", 100.0)

        if (min_val is not None and max_val is not None) and max_val < min_val:
            logger.error(
                f"[{self.char_id}] Invalid config: {name}_max ({max_val}) is less than {name}_min ({min_val})."
            )
            min_val, max_val = None, None

        new_value = current + amount
        if min_val is not None and max_val is not None:
            new_value = clamp(new_value, min_val, max_val)
        elif min_val is not None:
            new_value = max(new_value, min_val)
        elif max_val is not None:
            new_value = min(new_value, max_val)

        self.set_variable(name, new_value)
        logger.info(
            f"[{self.char_id}] {name.capitalize()} changed by {amount:.2f} to {float(self.get_variable(name)):.2f}"
        )

    def adjust_attitude(self, amount: float):
        self._adjust_bounded_stat("attitude", amount, 60.0)

    def adjust_boredom(self, amount: float):
        self._adjust_bounded_stat("boredom", amount, 10.0)

    def adjust_stress(self, amount: float):
        self._adjust_bounded_stat("stress", amount, 5.0)

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

