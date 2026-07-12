from __future__ import annotations
from typing import Dict, Any, List, Optional
import os
import base64
import datetime

from core.services import services, use
from main_logger import logger
from services.contracts import (
    AppVarsService,
    HistoryService,
    PromptBuildRequest,
    PromptBuildResult,
    PromptBuilderService,
    SettingsService,
)
from utils.prompt_builder import build_system_prompts
from core.request_policy import RequestPolicy
from services.runtime_capabilities import runtime_capabilities

_TYPE_MAP = {"float": "number", "double": "number", "int": "integer",
             "bool": "boolean", "str": "string", "string": "string"}
_VOLATILE_SYSTEM_BLOCK_PREFIXES = (
    "current context:",
)


def _build_custom_params_schema(custom_params: list) -> str:
    """Build the custom_fields schema block from character custom_params."""
    if not custom_params:
        return ""
    field_lines = []
    for p in custom_params:
        cmd = p.get("change_command") or p["name"]
        json_type = _TYPE_MAP.get(p.get("type", "string"), "string")
        desc = p.get("description", "")
        c_min, c_max = p.get("change_min"), p.get("change_max")
        range_str = f" ({c_min} to {c_max})" if c_min is not None and c_max is not None else ""
        field_lines.append(f'    "{cmd}": <{json_type}{range_str}>,  // {desc}')
    return '  "custom_fields": {\n' + "\n".join(field_lines) + "\n  },\n"


class PromptController(PromptBuilderService):
    """Сборка промпта. Чистая функция над персонажем и историей — шина не нужна."""

    def __init__(self):
        services().register(PromptBuilderService, self, replace=True)

    def _get_setting(self, key: str, default=None):
        return use(SettingsService).get(key, default)

    @staticmethod
    def _format_system_state_message(
        *,
        remote_only: bool | None,
        voice_enabled: bool,
        voice_method: str,
        microphone_enabled: bool,
        image_status: str,
    ) -> Dict[str, str]:
        """Собирает служебное состояние, не попадающее в историю диалога."""
        lines = ["[System State]"]

        if remote_only is True:
            lines.append(
                "You are currently communicating with the Player online through the NeuroMita computer program. "
                "The Player is not physically with you right now, but they may come to your home later. "
                "If you want to see them, do not hesitate to invite them. "
                "Do not use world or game commands such as switching lights or moving around. "
                "The commands field may still be used for program-level commands when genuinely needed."
            )
        elif remote_only is False:
            lines.append(
                "You are currently communicating with the Player through the NeuroMita computer program "
                "while the game runtime is connected."
            )
        else:
            lines.append("You are currently communicating with the Player through the NeuroMita computer program.")

        if voice_enabled:
            method = voice_method.strip() or "configured method"
            lines.append(f"Your voice (TTS): enabled; method: {method}. This is your voice.")
        else:
            lines.append("Your voice (TTS): disabled. The Player can only receive your written replies.")

        lines.append(
            "The Player's voice (microphone): enabled. This is how you hear the Player."
            if microphone_enabled
            else "The Player's voice (microphone): disabled. You cannot hear the Player's voice."
        )
        lines.append(
            "Your sight (image recognition): enabled. You can use screenshots and images as visual information."
            if image_status == "enabled"
            else "Your sight (image recognition): disabled. You cannot see screenshots or images."
        )
        return {"role": "system", "content": "\n".join(lines)}

    def _build_system_state_message(self) -> Dict[str, str]:
        remote_only = runtime_capabilities().remote_only

        image_status = (
            "enabled"
            if bool(self._get_setting("ENABLE_IMAGE_ANALYSIS", False))
            else "disabled"
        )

        return self._format_system_state_message(
            remote_only=remote_only,
            voice_enabled=bool(self._get_setting("USE_VOICEOVER", False)),
            voice_method=str(self._get_setting("VOICEOVER_METHOD", "Local") or "Local"),
            microphone_enabled=bool(self._get_setting("MIC_ACTIVE", False)),
            image_status=image_status,
        )

    def _setup_character_for_prompt(self, character, event_type: str):
        now_str = datetime.datetime.now().strftime("%Y %B %d (%A) %H:%M")
        character.set_variable("SYSTEM_DATETIME", now_str)
        character.update_app_vars(use(AppVarsService).snapshot())

        if getattr(character, "char_id", "") == "GameMaster":
            character.set_variable("GM_INSTRUCTION", self._get_setting("GM_SMALL_PROMPT", "") or "")

    def _build_system_messages(
        self,
        character,
        event_type: str,
        separate_prompts: bool,
        policy: RequestPolicy | None = None,
        capabilities: Dict[str, Any] | None = None,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        self._setup_character_for_prompt(character, event_type)

        # Expose capabilities as character variables so DSL templates can use them
        # via [{VAR}] substitution (e.g. in response_format_json.script includes).
        caps = capabilities or {}
        character.set_variable("TOOLS_DESCRIPTION", caps.get("tools_prompt", "") or "")
        character.set_variable("SCHEMA_REASONING_ENABLED", caps.get("schema_reasoning", False))
        character.set_variable("CUSTOM_PARAMS_SCHEMA",
                               _build_custom_params_schema(getattr(character, "custom_params", [])))

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
                    common_react = "../../Common/react_template.txt"
                    common_candidate = os.path.normpath(
                        os.path.join(character.base_data_path, common_react)
                    )
                    if os.path.exists(common_candidate):
                        template_name = common_react
                    else:
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
            return [], [], []

        stable_system_messages: List[Dict[str, Any]] = []
        volatile_system_messages: List[Dict[str, Any]] = []
        stable_blocks: List[str] = []
        volatile_blocks: List[str] = []
        for block in blocks or []:
            if self._is_volatile_system_block(block):
                volatile_blocks.append(block)
            else:
                stable_blocks.append(block)

        stable_system_messages.extend(build_system_prompts(stable_blocks, separate=separate_prompts))
        volatile_system_messages.extend(build_system_prompts(volatile_blocks, separate=separate_prompts))

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
            volatile_system_messages.append({"role": "system", "content": memory_message_content})

        try:
            if hasattr(character, "reminder_system") and character.reminder_system:
                reminder_content = character.reminder_system.get_reminders_formatted()
                if reminder_content and reminder_content.strip():
                    volatile_system_messages.append({"role": "system", "content": reminder_content})
        except Exception as e:
            logger.warning(
                f"[PromptController] Ошибка получения напоминаний для персонажа "
                f"{getattr(character, 'char_id', '')}: {e}"
            )

        return stable_system_messages, volatile_system_messages, dsl_system_infos

    @staticmethod
    def _build_behavior_state_message(character) -> Optional[Dict[str, str]]:
        try:
            attitude = float(character.get_variable("attitude", 60.0))
            boredom = float(character.get_variable("boredom", 10.0))
            stress = float(character.get_variable("stress", 5.0))
        except Exception:
            return None

        lines = [
            "[Behavior State]",
            f"Attitude: {attitude:.1f}",
            f"Boredom: {boredom:.1f}",
            f"Stress: {stress:.1f}",
        ]

        try:
            for param in getattr(character, "custom_params", []) or []:
                if not isinstance(param, dict):
                    continue
                name = str(param.get("name") or "").strip()
                if name.lower() != "love":
                    continue
                love_value = character.get_variable(name, param.get("default", param.get("initial", 0.0)))
                if isinstance(love_value, float):
                    lines.append(f"Love: {love_value:.1f}")
                else:
                    lines.append(f"Love: {love_value}")
                break
        except Exception:
            pass

        return {"role": "system", "content": "\n".join(lines)}

    @staticmethod
    def _is_volatile_system_block(block: Any) -> bool:
        if not isinstance(block, str):
            return False
        normalized = " ".join(block.strip().split()).lower()
        return any(normalized.startswith(prefix) for prefix in _VOLATILE_SYSTEM_BLOCK_PREFIXES)

    @staticmethod
    def _build_unity_actual_info_message(game_state: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Return Unity's current context as a volatile system message when present."""
        actual_info = game_state.get("actualInfo", "")
        if not actual_info or not str(actual_info).strip():
            return None
        return {"role": "system", "content": f"Other info: {actual_info}"}

    def build(self, request: PromptBuildRequest) -> PromptBuildResult:
        character = request.character
        char_id = str(getattr(character, "char_id", "") or "")
        if not char_id:
            raise ValueError("build_prompt: character без char_id")

        event_type = request.event_type
        user_input = request.user_input or ""
        system_input = request.system_input or ""
        hidden_user_context = request.hidden_user_context or ""
        image_data = request.image_data or []

        sender = str(request.sender or "Player")
        participants = self._normalize_participants(request.participants)

        memory_limit = int(request.memory_limit)
        is_game_master = bool(request.is_game_master)
        save_missed_history = bool(request.save_missed_history)
        image_cfg = request.image_quality or {}
        separate_prompts = bool(request.separate_prompts)
        extra_system_infos = request.extra_system_infos or []
        game_state = request.game_state or {}
        capabilities = request.capabilities or {}
        rag_context = request.rag_context or ""
        policy = request.policy

        game_state_prompt_content: Optional[str] = None
        try:
            if character.get_variable("playingGame", False) and hasattr(character, "game_manager"):
                game_state_prompt_content = character.game_manager.get_active_game_state_prompt()
        except Exception as e:
            logger.warning(f"[PromptController][{char_id}] Ошибка при формировании промпта игры: {e}", exc_info=True)

        messages: List[Dict[str, Any]] = []

        stable_system_messages, volatile_system_messages, dsl_system_infos = self._build_system_messages(
            character, event_type, separate_prompts, policy=policy,
            capabilities=capabilities,
        )
        unity_actual_info_message = self._build_unity_actual_info_message(game_state)
        if unity_actual_info_message:
            volatile_system_messages.insert(0, unity_actual_info_message)
        messages.extend(stable_system_messages)

        history_limited: List[Dict[str, Any]] = []
        history_summary: str = ""
        if policy.use_history_in_prompt:
            prepared = use(HistoryService).prepare_for_prompt(
                character=character,
                memory_limit=memory_limit,
                is_game_master=is_game_master,
                save_missed_history=save_missed_history,
                image_quality=image_cfg,
            )
            history_limited = list(prepared.messages)
            history_summary = prepared.summary.strip()

        for s in dsl_system_infos:
            if isinstance(s, str):
                messages.append({"role": "system", "content": s})
            elif isinstance(s, dict):
                messages.append(s)

        if history_summary:
            messages.append({
                "role": "system",
                "content": f"[HISTORY SUMMARY]\n{history_summary}",
            })

        messages.extend(history_limited)

        if game_state_prompt_content:
            messages.append({"role": "system", "content": game_state_prompt_content})

        non_player_participants = [p for p in participants if p and p != "Player"]
        if len(non_player_participants) >= 2:
            sys_txt = self._load_participants_system(character, non_player_participants, sender)
            if sys_txt:
                messages.append({"role": "system", "content": sys_txt})

        messages.extend(volatile_system_messages)

        # Relevant memories (RAG) идут отдельным сообщением сразу после
        # обычного active memory/reminders-блока, не смешиваясь с ним.
        if rag_context:
            messages.append({"role": "system", "content": rag_context})

        behavior_state_message = self._build_behavior_state_message(character)
        if behavior_state_message:
            messages.append(behavior_state_message)

        for info in extra_system_infos:
            if isinstance(info, dict):
                messages.append(info)
            elif isinstance(info, str):
                messages.append({"role": "system", "content": info})

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

        messages.append(self._build_system_state_message())

        event_types_as_event_role = {"idle_timeout", "idle", "timer", "reminder"}

        if system_input:
            role = "system"

            pr = str(getattr(policy, "system_input_role", "") or "").lower()
            if pr in ("system", "event"):
                role = pr

            if role != "event" and event_type in event_types_as_event_role:
                role = "event"

            messages.append({"role": role, "content": system_input})

        if hidden_user_context:
            messages.append({
                "role": "system",
                "content": hidden_user_context,
            })

        user_message_for_history: Optional[Dict[str, Any]] = None
        user_content_chunks: List[Dict[str, Any]] = []

        if user_input:
            if sender and sender != "Player":
                prefix = f"[{sender} is talking to you ({char_id})]: "
            else:
                prefix = ""
            user_content_chunks.append({"type": "text", "text": prefix + user_input})

        _is_structured = bool(capabilities.get("structured_output", False))
        inline_desc_enabled = bool(self._get_setting("IMAGE_INLINE_DESCRIPTION", False)) if image_data else False

        for img in image_data:
            if isinstance(img, bytes):
                img_b64 = base64.b64encode(img).decode("utf-8")
            else:
                img_b64 = str(img)
            user_content_chunks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        if image_data and inline_desc_enabled:
            _detail = str(self._get_setting("IMAGE_DESCRIPTION_DETAIL", "normal") or "normal")
            if _is_structured:
                from handlers.image_description_handler import get_structured_inline_instruction
                messages.append({
                    "role": "system",
                    "content": get_structured_inline_instruction(_detail)
                })
            else:
                from handlers.image_description_handler import get_inline_instruction
                messages.append({
                    "role": "system",
                    "content": get_inline_instruction(_detail)
                })

        if user_content_chunks:
            user_message_for_history = {"role": "user", "content": user_content_chunks}
            user_message_for_history["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if sender:
                user_message_for_history["sender"] = sender
            if non_player_participants:
                user_message_for_history["participants"] = non_player_participants

            messages.append(user_message_for_history)
            history_limited.append(user_message_for_history)

        return PromptBuildResult(
            messages=messages,
            history_messages=history_limited,
            user_message=user_message_for_history,
        )


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
