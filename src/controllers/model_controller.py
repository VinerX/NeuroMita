# src/controllers/model_controller.py
from __future__ import annotations

import json
import datetime
import re
import copy
from typing import Optional, Any
import base64

from handlers.chat_handler import ChatModel
from utils import _
from core.events import get_event_bus, Events, Event
from main_logger import logger

from managers.api_preset_resolver import ApiPresetResolver
from managers.game_state_manager import GameState
from managers.context_counter import ContextCounter
from managers.conversation_event_writer import ConversationEventWriter
from managers.history_ui_projector import HistoryUiProjector
from core.request_policy import RequestPolicy, resolve_policy
from utils.structured_response_parser import (
    parse_structured_response,
    structured_response_to_result_dict,
    StructuredResponseParseError,
)

_ALL_TOOLS_LIST = ["calculator", "web_search", "google_search", "web_reader"]


def _render_tools_for_prompt(schema: list) -> str:
    """Format tool JSON schema list into a human-readable prompt block."""
    if not schema:
        return ""
    lines = ["Available tools:"]
    for tool in schema:
        name = tool.get("name", "?")
        desc = tool.get("description", "")
        params = tool.get("parameters", {}).get("properties", {})
        param_parts = []
        for pname, pdef in params.items():
            ptype = pdef.get("type", "any")
            pdesc = pdef.get("description", "")
            param_parts.append(f"{pname}: {ptype}" + (f" — {pdesc}" if pdesc else ""))
        params_str = ", ".join(param_parts) if param_parts else "no parameters"
        lines.append(f"- {name}({params_str}) — {desc}")
    return "\n".join(lines)


class ModelController:
    """
    ModelController:
    - генерирует ответы (Events.Model.GENERATE_RESPONSE)
    - хранит game_state + temporary system infos
    - занимается UI-пейджингом истории (LOAD_HISTORY/LOAD_MORE_HISTORY)
    - считает токены/стоимость

    Персонажи:
    - НЕ создаются здесь
    - берутся через Events.Character.* (единый источник истины)
    """

    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        # UI history paging
        self.lazy_load_batch_size = 50
        self.total_messages_in_history = 0
        self.loaded_messages_offset = 0
        self.loading_more_history = False

        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
        self.model = ChatModel(settings)

        self.context_counter = ContextCounter(encoding_model="gpt-4o-mini")
        self._base_prompt_cache: dict[tuple[str, str], list[dict]] = {}

        self.game_state = GameState()
        self._temporary_system_infos: list[dict] = []

        self.event_writer = ConversationEventWriter(character_ref_resolver=self._get_character_ref)
        self.ui_projector = HistoryUiProjector(resolve_name=lambda cid: str(getattr(self._get_character_ref(cid), "name", "") or cid))

        self._refresh_chat_model_character_refs()

        self._subscribe_to_events()

    # ---------------------------------------------------------------------
    # Character resolution via Events.Character.*
    # ---------------------------------------------------------------------

    def _get_current_character_id(self) -> Optional[str]:
        res = self.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
        profile = res[0] if res else None
        if not isinstance(profile, dict):
            return None
        cid = profile.get("character_id")
        return str(cid) if cid else None

    def _get_character_ref(self, character_id: str):
        if not character_id:
            return None
        res = self.event_bus.emit_and_wait(
            Events.Character.GET,
            {"character_id": str(character_id)},
            timeout=1.0
        )
        return res[0] if res else None

    def _get_current_character_ref(self):
        cid = self._get_current_character_id()
        if not cid:
            return None
        return self._get_character_ref(cid)

    def _refresh_chat_model_character_refs(self):
        """
        Заполняем ссылки в ChatModel для обратной совместимости.
        Вся логика построена через Events.Character.* (никаких DI).
        """
        current = self._get_current_character_ref()
        self.model.current_character = current

        # Попытаемся собрать registry персонажей (только если нужно)
        chars_map = {}
        all_ids_res = self.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
        all_ids = all_ids_res[0] if all_ids_res else None
        if isinstance(all_ids, list):
            for cid in all_ids:
                try:
                    ch = self._get_character_ref(str(cid))
                    if ch is not None and hasattr(ch, "char_id"):
                        chars_map[ch.char_id] = ch
                except Exception:
                    continue

        self.model.characters = chars_map
        self.model.GameMaster = chars_map.get("GameMaster")

    # ---------------------------------------------------------------------
    # Subscriptions
    # ---------------------------------------------------------------------

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

        self.event_bus.subscribe(Events.Character.CURRENT_CHANGED, self._on_character_current_changed, weak=False)

        self.event_bus.subscribe(Events.Model.GET_GAME_STATE, self._on_get_game_state, weak=False)
        self.event_bus.subscribe(Events.Server.SET_GAME_DATA, self._on_set_game_data, weak=False)
        self.event_bus.subscribe(Events.Model.ADD_TEMPORARY_SYSTEM_INFO, self._on_add_temporary_system_info, weak=False)
        self.event_bus.subscribe(Events.Model.PEEK_TEMPORARY_SYSTEM_INFOS, self._on_peek_temporary_system_infos, weak=False)

        self.event_bus.subscribe(Events.Model.GENERATE_RESPONSE, self._on_generate_response, weak=False)

        self.event_bus.subscribe(Events.Model.LOAD_HISTORY, self._on_load_history, weak=False)
        self.event_bus.subscribe(Events.Model.LOAD_MORE_HISTORY, self._on_load_more_history, weak=False)
        self.event_bus.subscribe(Events.Model.GET_DEBUG_INFO, self._on_get_debug_info, weak=False)

        self.event_bus.subscribe(Events.Model.GET_CURRENT_CONTEXT_TOKENS, self._on_get_current_context_tokens, weak=False)
        self.event_bus.subscribe(Events.Model.CALCULATE_COST, self._on_calculate_cost, weak=False)

        self.event_bus.subscribe(Events.Model.RELOAD_PROMPTS_ASYNC, self._on_reload_prompts_async, weak=False)

    # ---------------------------------------------------------------------
    # Model settings
    # ---------------------------------------------------------------------

    def _on_setting_changed(self, event: Event):
        key = (event.data or {}).get("key")
        value = (event.data or {}).get("value")

        if key == "CHARACTER":
            self.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": str(value or "")})
            # обновим legacy ссылки
            self._refresh_chat_model_character_refs()
            return

        if hasattr(self.model, "cfg") and self.model.cfg:
            self.model.cfg.apply_setting(key, value)

    def _on_character_current_changed(self, event: Event):
        self._refresh_chat_model_character_refs()

    # ---------------------------------------------------------------------
    # Game state / temp system infos
    # ---------------------------------------------------------------------

    def _on_set_game_data(self, event: Event):
        self.game_state.update_from_event_data(event.data or {})

    def _on_add_temporary_system_info(self, event: Event):
        content = (event.data or {}).get("content", "")
        if not content:
            return False
        self._temporary_system_infos.append({"role": "system", "content": str(content)})
        return True

    def _on_peek_temporary_system_infos(self, event: Event):
        return list(self._temporary_system_infos)

    def _on_get_game_state(self, event: Event):
        return self.game_state.to_prompt_dict()

    # ---------------------------------------------------------------------
    # History UI
    # ---------------------------------------------------------------------

    def _normalize_character_id_from_data(self, data: dict) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        cid = data.get("character_id") or data.get("char_id") or data.get("character")
        return str(cid) if cid else None
    
    def _normalize_participants(self, participants: Any) -> list[str]:
        if not participants:
            return []
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split(",") if p.strip()]
        if not isinstance(participants, list):
            return []

        all_ids_res = self.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
        all_ids = all_ids_res[0] if all_ids_res and isinstance(all_ids_res[0], list) else []
        id_set = set(str(x) for x in all_ids)

        out: list[str] = []
        seen = set()

        for p in participants:
            s = str(p or "").strip()
            if not s:
                continue
            if s.lower() == "player":
                s = "Player"

            if s != "Player" and s not in id_set:
                # case-insensitive match
                sl = s.lower()
                match = None
                for cid in id_set:
                    if cid.lower() == sl:
                        match = cid
                        break
                if match is None:
                    continue
                s = match

            if s in seen:
                continue
            out.append(s)
            seen.add(s)

        return out


    def _make_message_id(self, prefix: str, base: str | None = None) -> str:
        base_s = str(base or "").strip()
        if base_s:
            return f"{prefix}:{base_s}"
        import uuid
        return f"{prefix}:{uuid.uuid4().hex}"


    def _has_message_id_recent(self, messages: list[dict], message_id: str, tail: int = 250) -> bool:
        if not message_id or not isinstance(messages, list):
            return False
        for m in messages[-tail:]:
            if isinstance(m, dict) and str(m.get("message_id") or "") == message_id:
                return True
        return False


    def _append_history_message(self, ch_ref, msg: dict) -> bool:
        if ch_ref is None or not isinstance(msg, dict):
            return False

        try:
            history_data = ch_ref.history_manager.load_history()
            messages = history_data.get("messages", []) or []
            if not isinstance(messages, list):
                messages = []

            mid = str(msg.get("message_id") or "")
            if mid and self._has_message_id_recent(messages, mid):
                return False

            messages.append(msg)
            ch_ref.save_character_state_to_history(messages)
            return True
        except Exception as e:
            logger.warning(f"[ModelController] append_history_message failed for {getattr(ch_ref,'char_id','?')}: {e}", exc_info=True)
            return False


    def _fanout_event(self, event_msg: dict, participants: list[str]) -> None:
        if not isinstance(event_msg, dict):
            return

        speaker = str(event_msg.get("speaker") or "")
        if not speaker:
            return

        for pid in participants:
            if not pid or pid == "Player":
                continue

            ch = self._get_character_ref(pid)
            if ch is None:
                continue

            local = dict(event_msg)

            # локальная роль относительно владельца файла
            local["role"] = "assistant" if pid == speaker else "user"

            # для совместимости: пусть "sender" дублирует speaker
            local.setdefault("sender", speaker)

            self._append_history_message(ch, local)


    def _build_user_event_message(
        self,
        *,
        speaker: str,
        target: str,
        participants: list[str],
        user_input: str,
        image_data: list[Any],
        event_type: str,
        base_id: str | None,
    ) -> dict | None:
        has_text = bool(str(user_input or "").strip())
        has_images = bool(image_data)

        if not has_text and not has_images:
            return None

        chunks: list[dict] = []

        if has_text:
            chunks.append({"type": "text", "text": str(user_input)})

        for img in image_data or []:
            if isinstance(img, bytes):
                b64 = base64.b64encode(img).decode("utf-8")
            else:
                b64 = str(img)
            chunks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })

        return {
            "message_id": self._make_message_id("in", base_id),
            "role": "user",  # будет перезаписано в fanout локально, но пусть тут остаётся "user"
            "speaker": speaker,
            "sender": speaker,
            "target": target,
            "participants": list(participants),
            "event_type": event_type,
            "time": datetime.datetime.now().strftime("%d.%m.%Y_%H.%M"),
            "content": chunks,
        }


    def _build_assistant_event_message(
        self,
        *,
        speaker: str,
        target: str,
        participants: list[str],
        final_text: str,
        event_type: str,
        base_id: str | None,
    ) -> dict:
        return {
            "message_id": self._make_message_id("out", base_id),
            "role": "assistant",  # будет перезаписано в fanout локально
            "speaker": speaker,
            "sender": speaker,
            "target": target,
            "participants": list(participants),
            "event_type": event_type,
            "time": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            "content": final_text,
        }


    def _ui_wrap_history_message(self, msg: dict) -> dict | None:
        """
        Превращает сохранённый history-msg в формат, который message_renderer умеет рисовать:
        - роль для UI: Player -> user (жёлтый), иначе -> assistant (розовый)
        - meta speaker-label: "Name → Target" если target != Player
        """
        if not isinstance(msg, dict):
            return None

        role = str(msg.get("role") or "")
        if role not in ("user", "assistant", "system"):
            return None

        # фильтр пустых user
        if role == "user":
            content = msg.get("content")
            if not self._has_visible_user_text(content):
                return None

        speaker = str(msg.get("speaker") or msg.get("sender") or "")
        target = str(msg.get("target") or "")

        # UI роль по speaker, а не по role из истории
        ui_role = "user" if speaker == "Player" else ("assistant" if role in ("user", "assistant") else role)

        mm = dict(msg)
        mm["role"] = ui_role

        # meta label
        speaker_label = ""
        if speaker and speaker != "Player":
            speaker_label = speaker
            if target and target != "Player":
                speaker_label = f"{speaker_label} → {target}"

        if speaker_label:
            content = mm.get("content")
            if isinstance(content, list):
                mm["content"] = [{"type": "meta", "speaker": speaker_label}] + content
            elif isinstance(content, str):
                mm["content"] = [{"type": "meta", "speaker": speaker_label}, {"type": "text", "text": content}]
            else:
                mm["content"] = [{"type": "meta", "speaker": speaker_label}, {"type": "text", "text": str(content)}]

        return mm


    def _on_load_history(self, event: Event):
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False

        ch = self._get_current_character_ref()
        if not ch:
            self.event_bus.emit("history_loaded", {"messages": [], "total_messages": 0, "loaded_offset": 0})
            return

        chat_history = ch.load_history()
        all_messages = chat_history.get("messages", []) or []
        logger.info(f"[ModelController._on_load_history] Загружено {len(all_messages)} raw сообщений из истории")
        if all_messages:
            for i, msg in enumerate(all_messages[-3:]):  # последние 3
                logger.info(f"[ModelController._on_load_history] msg[{i}]: role={msg.get('role')}, content={str(msg.get('content'))[:60]}")
        if not isinstance(all_messages, list):
            all_messages = []

        prepared = self.ui_projector.project_for_ui(all_messages)
        logger.info(f"[ModelController._on_load_history] После project_for_ui: {len(prepared)} сообщений")
        if prepared:
            for i, msg in enumerate(prepared[-3:]):  # последние 3 после проекции
                logger.info(f"[ModelController._on_load_history] projected[{i}]: role={msg.get('role')}, content={str(msg.get('content'))[:60]}")

        self.total_messages_in_history = len(prepared)

        max_display_messages = int(self.settings.get("MAX_CHAT_HISTORY_DISPLAY", 200))
        start_index = max(0, self.total_messages_in_history - max_display_messages)
        messages_to_load = prepared[start_index:]

        self.loaded_messages_offset = len(messages_to_load)

        self.event_bus.emit("history_loaded", {
            "messages": messages_to_load,
            "total_messages": self.total_messages_in_history,
            "loaded_offset": self.loaded_messages_offset
        })


    # def _on_load_more_history(self, event: Event):
    #     if self.loaded_messages_offset >= self.total_messages_in_history:
    #         return

    #     data = event.data or {}
    #     requested_cid = self._normalize_character_id_from_data(data)

    #     self.loading_more_history = True
    #     try:
    #         ch = self._get_character_ref(requested_cid) if requested_cid else self._get_current_character_ref()
    #         if not ch:
    #             return

    #         chat_history = ch.load_history()
    #         all_messages = chat_history.get("messages", []) or []

    #         end_index = self.total_messages_in_history - self.loaded_messages_offset
    #         start_index = max(0, end_index - self.lazy_load_batch_size)
    #         messages_to_prepend = all_messages[start_index:end_index]

    #         if messages_to_prepend:
    #             self.loaded_messages_offset += len(messages_to_prepend)
    #             self.event_bus.emit("more_history_loaded", {
    #                 "messages": messages_to_prepend,
    #                 "loaded_offset": self.loaded_messages_offset
    #             })
    #     finally:
    #         self.loading_more_history = False

    def _on_load_more_history(self, event: Event):
        if self.loaded_messages_offset >= self.total_messages_in_history:
            return

        self.loading_more_history = True
        try:
            ch = self._get_current_character_ref()
            if not ch:
                return

            chat_history = ch.load_history()
            all_messages = chat_history.get("messages", []) or []
            if not isinstance(all_messages, list):
                all_messages = []

            prepared = self.ui_projector.project_for_ui(all_messages)
            self.total_messages_in_history = len(prepared)

            end_index = self.total_messages_in_history - self.loaded_messages_offset
            start_index = max(0, end_index - self.lazy_load_batch_size)
            messages_to_prepend = prepared[start_index:end_index]

            if messages_to_prepend:
                self.loaded_messages_offset += len(messages_to_prepend)
                self.event_bus.emit("more_history_loaded", {
                    "messages": messages_to_prepend,
                    "loaded_offset": self.loaded_messages_offset
                })
        finally:
            self.loading_more_history = False

    def _on_get_debug_info(self, event: Event):
        data = event.data or {}
        requested_cid = self._normalize_character_id_from_data(data)
        ch = self._get_character_ref(requested_cid) if requested_cid else self._get_current_character_ref()

        if ch and hasattr(ch, "current_variables_string"):
            return ch.current_variables_string()
        return "Debug info not available"

    # ---------------------------------------------------------------------
    # Token counting / cost
    # ---------------------------------------------------------------------

    def _cache_base_prompt(self, character_id: str, event_type: str, messages: list[dict]) -> None:
        if not character_id or not isinstance(messages, list):
            return

        safe = copy.deepcopy(messages)
        if safe and isinstance(safe[-1], dict) and safe[-1].get("role") == "user":
            safe = safe[:-1]

        self._base_prompt_cache[(character_id, event_type)] = safe

    def _on_get_current_context_tokens(self, event: Event):
        cid = self._get_current_character_id()
        if not cid:
            return 0

        event_type = "chat"
        base = self._base_prompt_cache.get((cid, event_type))
        if not base:
            return 0

        user_input_res = self.event_bus.emit_and_wait(Events.Speech.GET_USER_INPUT, timeout=1.0)
        user_text = user_input_res[0] if user_input_res else ""

        try:
            extra_infos_res = self.event_bus.emit_and_wait(Events.Model.PEEK_TEMPORARY_SYSTEM_INFOS, timeout=1.0)
            extra_infos = extra_infos_res[0] if extra_infos_res and isinstance(extra_infos_res[0], list) else []
        except Exception:
            extra_infos = []

        messages = list(base)
        if extra_infos:
            messages.extend([x for x in extra_infos if isinstance(x, dict)])

        messages = self.context_counter.with_user_text(messages, str(user_text or ""))
        return self.context_counter.count_tokens(messages)

    def _on_calculate_cost(self, event: Event):
        tokens = self._on_get_current_context_tokens(event)
        cfg = getattr(self.model, "cfg", None)
        if not cfg:
            return 0.0
        try:
            return (float(tokens) / 1000.0) * float(cfg.token_cost_input)
        except Exception:
            return 0.0

    # ---------------------------------------------------------------------
    # Generation
    # ---------------------------------------------------------------------

    def _extract_think_blocks(self, text: str) -> tuple[str, str]:
        """
        Extracts <think>...</think> blocks.
        Returns: (visible_text_without_think, think_text_joined)

        - Think blocks SHOULD NOT be stored in history.
        - Think blocks SHOULD NOT be sent to voiceover.
        """
        if not isinstance(text, str) or not text:
            return ("" if text is None else str(text), "")

        # Capture content inside <think ...>...</think>
        # Keep it permissive (attrs allowed), DOTALL for multiline.
        pattern = re.compile(r"<think\b[^>]*>(.*?)</think\s*>", flags=re.IGNORECASE | re.DOTALL)
        think_parts: list[str] = []
        for m in pattern.finditer(text):
            part = m.group(1)
            if part is None:
                continue
            part_s = str(part).strip()
            if part_s:
                think_parts.append(part_s)

        visible = pattern.sub("", text)
        # Also drop any stray <think> or </think> tags (unbalanced)
        visible = re.sub(r"</?think\b[^>]*>", "", visible, flags=re.IGNORECASE)

        # Light cleanup (avoid accidental extra blank lines)
        visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
        think_text = "\n\n".join(think_parts).strip()
        return visible, think_text

    def _on_generate_response(self, event: Event):
        data = event.data or {}

        user_input = data.get("user_input", "") or ""
        system_input = data.get("system_input", "") or ""
        image_data = data.get("image_data", []) or []
        stream_callback = data.get("stream_callback", None)
        event_type = (data.get("event_type") or "chat") or "chat"

        sender = str(data.get("sender") or "Player")
        participants = data.get("participants") or []

        preset_id_override = data.get("preset_id", None)
        character_id_override = self._normalize_character_id_from_data(data)

        req_id = str(data.get("req_id") or "") or None
        task_uid = str(data.get("message_id") or "") or None

        policy_dict = data.get("policy")
        policy = RequestPolicy.from_dict(policy_dict) if isinstance(policy_dict, dict) else resolve_policy(model_event_type=str(event_type or "chat"))

        char = None
        if character_id_override:
            char = self._get_character_ref(str(character_id_override))
            if char is None:
                logger.error(f"GENERATE_RESPONSE: неизвестный character_id='{character_id_override}' (нет фолбэка на current).")
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                    "error": _("Неизвестный персонаж.", "Unknown character.")
                })
                return None
        else:
            char = self._get_current_character_ref()

        if not char:
            logger.error("Генерация невозможна: персонаж не выбран.")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": _("Персонаж не выбран.", "Character not selected.")
            })
            return None

        char_id = getattr(char, "char_id", "") or ""
        char_name = getattr(char, "name", "") or ""
        preset_id = preset_id_override  # Initialize early for capability resolution

        if event_type == "compress":
            messages = []
            if system_input:
                messages.append({"role": "system", "content": system_input})

            self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
                "character_id": char_id,
                "character_name": char_name or char_id or "Мита",
            })

            try:
                return self.model.generate(messages, stream_callback=None, preset_id=preset_id)
            except Exception as e:
                logger.error(f"Ошибка при сжатии истории: {e}", exc_info=True)
                return None

        game_state = self.game_state.to_prompt_dict()

        extra_system_infos = list(self._temporary_system_infos or [])
        self._temporary_system_infos.clear()

        cfg = getattr(self.model, "cfg", None)

        def _cfg_get(attr: str, default):
            if cfg is not None and hasattr(cfg, attr):
                return getattr(cfg, attr)
            return getattr(self.model, attr, default)

        screen_quality = self.settings.get("SCREEN_CAPTURE_QUALITY", 75)
        screen_quality = int(screen_quality) if str(screen_quality) != "" else 75

        image_quality_cfg = {
            "enabled": bool(_cfg_get("image_quality_reduction_enabled", False)),
            "start_index": int(_cfg_get("image_quality_reduction_start_index", 25)),
            "use_percentage": bool(_cfg_get("image_quality_reduction_use_percentage", False)),
            "min_quality": int(_cfg_get("image_quality_reduction_min_quality", 30)),
            "decrease_rate": int(_cfg_get("image_quality_reduction_decrease_rate", 5)),
            "screen_capture_quality": screen_quality,
        }

        separate_prompts = bool(self.settings.get("SEPARATE_PROMPTS", True))
        save_missed_history = bool(self.settings.get("SAVE_MISSED_HISTORY", True))
        memory_limit = int(_cfg_get("memory_limit", 40))
        is_game_master = (char_id == "GameMaster")
        disable_history_compression = bool(data.get("disable_history_compression", False))

        # Resolve capabilities from the effective preset for this request
        effective_capabilities = {}
        try:
            effective_preset = self.preset_resolver.resolve(preset_id)
            effective_capabilities = dict(getattr(effective_preset, "capabilities", {}) or {})
            logger.info(
                f"[ModelController] preset_id={preset_id!r} → "
                f"structured_output={effective_capabilities.get('structured_output')} "
                f"mode={effective_capabilities.get('structured_output_mode', 'json_schema')}"
            )
        except Exception as e:
            logger.warning(f"[ModelController] Failed to resolve preset capabilities: {e}")

        # Determine tools state and inject description into capabilities for prompt injection
        _tools_on = bool(self.settings.get("TOOLS_ON", True))
        _tools_mode = str(self.settings.get("TOOLS_MODE", "native"))
        if _tools_mode == "off":
            _tools_on = False
        _enabled_tools = [n for n in _ALL_TOOLS_LIST if self.settings.get(f"TOOL_ENABLED_{n}", True)]
        if not _enabled_tools:
            _tools_on = False

        if _tools_on and effective_capabilities.get("structured_output", False):
            try:
                schema = self.model.tool_manager._filtered_schema(_enabled_tools)
                effective_capabilities["tools_prompt"] = _render_tools_for_prompt(schema)
            except Exception as e:
                logger.warning(f"[ModelController] Failed to build tools prompt: {e}")
                _tools_on = False

        try:
            prompt_res = self.event_bus.emit_and_wait(
                Events.Prompt.BUILD_PROMPT,
                {
                    "character_id": char_id,
                    "character_ref": char,
                    "event_type": event_type,
                    "user_input": user_input,
                    "system_input": system_input,
                    "image_data": image_data,
                    "memory_limit": memory_limit,
                    "is_game_master": is_game_master,
                    "save_missed_history": save_missed_history,
                    "image_quality": image_quality_cfg,
                    "separate_prompts": separate_prompts,
                    "extra_system_infos": extra_system_infos,
                    "game_state": game_state,
                    "disable_history_compression": disable_history_compression,
                    "sender": sender,
                    "participants": participants,
                    "policy": policy.to_dict(),
                    "capabilities": effective_capabilities,
                },
                timeout=10.0
            )
        except Exception as e:
            logger.error(f"Ошибка при BUILD_PROMPT: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": _("Не удалось сформировать промпт.", "Failed to build prompt.")
            })
            return None

        if not prompt_res or not isinstance(prompt_res[0], dict):
            logger.error("BUILD_PROMPT не вернул валидный результат")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": _("Не удалось сформировать промпт.", "Failed to build prompt.")
            })
            return None

        prompt_data = prompt_res[0]
        combined_messages = prompt_data.get("messages", []) or []

        if event_type == "chat":
            self._cache_base_prompt(char_id, "chat", combined_messages)

        preset_id: Optional[int] = None

        def _is_current_label(label: str | None) -> bool:
            s = str(label or "").strip()
            return s in ("", "Current", "Текущий", _("Текущий", "Current"))

        def _resolve_label_to_preset_id(label: str | None) -> Optional[int]:
            if label is None or _is_current_label(label):
                return None
            s = str(label).strip()
            try:
                return int(s)
            except ValueError:
                pass
            try:
                return self.preset_resolver.resolve_preset_id_by_name(s)
            except Exception:
                return None

        def _get_char_provider_label(cid: str, cname: str) -> str:
            v = self.settings.get(f"CHAR_PROVIDER_{cid}", None)
            if v is None and cname:
                v = self.settings.get(f"CHAR_PROVIDER_{cname}", None)
            return str(v if v is not None else "Current")

        if event_type == "react":
            lvl = int(getattr(policy, "react_level", None) or 1)

            if lvl == 2:
                label = str(self.settings.get("REACT_PROVIDER_L2", self.settings.get("REACT_PROVIDER", _("Текущий", "Current"))))
            else:
                label = str(self.settings.get("REACT_PROVIDER_L1", self.settings.get("REACT_PROVIDER", _("Текущий", "Current"))))

            preset_id = _resolve_label_to_preset_id(label)
            if preset_id is None:
                preset_id = _resolve_label_to_preset_id(_get_char_provider_label(char_id, char_name))

            logger.info(f"[ModelController] react policy: level={lvl}, provider_label='{label}', preset_id={preset_id}")
        else:
            preset_id = _resolve_label_to_preset_id(_get_char_provider_label(char_id, char_name))

        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character_id": char_id,
            "character_name": char_name or char_id or "Мита",
        })

        is_structured_output = effective_capabilities.get("structured_output", False)

        try:
            use_stream_cb = stream_callback if policy.allow_streaming else None
            raw_text = self.model.generate(combined_messages, stream_callback=use_stream_cb, preset_id=preset_id)

            if not raw_text:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                    "error": _("Не удалось получить ответ.", "Text generation failed.")
                })
                return None

            # Strip <think> blocks BEFORE any downstream processing (commands, voiceover, history)
            visible_raw, think_text = self._extract_think_blocks(str(raw_text))

            # --- Structured Output path ---
            if is_structured_output:
                return self._process_structured_output(
                    visible_raw=visible_raw,
                    think_text=think_text,
                    char=char,
                    char_id=char_id,
                    char_name=char_name,
                    data=data,
                    policy=policy,
                    sender=sender,
                    participants=participants,
                    user_input=user_input,
                    image_data=image_data,
                    req_id=req_id,
                    task_uid=task_uid,
                    event_type=event_type,
                    combined_messages=combined_messages,
                    preset_id=preset_id,
                    tools_on=_tools_on,
                    tool_depth=0,
                )

            # --- Legacy (tag-based) path ---
            processed = char.process_response_nlp_commands(visible_raw, self.settings.get("SAVE_MISSED_MEMORY", False))

            targets: list[str] = []
            if hasattr(char, "consume_pending_targets"):
                try:
                    targets = char.consume_pending_targets()
                except Exception:
                    targets = []
            target = targets[-1] if targets else "Player"

            final_text = processed
            if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
                final_text = re.sub(
                    r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                    "[Изображение]",
                    final_text
                )

            if policy.write_to_history:
                origin_message_id = str(data.get("origin_message_id") or "") or None

                self.event_writer.write_turn(
                    responder_character_id=char_id,
                    sender=sender,
                    participants=participants,
                    user_input=user_input,
                    image_data=image_data,
                    req_id=req_id,
                    origin_message_id=origin_message_id,
                    assistant_text=final_text,
                    assistant_target=target,
                    event_type=event_type,
                    task_uid=task_uid,
                )

            self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)

            voice_profile = None
            if hasattr(char, "to_voice_profile"):
                try:
                    voice_profile = char.to_voice_profile()
                except Exception:
                    voice_profile = None

            return {
                "text": final_text,
                "character_id": char_id,
                "voice_profile": voice_profile,
                "target": target,
                "targets": targets,
                "think": think_text or None,
            }

        except Exception as e:
            logger.error(f"Error during LLM generation/processing: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": str(e)})
            return None

    # ---------------------------------------------------------------------
    # Structured Output processing
    # ---------------------------------------------------------------------

    def _process_structured_output(
        self,
        visible_raw: str,
        think_text: str,
        char,
        char_id: str,
        char_name: str,
        data: dict,
        policy,
        sender: str,
        participants: list,
        user_input: str,
        image_data: list,
        req_id: str | None,
        task_uid: str | None,
        event_type: str,
        combined_messages: list | None = None,
        preset_id: int | None = None,
        tools_on: bool = False,
        tool_depth: int = 0,
    ) -> dict | None:
        """
        Process a structured JSON response from the LLM.
        Parses the JSON, applies global fields (behavior, memory),
        processes game tags, and returns the result dict with segments.
        """
        try:
            structured = parse_structured_response(visible_raw)
        except StructuredResponseParseError as e:
            logger.error(
                f"[ModelController] Failed to parse structured response for {char_id}: {e}. "
                f"Falling back to legacy processing."
            )
            # Fallback to legacy tag-based processing
            processed = char.process_response_nlp_commands(
                visible_raw, self.settings.get("SAVE_MISSED_MEMORY", False)
            )
            fallback_targets: list[str] = []
            if hasattr(char, "consume_pending_targets"):
                try:
                    fallback_targets = char.consume_pending_targets()
                except Exception:
                    fallback_targets = []
            fallback_target = fallback_targets[-1] if fallback_targets else "Player"

            voice_profile = None
            if hasattr(char, "to_voice_profile"):
                try:
                    voice_profile = char.to_voice_profile()
                except Exception:
                    voice_profile = None

            self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)
            return {
                "text": processed,
                "character_id": char_id,
                "voice_profile": voice_profile,
                "target": fallback_target,
                "targets": fallback_targets,
                "think": think_text or None,
            }

        # Apply structured response processing (behavior changes, memory, game tags)
        char.process_structured_response(
            structured,
            save_as_missed=self.settings.get("SAVE_MISSED_MEMORY", False),
        )

        # --- Tool call path ---
        if structured.tool_call and tools_on and tool_depth < 2:
            return self._handle_tool_call(
                structured=structured,
                think_text=think_text,
                char=char,
                char_id=char_id,
                char_name=char_name,
                data=data,
                policy=policy,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                req_id=req_id,
                task_uid=task_uid,
                event_type=event_type,
                combined_messages=combined_messages or [],
                preset_id=preset_id,
                tool_depth=tool_depth,
            )

        # Extract reasoning from structured response (if model used the reasoning field)
        if structured.reasoning:
            schema_reasoning = structured.reasoning.strip()
            if schema_reasoning:
                if think_text:
                    think_text = think_text + "\n\n" + schema_reasoning
                else:
                    think_text = schema_reasoning

        # Build the result dict with segments
        result_dict = structured_response_to_result_dict(structured)
        # Remove reasoning from debug display — it's shown as a think block
        result_dict.pop("reasoning", None)
        final_text = result_dict["response"]

        targets: list[str] = []
        if hasattr(char, "consume_pending_targets"):
            try:
                targets = char.consume_pending_targets()
            except Exception:
                targets = []
        target = targets[-1] if targets else "Player"

        if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
            final_text = re.sub(
                r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                "[Изображение]",
                final_text,
            )

        if policy.write_to_history:
            origin_message_id = str(data.get("origin_message_id") or "") or None
            self.event_writer.write_turn(
                responder_character_id=char_id,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                req_id=req_id,
                origin_message_id=origin_message_id,
                assistant_text=final_text,
                assistant_target=target,
                event_type=event_type,
                task_uid=task_uid,
                structured_data=result_dict,
            )

        self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)

        voice_profile = None
        if hasattr(char, "to_voice_profile"):
            try:
                voice_profile = char.to_voice_profile()
            except Exception:
                voice_profile = None

        return {
            "text": final_text,
            "character_id": char_id,
            "voice_profile": voice_profile,
            "target": target,
            "targets": targets,
            "think": think_text or None,
            "structured": result_dict,
        }

    # ---------------------------------------------------------------------
    # Tool call handler (structured output tools)
    # ---------------------------------------------------------------------

    def _handle_tool_call(
        self,
        structured,
        think_text: str,
        char,
        char_id: str,
        char_name: str,
        data: dict,
        policy,
        sender: str,
        participants: list,
        user_input: str,
        image_data: list,
        req_id: str | None,
        task_uid: str | None,
        event_type: str,
        combined_messages: list,
        preset_id: int | None,
        tool_depth: int,
    ) -> dict | None:
        """
        Handle a tool_call from a structured response:
        1. Emit first response to UI.
        2. Execute the tool.
        3. Append tool result as system message.
        4. Make a second LLM call for the final answer.
        """
        from utils.structured_response_parser import structured_response_to_result_dict

        tool_name = structured.tool_call.name
        tool_args = structured.tool_call.args or {}

        # Build first response result dict
        result_dict = structured_response_to_result_dict(structured)
        result_dict.pop("reasoning", None)
        first_text = result_dict.get("response", "")

        targets: list[str] = []
        if hasattr(char, "consume_pending_targets"):
            try:
                targets = char.consume_pending_targets()
            except Exception:
                targets = []
        target = targets[-1] if targets else "Player"

        voice_profile = None
        if hasattr(char, "to_voice_profile"):
            try:
                voice_profile = char.to_voice_profile()
            except Exception:
                voice_profile = None

        # Write first turn to history
        if policy.write_to_history:
            origin_message_id = str(data.get("origin_message_id") or "") or None
            self.event_writer.write_turn(
                responder_character_id=char_id,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                req_id=req_id,
                origin_message_id=origin_message_id,
                assistant_text=first_text,
                assistant_target=target,
                event_type=event_type,
                task_uid=task_uid,
                structured_data=result_dict,
            )

        # Emit first response to UI (shows "I'll check that" message)
        self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)
        self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
            "role": "assistant",
            "response": first_text if first_text else "...",
            "is_initial": False,
            "emotion": "",
            "character_id": char_id or "",
            "character_name": char_name or "",
            "speaker_name": char_name or "",
            "target": target,
            "targets": targets,
            "structured_data": result_dict,
        }, sync=True)

        # Emit tool executing indicator for UI
        self.event_bus.emit(Events.Model.ON_TOOL_EXECUTING, {
            "tool_name": tool_name,
            "character_id": char_id,
        })

        # Execute the tool
        logger.info(f"[ModelController] Executing tool '{tool_name}' with args: {tool_args}")
        try:
            tool_result = self.model.tool_manager.run(tool_name, tool_args)
        except Exception as e:
            tool_result = f"[Tool error: {e}]"
            logger.error(f"[ModelController] Tool '{tool_name}' failed: {e}", exc_info=True)

        self.event_bus.emit(Events.Model.ON_TOOL_DONE, {
            "tool_name": tool_name,
            "character_id": char_id,
        })
        self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
            "role": "system",
            "response": f"[Tool: {tool_name}]\n{tool_result}",
            "is_initial": False,
            "emotion": "",
            "character_id": "",
            "character_name": "",
            "speaker_name": "",
        }, sync=True)

        # Build messages for second call: append first response JSON + tool result
        combined_messages_v2 = list(combined_messages)
        try:
            first_response_json = structured.model_dump_json(exclude_none=True)
        except Exception:
            first_response_json = first_text
        combined_messages_v2.append({"role": "assistant", "content": first_response_json})
        combined_messages_v2.append({
            "role": "system",
            "content": f"[Tool result: {tool_name}]\n{tool_result}"
        })

        # Second LLM call
        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character_id": char_id,
            "character_name": char_name or char_id or "Мита",
        })

        raw_text_2 = self.model.generate(combined_messages_v2, preset_id=preset_id)

        if not raw_text_2:
            logger.error(f"[ModelController] Second LLM call after tool '{tool_name}' returned empty.")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": _("Не удалось получить ответ после инструмента.", "Failed to get response after tool.")
            })
            # Return first response as fallback
            return {
                "text": first_text,
                "character_id": char_id,
                "voice_profile": voice_profile,
                "target": target,
                "targets": targets,
                "think": think_text or None,
                "structured": result_dict,
            }

        visible_raw_2, think_text_2 = self._extract_think_blocks(str(raw_text_2))

        combined_think = think_text
        if think_text_2:
            combined_think = (combined_think + "\n\n" + think_text_2) if combined_think else think_text_2

        # Process second response (depth+1 prevents infinite tool loops)
        # user_input is empty so the user message is not written to history again
        return self._process_structured_output(
            visible_raw=visible_raw_2,
            think_text=combined_think or "",
            char=char,
            char_id=char_id,
            char_name=char_name,
            data=data,
            policy=policy,
            sender=sender,
            participants=participants,
            user_input="",
            image_data=[],
            req_id=req_id,
            task_uid=task_uid,
            event_type=event_type,
            combined_messages=combined_messages_v2,
            preset_id=preset_id,
            tools_on=True,
            tool_depth=tool_depth + 1,
        )

    # ---------------------------------------------------------------------
    # Reload prompts
    # ---------------------------------------------------------------------

    def _on_reload_prompts_async(self, event: Event):
        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            "coroutine": self._async_reload_prompts(),
            "callback": None
        })

    async def _async_reload_prompts(self):
        try:
            from utils.prompt_downloader import PromptDownloader
            import asyncio

            downloader = PromptDownloader()
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, downloader.download_and_replace_prompts)

            if success:
                cid = self._get_current_character_id()
                if cid:
                    self.event_bus.emit(Events.Character.RELOAD_PROMPTS, {"character_id": cid})
                self.event_bus.emit("reload_prompts_success")
            else:
                self.event_bus.emit("reload_prompts_failed", {"error": "Download failed"})
        except Exception as e:
            logger.error(f"Ошибка при обновлении промптов: {e}", exc_info=True)
            self.event_bus.emit("reload_prompts_failed", {"error": str(e)})

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------


    def _has_visible_user_text(self, content: Any) -> bool:
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for it in content:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "text":
                    txt = it.get("text")
                    if txt is None:
                        txt = it.get("content", "")
                    if str(txt or "").strip():
                        return True
                if it.get("type") == "image_url":
                    return True
        return False

