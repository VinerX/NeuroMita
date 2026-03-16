from __future__ import annotations
from typing import Dict, Any, List, Optional
import os
import base64
import datetime

from core.events import get_event_bus, Events, Event
from main_logger import logger
from utils.prompt_builder import build_system_prompts
from core.request_policy import RequestPolicy, resolve_policy

_STRUCTURED_OUTPUT_PROMPT_PATH = os.path.join(
    os.path.abspath("Prompts"), "Structural", "response_format_json.txt"
)


class PromptController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Prompt.BUILD_PROMPT, self._on_build_prompt, weak=False)

    def _load_app_vars(self) -> Dict[str, Any]:
        app_vars: Dict[str, Any] = {}
        try:
            results = self.event_bus.emit_and_wait(Events.Settings.GET_APP_VARS, timeout=1.0)
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
        except Exception as e:
            logger.warning(f"[PromptController] Не удалось получить app_vars: {e}")
        return app_vars

    def _setup_character_for_prompt(self, character, event_type: str):
        now_str = datetime.datetime.now().strftime("%Y %B %d (%A) %H:%M")
        character.set_variable("SYSTEM_DATETIME", now_str)
        app_vars = self._load_app_vars()
        character.update_app_vars(app_vars)

        if getattr(character, "char_id", "") == "GameMaster":
            try:
                res = self.event_bus.emit_and_wait(
                    Events.Settings.GET_SETTING,
                    {"key": "GM_SMALL_PROMPT", "default": ""},
                    timeout=1.0
                )
                gm_instr = res[0] if res else ""
                character.set_variable("GM_INSTRUCTION", gm_instr or "")
            except Exception as e:
                logger.warning(f"[PromptController] Не удалось получить GM_SMALL_PROMPT для GameMaster: {e}")
                character.set_variable("GM_INSTRUCTION", "")

    def _build_system_messages(
        self,
        character,
        event_type: str,
        separate_prompts: bool,
        policy: RequestPolicy | None = None,
        capabilities: Dict[str, Any] | None = None,
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        self._setup_character_for_prompt(character, event_type)

        chosen_template = None

        if policy and policy.template_name_override:
            candidate = os.path.join(character.base_data_path, policy.template_name_override)
            if os.path.exists(candidate):
                chosen_template = policy.template_name_override

        if not chosen_template:
            if event_type == "react":
                template_name = "react_template.txt"
                candidate = os.path.join(character.base_data_path, template_name)
                if not os.path.exists(candidate):
                    template_name = character.main_template_path_relative
                chosen_template = template_name
            else:
                chosen_template = character.main_template_path_relative

        try:
            blocks, dsl_system_infos = character.dsl_interpreter.process_main_template(chosen_template)
        except Exception as e:
            logger.error(
                f"[PromptController] Ошибка DSL при обработке шаблона '{chosen_template}' "
                f"для персонажа {getattr(character, 'char_id', '')}: {e}",
                exc_info=True
            )
            return [], []

        system_messages: List[Dict[str, Any]] = []
        system_messages.extend(build_system_prompts(blocks, separate=separate_prompts))

        # Inject structured output format instructions when capability is enabled
        caps = capabilities or {}
        if caps.get("structured_output", False):
            so_prompt = self._load_structured_output_prompt()
            if so_prompt:
                system_messages.append({"role": "system", "content": so_prompt})

        memory_message_content = ""
        try:
            if hasattr(character, "memory_system") and character.memory_system:
                memory_message_content = character.memory_system.get_memories_formatted()
        except Exception as e:
            logger.warning(
                f"[PromptController] Ошибка получения памяти для персонажа "
                f"{getattr(character, 'char_id', '')}: {e}"
            )
            memory_message_content = ""

        if memory_message_content and memory_message_content.strip():
            system_messages.append({"role": "system", "content": memory_message_content})

        return system_messages, dsl_system_infos

    def _load_structured_output_prompt(self) -> str:
        """Load the structured output format instructions from the prompt file."""
        try:
            if os.path.exists(_STRUCTURED_OUTPUT_PROMPT_PATH):
                with open(_STRUCTURED_OUTPUT_PROMPT_PATH, "r", encoding="utf-8") as f:
                    return f.read().strip()
            else:
                logger.warning(
                    f"[PromptController] Structured output prompt not found: "
                    f"{_STRUCTURED_OUTPUT_PROMPT_PATH}"
                )
                return ""
        except Exception as e:
            logger.warning(f"[PromptController] Failed to load structured output prompt: {e}")
            return ""

    def _on_build_prompt(self, event: Event) -> Dict[str, Any]:
        data = event.data or {}

        char_id: str = data.get("character_id")
        if not char_id:
            logger.error("[PromptController] BUILD_PROMPT без character_id")
            return {"messages": [], "history_messages": [], "user_message": None}

        character = data.get("character_ref")
        if character is None:
            logger.error(f"[PromptController] BUILD_PROMPT для '{char_id}' без character_ref")
            return {"messages": [], "history_messages": [], "user_message": None}

        if getattr(character, "char_id", None) != char_id:
            logger.error(
                f"[PromptController] character_ref.char_id != character_id "
                f"({getattr(character, 'char_id', None)} != {char_id})"
            )
            return {"messages": [], "history_messages": [], "user_message": None}

        event_type: str = data.get("event_type", "chat")
        user_input: str = data.get("user_input", "") or ""
        system_input: str = data.get("system_input", "") or ""
        image_data = data.get("image_data") or []

        sender: str = str(data.get("sender") or "Player")
        participants_raw = data.get("participants") or []
        participants = self._normalize_participants(participants_raw)

        memory_limit: int = int(data.get("memory_limit", 40))
        is_game_master: bool = bool(data.get("is_game_master", False))
        save_missed_history: bool = bool(data.get("save_missed_history", True))
        image_cfg: Dict[str, Any] = data.get("image_quality", {}) or {}
        separate_prompts: bool = bool(data.get("separate_prompts", True))
        extra_system_infos: List[Any] = data.get("extra_system_infos") or []
        game_state: Dict[str, Any] = data.get("game_state") or {}
        disable_history_compression: bool = bool(data.get("disable_history_compression", False))
        capabilities: Dict[str, Any] = data.get("capabilities") or {}

        policy_dict = data.get("policy")
        policy = (
            RequestPolicy.from_dict(policy_dict)
            if isinstance(policy_dict, dict)
            else resolve_policy(model_event_type=str(event_type or "chat"))
        )

        try:
            character.set_variable("GAME_DISTANCE", float(game_state.get("distance", 0.0)))
            character.set_variable("GAME_ROOM_PLAYER", game_state.get("roomPlayer", -1))
            character.set_variable("GAME_ROOM_MITA", game_state.get("roomMita", -1))
            character.set_variable("GAME_NEAR_OBJECTS", game_state.get("nearObjects", ""))
            character.set_variable("GAME_ACTUAL_INFO", game_state.get("actualInfo", ""))
        except Exception as e:
            logger.warning(f"[PromptController] Не удалось обновить игровые переменные для {char_id}: {e}")

        game_state_prompt_content: Optional[str] = None
        try:
            if character.get_variable("playingGame", False) and hasattr(character, "game_manager"):
                game_state_prompt_content = character.game_manager.get_active_game_state_prompt()
        except Exception as e:
            logger.warning(f"[PromptController][{char_id}] Ошибка при формировании промпта игры: {e}", exc_info=True)

        messages: List[Dict[str, Any]] = []

        system_messages, dsl_system_infos = self._build_system_messages(
            character, event_type, separate_prompts, policy=policy,
            capabilities=capabilities,
        )
        messages.extend(system_messages)

        if game_state_prompt_content:
            messages.append({"role": "system", "content": game_state_prompt_content})

        non_player_participants = [p for p in participants if p and p != "Player"]
        if len(non_player_participants) >= 2:
            sys_txt = self._load_participants_system(character, non_player_participants, sender)
            if sys_txt:
                messages.append({"role": "system", "content": sys_txt})

        history_limited: List[Dict[str, Any]] = []
        if policy.use_history_in_prompt:
            hist_res = self.event_bus.emit_and_wait(
                Events.History.PREPARE_FOR_PROMPT,
                {
                    "character_id": char_id,
                    "character_ref": character,
                    "event_type": event_type,
                    "memory_limit": memory_limit,
                    "is_game_master": is_game_master,
                    "save_missed_history": save_missed_history,
                    "image_quality": image_cfg,
                    "disable_compression": disable_history_compression,
                },
                timeout=5.0
            )
            if hist_res and isinstance(hist_res[0], dict):
                history_limited = hist_res[0].get("history", []) or []

        for info in extra_system_infos:
            if isinstance(info, dict):
                history_limited.append(info)
            elif isinstance(info, str):
                history_limited.append({"role": "system", "content": info})

        for s in dsl_system_infos:
            if isinstance(s, str):
                history_limited.append({"role": "system", "content": s})
            elif isinstance(s, dict):
                history_limited.append(s)

        messages.extend(history_limited)

        current_time = datetime.datetime.now()
        messages.append({
            "role": "system",
            "content": (
                f"[Current State]\n"
                f"Date: {current_time.strftime('%Y-%m-%d')}\n"
                f"Time: {current_time.strftime('%H:%M:%S')}\n"
                f"Day of week: {current_time.strftime('%A')}"
            )
        })

        event_types_as_event_role = {"idle_timeout", "idle", "timer"}

        if system_input:
            role = "system"

            pr = str(getattr(policy, "system_input_role", "") or "").lower()
            if pr in ("system", "event"):
                role = pr

            if role != "event" and event_type in event_types_as_event_role:
                role = "event"

            messages.append({"role": role, "content": system_input})

        user_message_for_history: Optional[Dict[str, Any]] = None
        user_content_chunks: List[Dict[str, Any]] = []

        if user_input:
            prefix = f"[Собеседник: {sender}] " if sender and sender != "Player" else ""
            user_content_chunks.append({"type": "text", "text": prefix + user_input})

        for img in image_data:
            if isinstance(img, bytes):
                img_b64 = base64.b64encode(img).decode("utf-8")
            else:
                img_b64 = str(img)
            user_content_chunks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        if user_content_chunks:
            user_message_for_history = {"role": "user", "content": user_content_chunks}
            user_message_for_history["time"] = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
            if sender:
                user_message_for_history["sender"] = sender
            if non_player_participants:
                user_message_for_history["participants"] = non_player_participants

            messages.append(user_message_for_history)
            history_limited.append(user_message_for_history)

        return {
            "messages": messages,
            "history_messages": history_limited,
            "user_message": user_message_for_history,
        }


    def _normalize_participants(self, participants: Any) -> List[str]:
        if not participants:
            return []
        if isinstance(participants, str):
            parts = [p.strip() for p in participants.split(",")]
            participants = [p for p in parts if p]

        if not isinstance(participants, list):
            return []

        out: List[str] = []
        seen = set()

        for p in participants:
            s = str(p or "").strip()
            if not s:
                continue
            if s.lower() == "player":
                s = "Player"
            if s in seen:
                continue
            out.append(s)
            seen.add(s)

        return out

    def _load_participants_system(self, character, participants: List[str], sender: str) -> Optional[str]:
        if character is None or not hasattr(character, "dsl_interpreter") or character.dsl_interpreter is None:
            return None

        participants_lines = "\n".join(f"- {x}" for x in (participants or [])) if participants else "- (none)"

        vars_to_set = {
            "CHARACTER_NAME": str(getattr(character, "name", "") or getattr(character, "char_id", "") or "Character"),
            "PARTICIPANTS_TEXT": participants_lines,
            "SENDER_NAME": str(sender or "Player"),
        }

        old_values: dict[str, object] = {}
        try:
            for k, v in vars_to_set.items():
                try:
                    old_values[k] = character.get_variable(k, None)
                except Exception:
                    old_values[k] = None
                character.set_variable(k, v)

            base = str(getattr(character, "base_data_path", "") or "")
            if not base:
                return None

            candidates: list[tuple[str, str]] = [
                ("participants_dialogue.system", os.path.join(base, "participants_dialogue.system")),
                ("System/participants_dialogue.system", os.path.join(base, "System", "participants_dialogue.system")),
            ]

            global_abs = os.path.normpath(os.path.join(base, "..", "..", "System", "participants_dialogue.system"))
            global_rel = os.path.relpath(global_abs, base).replace(os.sep, "/")
            candidates.append((global_rel, global_abs))

            chosen_rel = None
            for rel, abs_path in candidates:
                if os.path.exists(abs_path):
                    chosen_rel = rel
                    break

            if not chosen_rel:
                return None

            content, _ = character.dsl_interpreter.process_file(chosen_rel, sys_msgs=[])
            content = (content or "").strip()
            return content if content else None

        except Exception as e:
            logger.warning(f"[PromptController] Не удалось обработать participants_dialogue.system через DSL: {e}", exc_info=True)
            return None

        finally:
            for k, old in old_values.items():
                try:
                    if old is None:
                        if hasattr(character, "variables") and isinstance(character.variables, dict):
                            character.variables.pop(k, None)
                        else:
                            character.set_variable(k, None)
                    else:
                        character.set_variable(k, old)
                except Exception:
                    pass
