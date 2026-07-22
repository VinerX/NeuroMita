# src/controllers/model_controller.py
from __future__ import annotations

import base64
import json
import datetime
import re
import copy
import threading
from typing import Optional, Any

from handlers.chat_handler import ChatModel
from utils import _, redact_image_payloads
from core.character_locks import character_generation_lock, character_lock
from core.events import Event, EventDelivery, Events, get_event_bus
from core.executors import Pools, executors
from core.services import services, use
from main_logger import logger
from services.contracts import (
    CharacterRegistry,
    ChatGenerationRequest,
    ChatGenerationResult,
    GenerationService,
    ModelStateService,
    PromptBuildRequest,
    PromptBuilderService,
    UtilityGenerationRequest,
    UtilityGenerationResult,
    SettingsService,
)

from managers.api_preset_resolver import ApiPresetResolver
from managers.game_state_manager import GameState
from managers.context_counter import ContextCounter
from managers.conversation_event_writer import ConversationEventWriter
from managers.history_ui_projector import HistoryUiProjector
from managers.model_pricing_manager import ModelPricingManager, known_model_context_length
from core.request_policy import RequestPolicy, resolve_policy
from handlers.llm_providers.base import LLMUsage
from services.runtime_capabilities import runtime_capabilities
from utils.structured_response_parser import (
    parse_structured_response,
    structured_response_to_result_dict,
    StructuredResponseParseError,
)

_ALL_TOOLS_LIST = ["calculator", "web_search", "google_search", "web_reader", "memory_search", "reminder"]
_DEFAULT_TOOL_ENABLED = {
    "calculator": False,
    "web_search": False,
    "google_search": False,
    "web_reader": False,
    "memory_search": True,
    "reminder": True,
}

def _render_tools_for_prompt(schema: list) -> str:
    """Format tool JSON schema list into a human-readable prompt block."""
    if not schema:
        return ""
    lines = ["Available tools:"]
    for tool in schema:
        name = tool.get("name", "?")
        desc = tool.get("description", "")
        params_def = tool.get("parameters", {})
        props = params_def.get("properties", {})
        required_set = set(params_def.get("required", []))
        param_parts = []
        for pname, pdef in props.items():
            ptype = pdef.get("type", "any")
            pdesc = pdef.get("description", "")
            req_marker = " (REQUIRED)" if pname in required_set else ""
            param_parts.append(f"{pname}: {ptype}{req_marker}" + (f" — {pdesc}" if pdesc else ""))
        params_str = ", ".join(param_parts) if param_parts else "no parameters"
        lines.append(f"- {name}({params_str}) — {desc}")
    return "\n".join(lines)


_GRAPH_TAG_RE = re.compile(r"<graph>([\s\S]*?)</graph>", re.IGNORECASE)


def _strip_graph_tag(text: str) -> tuple[str, Optional[str]]:
    """Remove <graph>...</graph> from response, return (clean_text, json_str|None)."""
    m = _GRAPH_TAG_RE.search(text)
    if not m:
        return text, None
    json_str = m.group(1).strip()
    clean = _GRAPH_TAG_RE.sub("", text).strip()
    return clean, json_str


class ModelController(GenerationService, ModelStateService):
    """
    ModelController:
    - реализует GenerationService (generate_chat / generate_utility)
    - хранит game_state + temporary system infos
    - занимается UI-пейджингом истории (LOAD_HISTORY/LOAD_MORE_HISTORY)
    - считает токены/стоимость

    Персонажи:
    - НЕ создаются здесь
    - берутся через CharacterRegistry (единый источник истины)
    """

    def __init__(self, settings):
        self.settings = settings
        self._settings_service = use(SettingsService)
        self._settings_subscription = self._settings_service.subscribe(
            self._on_setting_changed
        )
        self.event_bus = get_event_bus()

        # UI history paging
        self.lazy_load_batch_size = 50
        self.total_messages_in_history = 0
        self.loaded_messages_offset = 0
        self.loading_more_history = False

        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
        self.model = ChatModel(settings)

        from managers.tools.builtin.memory_search import MemorySearchTool
        from managers.tools.builtin.reminder_tool import ReminderTool
        self.model.tool_manager.register(MemorySearchTool(settings=self.settings))
        self.model.tool_manager.register(ReminderTool())

        self.context_counter = ContextCounter(encoding_model="gpt-4o-mini")
        self.model_pricing_manager = ModelPricingManager()
        self._base_prompt_cache: dict[tuple[str, str], list[dict]] = {}
        self._last_token_stats: dict[str, Any] = {}

        self.game_state = GameState()
        self._temporary_system_infos: dict[str, list[dict]] = {}
        self._temporary_system_infos_lock = threading.Lock()

        self.event_writer = ConversationEventWriter(character_ref_resolver=self._get_character_ref)
        self.ui_projector = HistoryUiProjector(resolve_name=lambda cid: str(getattr(self._get_character_ref(cid), "name", "") or cid))

        from handlers.image_description_handler import ImageDescriptionHandler
        self.image_description_handler = ImageDescriptionHandler(model=self.model, settings=self.settings)

        self._refresh_chat_model_character_refs()

        services().register(GenerationService, self, replace=True)
        self._subscribe_to_events()

    # ---------------------------------------------------------------------
    # Character resolution via CharacterRegistry
    # ---------------------------------------------------------------------

    @property
    def _characters(self) -> CharacterRegistry:
        return use(CharacterRegistry)

    def _get_current_character_id(self) -> Optional[str]:
        return self._characters.current_id() or None

    def _get_character_ref(self, character_id: str):
        return self._characters.get(str(character_id)) if character_id else None

    def _get_current_character_ref(self):
        return self._characters.current()

    def _refresh_chat_model_character_refs(self):
        """Refresh only the active runtime; do not materialize every character."""
        current = self._characters.current()
        self.model.current_character = current
        if current is not None and hasattr(current, "char_id"):
            self.model.characters = {str(current.char_id): current}
            self.model.GameMaster = current if str(current.char_id) == "GameMaster" else None
        else:
            self.model.characters = {}
            self.model.GameMaster = None

    # ---------------------------------------------------------------------
    # Subscriptions
    # ---------------------------------------------------------------------

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Character.CURRENT_CHANGED, self._on_character_current_changed, weak=False)

        self.event_bus.subscribe(Events.Server.SET_GAME_DATA, self._on_set_game_data, weak=False)
        self.event_bus.subscribe(Events.Model.ADD_TEMPORARY_SYSTEM_INFO, self._on_add_temporary_system_info, weak=False)
        self.event_bus.subscribe(Events.Model.PEEK_TEMPORARY_SYSTEM_INFOS, self._on_peek_temporary_system_infos, weak=False)

        self.event_bus.subscribe(Events.Model.LOAD_HISTORY, self._on_load_history, weak=False)
        self.event_bus.subscribe(Events.Model.LOAD_MORE_HISTORY, self._on_load_more_history, weak=False)

        self.event_bus.subscribe(Events.Model.CALCULATE_COST, self._on_calculate_cost, weak=False)

        self.event_bus.subscribe(Events.Model.RELOAD_PROMPTS_ASYNC, self._on_reload_prompts_async, weak=False)

    # ---------------------------------------------------------------------
    # Model settings
    # ---------------------------------------------------------------------

    def _on_setting_changed(self, change):
        key = change.key
        value = change.value

        if key == "CHARACTER":
            self.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": str(value or "")})
            # обновим legacy ссылки
            self._refresh_chat_model_character_refs()
            return

        if hasattr(self.model, "cfg") and self.model.cfg:
            self.model.cfg.apply_setting(key, value)

    def shutdown(self) -> None:
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        self.model_pricing_manager.close()
        self.model.close()

    def _on_character_current_changed(self, event: Event):
        self._refresh_chat_model_character_refs()
        self._last_token_stats = {}

    # ---------------------------------------------------------------------
    # Game state / temp system infos
    # ---------------------------------------------------------------------

    def _on_set_game_data(self, event: Event):
        self.game_state.update_from_event_data(event.data or {})

    def _on_add_temporary_system_info(self, event: Event):
        data = event.data or {}
        content = data.get("content", "")
        if not content:
            return False
        character_id = str(data.get("character_id") or self._get_current_character_id() or "")
        if not character_id:
            return False
        with self._temporary_system_infos_lock:
            self._temporary_system_infos.setdefault(character_id, []).append(
                {"role": "system", "content": str(content)}
            )
        return True

    def _on_peek_temporary_system_infos(self, event: Event):
        data = event.data or {}
        character_id = str(data.get("character_id") or self._get_current_character_id() or "")
        with self._temporary_system_infos_lock:
            return list(self._temporary_system_infos.get(character_id, ()))

    def _consume_temporary_system_infos(self, character_id: str, reserved: list[dict]) -> None:
        if not character_id or not reserved:
            return
        with self._temporary_system_infos_lock:
            current = list(self._temporary_system_infos.get(character_id, ()))
            if not current:
                return
            for used in reserved:
                for index, candidate in enumerate(current):
                    if candidate is used or candidate == used:
                        current.pop(index)
                        break
            if current:
                self._temporary_system_infos[character_id] = current
            else:
                self._temporary_system_infos.pop(character_id, None)

    def _on_get_game_state(self, event: Event):
        return self.game_state.to_prompt_dict()

    def _remote_only_structured_segment_fields(self) -> list[str]:
        capabilities = runtime_capabilities(settings=self.settings)
        return list(capabilities.structured_segment_exclude_fields)

    @staticmethod
    def _sanitize_structured_segment_fields(structured, capabilities: dict) -> None:
        excluded = {
            str(name).strip()
            for name in (capabilities or {}).get("structured_segment_exclude_fields", ())
            if str(name).strip()
        }
        if not excluded:
            return

        for segment in getattr(structured, "segments", ()) or ():
            for field_name in excluded:
                if not hasattr(segment, field_name):
                    continue
                current = getattr(segment, field_name, None)
                setattr(segment, field_name, [] if isinstance(current, list) else None)

    def _summarize_image_data_for_capture(self, image_data: Any) -> dict[str, Any]:
        items = image_data if isinstance(image_data, list) else []
        summary_items: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            if isinstance(item, str):
                summary_items.append({
                    "index": idx,
                    "kind": "str",
                    "chars": len(item),
                    "preview": item[:80],
                })
                continue
            if isinstance(item, dict):
                summary_items.append({
                    "index": idx,
                    "kind": "dict",
                    "keys": sorted(str(k) for k in item.keys()),
                    "type": str(item.get("type") or ""),
                    "mime_type": str(item.get("mime_type") or item.get("mimeType") or ""),
                    "chars": len(str(item.get("data") or item.get("image") or "")),
                })
                continue
            summary_items.append({
                "index": idx,
                "kind": type(item).__name__,
                "repr": repr(item)[:120],
            })
        return {
            "count": len(items),
            "items": summary_items,
        }

    def _capture_generation_input(
        self,
        *,
        request: ChatGenerationRequest,
        char_id: str,
        char_name: str,
        policy: RequestPolicy,
        prompt_request: PromptBuildRequest,
        original_image_data: Any,
        image_data_after_processing: Any,
        image_descriptions: dict[str, str] | None,
    ) -> None:
        try:
            from managers.generation_input_collector import GenerationInputCollector

            collector = GenerationInputCollector.instance
            if collector is None:
                collector = GenerationInputCollector()
                GenerationInputCollector.instance = collector
            if not collector.is_enabled():
                return

            incoming = {
                "user_input": request.user_input,
                "system_input": request.system_input,
                "image_source": request.image_source,
                "event_type": request.event_type,
                "sender": request.sender,
                "participants": list(request.participants or []),
                "req_id": request.req_id,
                "origin_message_id": request.origin_message_id,
                "task_uid": request.task_uid,
                "streaming": (
                    request.stream_callback is not None
                    or request.stream_event_callback is not None
                ),
            }

            prompt_snapshot = {
                "event_type": prompt_request.event_type,
                "user_input": prompt_request.user_input,
                "system_input": prompt_request.system_input,
                "rag_context": prompt_request.rag_context,
                "hidden_user_context": prompt_request.hidden_user_context,
                "memory_limit": prompt_request.memory_limit,
                "is_game_master": prompt_request.is_game_master,
                "save_missed_history": prompt_request.save_missed_history,
                "separate_prompts": prompt_request.separate_prompts,
                "image_quality": copy.deepcopy(prompt_request.image_quality),
                "extra_system_infos": copy.deepcopy(prompt_request.extra_system_infos),
                "game_state": copy.deepcopy(prompt_request.game_state),
                "sender": prompt_request.sender,
                "participants": list(prompt_request.participants or []),
                "capabilities": copy.deepcopy(prompt_request.capabilities),
                "image_data": self._summarize_image_data_for_capture(prompt_request.image_data),
            }

            record = {
                "character_id": char_id,
                "character_name": char_name,
                "event_type": request.event_type,
                "policy": policy.to_dict(),
                "incoming_event": incoming,
                "original_image_data": self._summarize_image_data_for_capture(original_image_data),
                "processed_image_data": self._summarize_image_data_for_capture(image_data_after_processing),
                "image_descriptions": copy.deepcopy(image_descriptions or {}),
                "build_prompt_payload": prompt_snapshot,
            }
            collector.save_capture(record)
        except Exception as e:
            logger.warning(f"[ModelController] Failed to capture generation input: {e}")

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

        id_set = set(str(x) for x in self._characters.all_ids())

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
            ch_ref.add_message_to_history(msg)
            return True

        except Exception as e:
            logger.warning(
                f"[ModelController] append_history_message failed for {getattr(ch_ref, 'char_id', '?')}: {e}",
                exc_info=True)
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
            # единый формат времени для user/assistant (чтобы не было каши в БД)
            "time": datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
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
            # единый формат времени для user/assistant
            "time": datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
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

        raw_role = str(msg.get("role") or "").strip().lower()
        # небольшая обратная совместимость на случай странных значений
        if raw_role == "player":
            raw_role = "user"
        if raw_role not in ("user", "assistant", "system", "event"):
            return None

        # фильтр пустых user
        if raw_role == "user":
            content = msg.get("content")
            if not self._has_visible_user_text(content):
                return None

        def _norm_actor(v: Any) -> str:
            s = str(v or "").strip()
            if not s:
                return ""
            if s.lower() == "player":
                return "Player"
            return s

        def _is_player(v: Any) -> bool:
            return _norm_actor(v) == "Player"

        # достаём поля максимально терпимо
        speaker_raw = msg.get("speaker")
        sender_raw = msg.get("sender")
        target_raw = msg.get("target")

        speaker = _norm_actor(speaker_raw or sender_raw)
        sender = _norm_actor(sender_raw or speaker_raw)
        target = _norm_actor(target_raw)

        # role=user в локальной истории миты может означать не только Player,
        # но и реплику другой миты. В UI это нельзя безусловно превращать в Player.
        has_explicit_non_player_actor = any(
            actor and not _is_player(actor) for actor in (speaker, sender)
        )
        is_player_msg = (
            ((raw_role == "user") and not has_explicit_non_player_actor)
            or _is_player(speaker)
            or _is_player(sender)
        )

        if raw_role == "system":
            ui_role = "system"
        elif is_player_msg:
            ui_role = "user"
        else:
            ui_role = "assistant"

        mm = dict(msg)
        mm["role"] = ui_role

        # Для user-сообщений убираем любые speaker/meta намёки,
        # чтобы делегат рисовал "You:" и жёлтую сторону.
        if ui_role == "user":
            mm["speaker"] = "Player"
            mm["sender"] = "Player"
            c = mm.get("content")
            if isinstance(c, list):
                mm["content"] = [it for it in c if not (isinstance(it, dict) and it.get("type") == "meta")]
            return mm

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
        """
        Загрузка первой страницы истории (самые свежие сообщения).
        """
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False

        ch = self._get_current_character_ref()
        if not ch:
            self.event_bus.emit("history_loaded", {"messages": [], "total_messages": 0, "loaded_offset": 0})
            return

        # [ИСПРАВЛЕНО] Оптимизация SQL
        hm = getattr(ch, "history_manager", None)

        # Проверяем, поддерживает ли HM новые методы пагинации
        if hm and hasattr(hm, "get_total_messages_count") and hasattr(hm, "get_recent_messages"):
            self.total_messages_in_history = hm.get_total_messages_count()

            # Загружаем только последние N сообщений
            # Offset 0 = самые последние
            raw_messages = hm.get_recent_messages(limit=self.lazy_load_batch_size, offset=0)

            self.loaded_messages_offset = len(raw_messages)

            # Проекция для UI (цвета, мета-теги)
            prepared = self.ui_projector.project_for_ui(raw_messages)
            if isinstance(prepared, list):
                prepared = [
                    self._fix_projected_ui_message(r, m)
                    for r, m in zip(raw_messages, prepared)
                ]

            self.event_bus.emit("history_loaded", {
                "messages": prepared,
                "total_messages": self.total_messages_in_history,
                "loaded_offset": self.loaded_messages_offset
            })
        else:
            # Fallback (Старый метод: грузим всё)
            chat_history = ch.load_history()
            all_messages = chat_history.get("messages", []) or []
            self.total_messages_in_history = len(all_messages)

            prepared_all = self.ui_projector.project_for_ui(all_messages)
            if isinstance(prepared_all, list):
                prepared_all = [
                    self._fix_projected_ui_message(r, m)
                    for r, m in zip(all_messages, prepared_all)
                ]
            # Берем хвост списка
            max_display = self.lazy_load_batch_size
            start_index = max(0, self.total_messages_in_history - max_display)
            messages_to_load = prepared_all[start_index:]

            self.loaded_messages_offset = len(messages_to_load)

            self.event_bus.emit("history_loaded", {
                "messages": messages_to_load,
                "total_messages": self.total_messages_in_history,
                "loaded_offset": self.loaded_messages_offset
            })

    def _on_load_more_history(self, event: Event):
        """
        Подгрузка старых сообщений при скролле вверх.
        """
        if self.loaded_messages_offset >= self.total_messages_in_history:
            return

        self.loading_more_history = True
        try:
            ch = self._get_current_character_ref()
            if not ch: return

            hm = getattr(ch, "history_manager", None)

            # [ИСПРАВЛЕНО] Оптимизация SQL
            if hm and hasattr(hm, "get_recent_messages"):
                # offset равен текущему количеству загруженных (мы идем от конца вглубь)
                raw_messages = hm.get_recent_messages(
                    limit=self.lazy_load_batch_size,
                    offset=self.loaded_messages_offset
                )

                if raw_messages:
                    self.loaded_messages_offset += len(raw_messages)
                    prepared = self.ui_projector.project_for_ui(raw_messages)

                    self.event_bus.emit("more_history_loaded", {
                        "messages": prepared,
                        "loaded_offset": self.loaded_messages_offset
                    })
            else:
                # Fallback
                chat_history = ch.load_history()
                all_messages = chat_history.get("messages", []) or []
                self.total_messages_in_history = len(all_messages)  # Обновляем на всякий случай

                prepared_all = self.ui_projector.project_for_ui(all_messages)

                end_index = self.total_messages_in_history - self.loaded_messages_offset
                start_index = max(0, end_index - self.lazy_load_batch_size)

                messages_to_prepend = prepared_all[start_index:end_index]

                if messages_to_prepend:
                    self.loaded_messages_offset += len(messages_to_prepend)
                    self.event_bus.emit("more_history_loaded", {
                        "messages": messages_to_prepend,
                        "loaded_offset": self.loaded_messages_offset
                    })
        finally:
            self.loading_more_history = False

    def debug_info(self, character_id: str | None = None) -> str:
        ch = self._get_character_ref(character_id) if character_id else self._get_current_character_ref()
        if ch and hasattr(ch, "current_variables_string"):
            return ch.current_variables_string()
        return "Debug info not available"

    def token_stats(self) -> dict[str, Any]:
        return self._build_token_stats()

    def schedule_g4f_update(self, version: str = "latest") -> bool:
        logger.warning(
            "g4f automatic installation and update scheduling are disabled; "
            "an already installed package may still be used"
        )
        return False

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
        """Кэш промпта для подсчёта токенов.

        Раньше здесь был deepcopy всего промпта — вместе с base64-картинками, на
        каждый ответ. Картинки в кэше не нужны: ContextCounter считает image_url
        фиксированной ценой, поэтому редакция url не меняет число токенов.
        """
        if not character_id or not isinstance(messages, list):
            return

        safe = redact_image_payloads(list(messages))
        if safe and isinstance(safe[-1], dict) and safe[-1].get("role") == "user":
            safe = safe[:-1]

        self._base_prompt_cache[(character_id, event_type)] = safe

    @staticmethod
    def _is_current_preset_label(label: str | None) -> bool:
        s = str(label or "").strip()
        return s in ("", "Current", "Текущий", _("Текущий", "Current"))

    def _preset_id_from_label(self, label: str | None) -> Optional[int]:
        if label is None or self._is_current_preset_label(label):
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

    def _char_provider_label(self, character_id: str, character_name: str) -> str:
        label = self.settings.get(f"CHAR_PROVIDER_{character_id}", None)
        if label is None and character_name:
            label = self.settings.get(f"CHAR_PROVIDER_{character_name}", None)
        return str(label if label is not None else "Current")

    def _resolve_chat_preset_id(self, character_id: str, character_name: str) -> Optional[int]:
        return self._preset_id_from_label(self._char_provider_label(character_id, character_name))

    def _resolve_preset_id(
        self, event_type: str, policy: RequestPolicy, char_id: str, char_name: str
    ) -> Optional[int]:
        if event_type != "react":
            return self._resolve_chat_preset_id(char_id, char_name)

        lvl = int(getattr(policy, "react_level", None) or 1)
        default_label = self.settings.get("REACT_PROVIDER", _("Текущий", "Current"))
        key = "REACT_PROVIDER_L2" if lvl == 2 else "REACT_PROVIDER_L1"
        label = str(self.settings.get(key, default_label))

        preset_id = self._preset_id_from_label(label)
        if preset_id is None:
            preset_id = self._resolve_chat_preset_id(char_id, char_name)

        logger.info(f"[ModelController] react policy: level={lvl}, provider_label='{label}', preset_id={preset_id}")
        return preset_id

    def _warm_base_prompt(self, cid: str, event_type: str) -> list[dict] | None:
        """Собрать базовый промпт БЕЗ запроса — чтобы счётчик токенов под чатом
        показывал контекст ещё до отправки первого сообщения (#1).

        Используем настоящий PromptBuilderService (единый источник сборки), без
        user_input/rag — это статическая часть окна (система + память + история).
        RAG и текст сообщения добавятся сверху при реальном запросе. Всё
        защищено: любая ошибка → None, счётчик просто останется на 0, как раньше.
        """
        try:
            char = self._get_character_ref(cid)
            if char is None:
                return None
            char_name = str(getattr(char, "name", "") or "")
            policy = resolve_policy(model_event_type=str(event_type))
            preset_id = self._resolve_chat_preset_id(cid, char_name)
            capabilities: Dict[str, Any] = {}
            try:
                capabilities = dict(getattr(self.preset_resolver.resolve(preset_id), "capabilities", {}) or {})
            except Exception:
                capabilities = {}
            cfg = getattr(self.model, "cfg", None)
            memory_limit = int(getattr(cfg, "memory_limit", 40) or 40)
            prompt_request = PromptBuildRequest(
                character=char,
                event_type=event_type,
                policy=policy,
                user_input="",
                memory_limit=memory_limit,
                is_game_master=(cid == "GameMaster"),
                separate_prompts=bool(self.settings.get("SEPARATE_PROMPTS", True)),
                capabilities=capabilities,
                game_state=self.game_state.to_prompt_dict(),
            )
            with character_lock(cid):
                built = use(PromptBuilderService).build(prompt_request)
            # НЕ кладём в _base_prompt_cache: тот кэш — авторитетный слепок
            # реального запроса. Оценку считаем свежей на каждый вызов (пока не
            # было запроса), чтобы она отражала текущие настройки, а не залипала.
            return redact_image_payloads(list(getattr(built, "messages", []) or []))
        except Exception as e:
            logger.debug(f"[ModelController] warm base prompt failed for {cid}: {e}")
            return None

    def _build_current_context_messages(self) -> tuple[str, list[dict], int]:
        cid = self._get_current_character_id()
        if not cid:
            return "", [], 0

        event_type = "chat"
        base = self._base_prompt_cache.get((cid, event_type))
        if not base:
            # Кэш ещё не прогрет (не было запросов в этой сессии) — собираем
            # базовый промпт на лету, чтобы счётчик не висел на нуле до отправки.
            base = self._warm_base_prompt(cid, event_type)
        if not base:
            return cid, [], 0

        # Events.Speech.GET_USER_INPUT удалён: единственный подписчик всегда
        # возвращал "", то есть это был поход на шину за пустой строкой.
        messages = list(base)
        with self._temporary_system_infos_lock:
            temporary = list(self._temporary_system_infos.get(cid, ()))
        messages.extend([x for x in temporary if isinstance(x, dict)])

        return cid, messages, self.context_counter.count_tokens(messages)

    def _build_token_stats(self) -> dict[str, Any]:
        cid, messages, context_tokens = self._build_current_context_messages()
        cfg = getattr(self.model, "cfg", None)
        char = self._get_character_ref(cid) if cid else None
        char_name = str(getattr(char, "name", "") or "")
        preset_id = self._resolve_chat_preset_id(cid, char_name) if cid else None

        pricing_info = None
        model_name = ""
        if cid:
            try:
                resolved_preset = self.preset_resolver.resolve(preset_id)
                model_name = str(getattr(resolved_preset, "api_model", "") or "")
                pricing_info = self.model_pricing_manager.resolve_for_preset(resolved_preset)
            except Exception:
                pricing_info = None

        estimated_cost = None
        estimated_currency = None
        estimated_source = None

        if pricing_info is not None:
            estimated_cost = pricing_info.estimate_prompt_cost(context_tokens)
            if estimated_cost is not None:
                estimated_currency = pricing_info.currency
                estimated_source = pricing_info.source

        # Ручная оценка в рублях — только если пользователь ЯВНО задал цену за
        # 1000 токенов (> 0). Иначе (бесплатный тариф/цена неизвестна) не
        # выдумываем стоимость, а показываем n/a — не врём про рубли.
        if estimated_cost is None and cfg:
            try:
                manual_price = float(cfg.token_cost_input)
            except Exception:
                manual_price = 0.0
            if manual_price > 0:
                estimated_cost = (float(context_tokens) / 1000.0) * manual_price
                estimated_currency = "RUB"
                estimated_source = "manual_settings"

        last = dict(self._last_token_stats or {})
        last.setdefault("actual_cost", None)
        last.setdefault("actual_cost_currency", None)
        last.setdefault("actual_cost_source", None)

        max_context_tokens = None
        max_completion_tokens = None
        if pricing_info is not None:
            max_context_tokens = pricing_info.context_length
            max_completion_tokens = pricing_info.max_completion_tokens
        if max_context_tokens is None:
            try:
                configured = int(self.settings.get("MAX_MODEL_TOKENS", 32000))
            except Exception:
                configured = 32000
            # Провайдер не сообщил окно (напр. Google AI Studio Gemini). Если
            # пользователь не менял дефолт (32000), а модель известна — берём её
            # реальное окно, иначе Gemini/Claude показывались бы как 32k. Явно
            # выставленное пользователем значение уважаем.
            if configured == 32000:
                known = known_model_context_length(model_name)
                if known:
                    configured = known
            max_context_tokens = configured

        return {
            "estimated_context_tokens": int(context_tokens or 0),
            "max_context_tokens": int(max_context_tokens or 0),
            "max_completion_tokens": int(max_completion_tokens or 0) if max_completion_tokens else None,
            "estimated_input_cost": estimated_cost,
            "estimated_input_cost_currency": estimated_currency,
            "estimated_input_cost_source": estimated_source,
            "actual_prompt_tokens": last.get("actual_prompt_tokens"),
            "actual_completion_tokens": last.get("actual_completion_tokens"),
            "actual_total_tokens": last.get("actual_total_tokens"),
            "actual_reasoning_tokens": last.get("actual_reasoning_tokens"),
            "actual_cached_prompt_tokens": last.get("actual_cached_prompt_tokens"),
            "actual_cost": last.get("actual_cost"),
            "actual_cost_currency": last.get("actual_cost_currency"),
            "actual_cost_source": last.get("actual_cost_source"),
            "actual_model": last.get("actual_model"),
            "actual_provider": last.get("actual_provider"),
        }

    def _store_last_usage(
        self,
        usage: Optional[LLMUsage],
        *,
        model: str = "",
        provider: str = "",
        cost_fallback=None,
        cost_fallback_currency: Optional[str] = None,
        cost_fallback_source: Optional[str] = None,
    ) -> None:
        snapshot = self._build_usage_snapshot(
            usage,
            model=model,
            provider=provider,
            cost_fallback=cost_fallback,
            cost_fallback_currency=cost_fallback_currency,
            cost_fallback_source=cost_fallback_source,
        )
        if not snapshot:
            return

        self._last_token_stats = {
            "actual_prompt_tokens": snapshot.get("llm_prompt_tokens"),
            "actual_completion_tokens": snapshot.get("llm_completion_tokens"),
            "actual_total_tokens": snapshot.get("llm_total_tokens"),
            "actual_reasoning_tokens": snapshot.get("llm_reasoning_tokens"),
            "actual_cached_prompt_tokens": snapshot.get("llm_cached_prompt_tokens"),
            "actual_cost": snapshot.get("llm_cost"),
            "actual_cost_currency": snapshot.get("llm_cost_currency"),
            "actual_cost_source": snapshot.get("llm_cost_source"),
            "actual_model": snapshot.get("llm_model"),
            "actual_provider": snapshot.get("llm_provider"),
        }

    def _build_usage_snapshot(
        self,
        usage: Optional[LLMUsage],
        *,
        model: str = "",
        provider: str = "",
        cost_fallback=None,
        cost_fallback_currency: Optional[str] = None,
        cost_fallback_source: Optional[str] = None,
    ) -> dict[str, Any]:
        if usage is None and cost_fallback is None:
            return {}

        actual_cost = usage.cost if usage and usage.cost is not None else cost_fallback
        actual_cost_currency = (
            usage.cost_currency if usage and usage.cost is not None else cost_fallback_currency
        )
        actual_cost_source = (
            usage.cost_source if usage and usage.cost is not None else cost_fallback_source
        )

        return {
            "llm_prompt_tokens": int(usage.prompt_tokens or 0) if usage else None,
            "llm_completion_tokens": int(usage.completion_tokens or 0) if usage else None,
            "llm_total_tokens": int(usage.total_tokens or 0) if usage else None,
            "llm_reasoning_tokens": int(usage.reasoning_tokens or 0) if usage else None,
            "llm_cached_prompt_tokens": int(usage.cached_prompt_tokens or 0) if usage else None,
            "llm_cache_write_tokens": int(usage.cache_write_tokens or 0) if usage else None,
            "llm_cost": actual_cost,
            "llm_cost_currency": actual_cost_currency,
            "llm_cost_source": actual_cost_source,
            "llm_model": model or "",
            "llm_provider": provider or "",
        }

    def _on_get_current_context_tokens(self, event: Event):
        return self._build_token_stats().get("estimated_context_tokens", 0)

    def _on_get_token_stats(self, event: Event):
        return self._build_token_stats()

    def _on_calculate_cost(self, event: Event):
        stats = self._build_token_stats()
        cost = stats.get("estimated_input_cost")
        return float(cost) if cost is not None else 0.0

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

    def _resolve_preset_bool(self, preset, override_key: str, setting_key: str, *, default: bool) -> bool:
        """Булев флаг пресета поверх глобальной настройки.

        Тот же трёхпозиционный контракт, что у enable_thinking: переопределение
        существует только когда у него взведён enabled, иначе берётся глобальное
        значение.
        """
        overrides = getattr(preset, "generation_overrides", None) or {}
        spec = overrides.get(override_key) or {}
        if spec.get("enabled"):
            return bool(spec.get("value", default))
        return bool(self.settings.get(setting_key, default))

    def _split_response_thinking(self, llm_response) -> tuple[str, str]:
        """Собрать размышления из обоих источников сразу.

        Мысли приходят двумя разными путями: текстовыми <think>-тегами внутри
        ответа (DeepSeek-R1 и прочие) и отдельным каналом провайдера
        (reasoning_content у LM Studio, thought-части Gemini). Второй в text не
        попадает вовсе, поэтому его надо забрать из самого ответа.
        """
        visible, think_text = self._extract_think_blocks(str(llm_response.text))
        native = (getattr(llm_response, "reasoning", None) or "").strip()
        if native:
            think_text = f"{native}\n\n{think_text}" if think_text else native
        return visible, think_text

    def _extract_image_description(self, text: str) -> tuple[str, str | None]:
        """
        Extracts <image_description>...</image_description> block from text.
        Returns (clean_text_without_block, description_or_None).
        Used when IMAGE_INLINE_DESCRIPTION is enabled.
        """
        if not isinstance(text, str) or not text:
            return text, None
        pattern = re.compile(r"<image_description\b[^>]*>(.*?)</image_description\s*>", flags=re.IGNORECASE | re.DOTALL)
        m = pattern.search(text)
        if not m:
            return text, None
        description = m.group(1).strip() or None
        clean = pattern.sub("", text)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        return clean, description

    # ---------------------------------------------------------------------
    # GenerationService: служебная одноразовая генерация
    # ---------------------------------------------------------------------

    def generate_utility(self, request: UtilityGenerationRequest) -> UtilityGenerationResult:
        """Сжатие истории / graph extraction: один запрос, без истории и персонажа.

        Ни RAG, ни промпт-сборка, ни запись в историю тут не участвуют.
        """
        char_ref = self._get_character_ref(request.character_id)
        char_name = str(getattr(char_ref, "name", "") or "") or request.character_id or "Мита"

        # Один user-месседж: запрос из одного лишь system-сообщения часть
        # провайдеров (в т.ч. маршруты OpenRouter) отклоняет с HTTP 400.
        messages = [{"role": "user", "content": request.prompt}] if request.prompt else []

        if request.kind == "compress":
            self.event_bus.emit(Events.Model.ON_COMPRESSION_STARTED, {
                "character_id": request.character_id,
                "character_name": char_name,
            })

        logger.info(
            f"[ModelController] {request.kind}: sending {len(messages)} messages, "
            f"preset_id={request.preset_id}, char='{request.character_id}'"
        )

        try:
            # Обычный текст, а не сегментный JSON Миты: иначе провайдер навяжет
            # response_format схемы StructuredResponse и сводка вернётся пустой.
            result = self.model.generate(
                messages,
                stream_callback=None,
                preset_id=request.preset_id,
                capabilities_override={"structured_output": False},
                request_options_override={
                    "max_attempts": request.max_attempts,
                    "retry_delay": request.retry_delay,
                    "request_timeout": request.request_timeout,
                    "suppress_failure_events": True,
                },
            )
            if result and result.text:
                return UtilityGenerationResult(
                    ok=True,
                    text=result.text,
                    provider=getattr(result, "provider_name", None),
                )

            logger.warning(f"[ModelController] {request.kind}: model.generate() returned empty/None")
            last_error = getattr(self.model, "last_error", None)
            fallback_msg = getattr(result, "error_message", "") if result else ""
            return UtilityGenerationResult(
                ok=False,
                error=(
                    last_error.to_user_message()
                    if last_error and hasattr(last_error, "to_user_message")
                    else fallback_msg
                ),
                details=(
                    last_error.to_console_summary()
                    if last_error and hasattr(last_error, "to_console_summary")
                    else fallback_msg
                ),
                status_code=getattr(last_error, "status_code", None) if last_error else None,
                retryable=bool(getattr(last_error, "retryable", False)) if last_error else False,
                retry_after_sec=getattr(last_error, "retry_after_seconds", None) if last_error else None,
                provider=getattr(last_error, "provider", None) if last_error else None,
            )
        except Exception as e:
            logger.error(f"Ошибка при {request.kind}: {e}", exc_info=True)
            return UtilityGenerationResult(ok=False, error=str(e), details=str(e))
        finally:
            if request.kind == "compress":
                self.event_bus.emit(Events.Model.ON_COMPRESSION_FINISHED)

    # ---------------------------------------------------------------------
    # GenerationService: пользовательская генерация
    # ---------------------------------------------------------------------

    def generate_chat(self, request: ChatGenerationRequest) -> Optional[ChatGenerationResult]:
        if request.character_id:
            char = self._get_character_ref(str(request.character_id))
            if char is None:
                logger.error(f"generate_chat: неизвестный character_id='{request.character_id}'.")
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

        # Полные генерации одной Миты идут последовательно, но этот gate не блокирует
        # короткие state-lock секции фонового summary/переменных во время сетевого I/O.
        with character_generation_lock(getattr(char, "char_id", "") or ""):
            return self._generate_chat_serialized(request, char)

    def _generate_chat_serialized(self, request: ChatGenerationRequest, char) -> Optional[ChatGenerationResult]:
        user_input = request.user_input or ""
        visible_user_input = user_input
        system_input = request.system_input or ""
        image_data = list(request.image_data or [])
        image_source = str(request.image_source or "").strip().lower()
        stream_callback = request.stream_callback
        stream_event_callback = request.stream_event_callback
        event_type = request.event_type or "chat"

        sender = str(request.sender or "Player")
        participants = list(request.participants or [])

        req_id = request.req_id or None
        task_uid = request.task_uid or None
        origin_message_id = request.origin_message_id or None

        policy = request.policy or resolve_policy(model_event_type=str(event_type))

        char_id = getattr(char, "char_id", "") or ""
        char_name = getattr(char, "name", "") or ""

        rag_context = ""
        if bool(self.settings.get("RAG_ENABLED", False)) and policy.react_level != 1:
            prompt_set_path = getattr(char, "base_data_path", None)
            rag_context = self.process_rag(char_id, system_input, user_input, prompt_set_path=prompt_set_path)

        # Core-memory triggers (e.g. the code 23 easter egg) are exact hooks:
        # they fire on precise player input, independent of RAG availability or
        # embedding similarity of a two-digit message.
        try:
            from managers.core_memory_triggers import core_memory_context
            _core_ctx = core_memory_context(user_input, character_id=char_id)
            if _core_ctx:
                rag_context = f"{_core_ctx}\n\n{rag_context}" if rag_context else _core_ctx
        except Exception as _core_err:
            logger.warning(f"[{char_id}] core-memory trigger check failed (ignored): {_core_err}")

        game_state = (
            copy.deepcopy(request.game_state)
            if request.game_state
            else self.game_state.to_prompt_dict()
        )

        with self._temporary_system_infos_lock:
            extra_system_infos = list(self._temporary_system_infos.get(char_id, ()))

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

        # Пресет резолвим ДО capabilities. Раньше capabilities брались у текущего
        # пресета, а запрос уходил в пресет персонажа — structured_output мог не
        # совпадать с тем, что реально поддерживает провайдер.
        preset_id = self._resolve_preset_id(event_type, policy, char_id, char_name)

        effective_capabilities = {}
        effective_preset = None
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

        remote_only_segment_fields = self._remote_only_structured_segment_fields()
        if remote_only_segment_fields:
            effective_capabilities["structured_segment_exclude_fields"] = remote_only_segment_fields

        _tools_on = bool(self.settings.get("TOOLS_ON", True))
        _tools_mode = str(self.settings.get("TOOLS_MODE", "native"))
        if _tools_mode == "off":
            _tools_on = False
        _enabled_tools = [
            n for n in _ALL_TOOLS_LIST
            if self.settings.get(f"TOOL_ENABLED_{n}", _DEFAULT_TOOL_ENABLED.get(n, False))
        ]
        if not _enabled_tools:
            _tools_on = False

        if _tools_on and effective_capabilities.get("structured_output", False):
            try:
                schema = self.model.tool_manager._filtered_schema(_enabled_tools)
                effective_capabilities["tools_prompt"] = _render_tools_for_prompt(schema)
            except Exception as e:
                logger.warning(f"[ModelController] Failed to build tools prompt: {e}")
                _tools_on = False

        with character_lock(char_id):
            _custom_params = copy.deepcopy(getattr(char, "custom_params", []) or [])
        effective_capabilities["has_custom_params"] = bool(_custom_params)
        effective_capabilities["custom_params"] = _custom_params
        # Схемный CoT — свойство конкретной модели, а не всей программы: локальной
        # он нужен, чтобы думать вслух, большой хостовой только жжёт токены.
        effective_capabilities["schema_reasoning"] = self._resolve_preset_bool(
            effective_preset, "schema_reasoning", "SCHEMA_REASONING", default=False
        )

        # The selected DSL template is the only owner of intent support. The
        # capability is finalized after PromptController processes the template.
        effective_capabilities["schema_intents"] = False

        # Пока секрет персонажа не раскрыт, secret_exposed в схеме провайдера
        # обязателен: опциональное поле constrained decoding молча пропускает,
        # и модель писала реплику-раскрытие без флага — текст и состояние
        # расходились. Required + nullable заставляет решать каждый ход.
        from characters import SecretExposedCharacter
        if isinstance(char, SecretExposedCharacter):
            with character_lock(char_id):
                _secret_open = bool(char.get_variable("secretExposed", False))
            if not _secret_open:
                effective_capabilities["structured_required_fields"] = ("secret_exposed",)

        # Non-native image fallback: describe images with a vision provider first,
        # then pass text descriptions to the main (non-vision) model instead of images.
        original_image_data = image_data  # kept for history storage
        image_descriptions: dict[str, str] | None = None

        # Build context hint so the vision description model knows the image source.
        _image_context_hint = ""
        if event_type == "camera_snapshot_result":
            _image_context_hint = (
                "This image was captured by the character's head-mounted camera "
                "(their own point of view, in-game). "
                "This is what the character is currently seeing with their own eyes, not a player photo, selfie, or drawing. "
                "Describe the scene strictly from the character's point of view."
            )
        elif image_source == "mita_camera":
            _image_context_hint = (
                "These frames were explicitly marked as coming from the character's own in-game camera. "
                "This is the character's current visual perception, not a player-uploaded image, selfie, or drawing. "
                "Describe what the character is seeing from their point of view."
            )
        elif "[Your eyes (in-game camera)]" in system_input:
            _image_context_hint = (
                "These frames are from the character's own eyes (in-game camera). "
                "Treat them as the character's current visual perception, not as a player-uploaded image, selfie, or drawing. "
                "Describe the scene from their point of view."
            )
        elif event_type == "easel_drawing":
            _image_context_hint = (
                "This image shows the player's drawing on an easel/canvas in-game. "
                "Treat it as artwork created by the player, not as a real-life photo or selfie. "
                "Describe the drawing itself and any depicted characters or objects."
            )

        hidden_user_context = ""

        if image_data and bool(self.settings.get("IMAGE_DESCRIPTION_ENABLED", False)):
            _detail = str(self.settings.get("IMAGE_DESCRIPTION_DETAIL", "normal") or "normal")

            _is_mita_cam = image_source in ("mita_camera",) or event_type == "camera_snapshot_result"
            _is_easel = image_source == "easel" or event_type == "easel_drawing"

            if _is_mita_cam:
                _ctx_preamble_single = (
                    "The following description is what you (the character) currently see through your own eyes "
                    "(in-game camera). React naturally as if perceiving this scene yourself."
                )
                _ctx_preamble_seq = _ctx_preamble_single
            elif _is_easel:
                _ctx_preamble_single = (
                    "The player is showing you their drawing from the in-game easel. "
                    "React to it as artwork the player created and is presenting to you."
                )
                _ctx_preamble_seq = _ctx_preamble_single
            else:
                _ctx_preamble_single = (
                    "The following image description is for internal context only. "
                    "Use it to understand what is shown, but do not repeat it verbatim or present it as dialogue."
                )
                _ctx_preamble_seq = _ctx_preamble_single

            try:
                if len(image_data) > 1:
                    seq_desc = self.image_description_handler.describe_sequence(image_data, context_hint=_image_context_hint)
                    if seq_desc and not seq_desc.startswith("["):
                        hidden_user_context = f"[Hidden image context]\n{_ctx_preamble_seq}\n[Scene: {seq_desc}]"
                        image_descriptions = {_detail: seq_desc}
                        logger.info(f"[ModelController] Non-native sequence mode: {len(image_data)} frames described as one scene.")
                else:
                    descriptions = self.image_description_handler.describe(image_data, context_hint=_image_context_hint)
                    if descriptions:
                        desc_text = "\n".join(
                            f"[Image {i + 1}: {d}]" for i, d in enumerate(descriptions)
                        )
                        hidden_user_context = f"[Hidden image context]\n{_ctx_preamble_single}\n{desc_text}"
                        image_descriptions = {_detail: "\n".join(descriptions)}
                        logger.info(f"[ModelController] Non-native image mode: replaced {len(descriptions)} image(s) with text descriptions.")
                image_data = []  # don't send images to main model
            except Exception as _desc_exc:
                logger.warning(f"[ModelController] Image description fallback failed: {_desc_exc}")

        prompt_request = PromptBuildRequest(
            character=char,
            event_type=event_type,
            policy=policy,
            user_input=user_input,
            system_input=system_input,
            rag_context=rag_context,
            hidden_user_context=hidden_user_context,
            image_data=image_data,
            memory_limit=memory_limit,
            is_game_master=is_game_master,
            save_missed_history=save_missed_history,
            image_quality=image_quality_cfg,
            separate_prompts=separate_prompts,
            extra_system_infos=extra_system_infos,
            game_state=game_state,
            sender=sender,
            participants=participants,
            capabilities=effective_capabilities,
        )
        self._capture_generation_input(
            request=request,
            char_id=char_id,
            char_name=char_name,
            policy=policy,
            prompt_request=prompt_request,
            original_image_data=original_image_data,
            image_data_after_processing=image_data,
            image_descriptions=image_descriptions,
        )

        try:
            with character_lock(char_id):
                prompt_data = use(PromptBuilderService).build(prompt_request)
        except Exception as e:
            logger.error(f"Ошибка при сборке промпта: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": _("Не удалось сформировать промпт.", "Failed to build prompt.")
            })
            return None

        excluded_segment_fields = {
            str(name).strip()
            for name in effective_capabilities.get("structured_segment_exclude_fields", ())
            if str(name).strip()
        }
        intents_available = bool(prompt_data.support_intents) and "intents" not in excluded_segment_fields
        effective_capabilities["schema_intents"] = intents_available
        if intents_available:
            excluded_segment_fields.discard("intents")
        else:
            excluded_segment_fields.add("intents")
        effective_capabilities["structured_segment_exclude_fields"] = tuple(
            sorted(excluded_segment_fields)
        )

        combined_messages = prompt_data.messages

        if event_type == "chat":
            self._cache_base_prompt(char_id, "chat", combined_messages)

        active_pricing = None
        try:
            active_pricing = self.model_pricing_manager.resolve_for_preset(self.preset_resolver.resolve(preset_id))
        except Exception:
            active_pricing = None

        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character_id": char_id,
            "character_name": char_name or char_id or "Мита",
        })

        is_structured_output = effective_capabilities.get("structured_output", False)

        structured_model_cls = None
        if is_structured_output:
            try:
                from schemas.structured_response import StructuredResponse as _SR
                try:
                    from schemas.structured_response import build_structured_response_model  # type: ignore
                    structured_model_cls = build_structured_response_model(_custom_params or [])
                except Exception:
                    structured_model_cls = _SR
            except Exception:
                structured_model_cls = None

        try:
            use_stream_cb = stream_callback if policy.allow_streaming else None
            llm_response = self.model.generate(
                combined_messages,
                stream_callback=use_stream_cb,
                stream_event_callback=(stream_event_callback if policy.allow_streaming else None),
                preset_id=preset_id,
                request_id=str(task_uid or req_id or origin_message_id or ""),
                capabilities_override=effective_capabilities,
                structured_model=structured_model_cls,
            )

            if not llm_response or not llm_response.text:
                error_message = getattr(llm_response, "error_message", None) or _(
                    "Не удалось получить ответ.",
                    "Text generation failed."
                )
                if hasattr(self.model, "get_last_error_message"):
                    try:
                        error_message = self.model.get_last_error_message() or error_message
                    except Exception:
                        pass
                error_details = getattr(llm_response, "error_details", None) if llm_response else None
                provider_error = getattr(self.model, "last_error", None)
                if error_details is None and provider_error is not None and hasattr(provider_error, "to_payload"):
                    error_details = provider_error.to_payload()
                if provider_error is None:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                        "error": error_message,
                    })
                return ChatGenerationResult(
                    text="",
                    character_id=char_id,
                    error=error_message,
                    error_details=error_details,
                )

            raw_text = llm_response.text
            visible_raw, think_text = self._split_response_thinking(llm_response)

            if original_image_data and bool(self.settings.get("IMAGE_INLINE_DESCRIPTION", False)):
                _detail = str(self.settings.get("IMAGE_DESCRIPTION_DETAIL", "normal") or "normal")
                visible_raw, _desc_text = self._extract_image_description(visible_raw)
                if _desc_text:
                    image_descriptions = {_detail: _desc_text}
                else:
                    logger.warning(
                        f"[ModelController][{char_id}] IMAGE_INLINE_DESCRIPTION is enabled "
                        f"but no <image_description> block was found in the model response."
                    )

            if is_structured_output:
                sample_id = str((getattr(llm_response, "raw", {}) or {}).get("finetune_sample_id") or "").strip() or None
                structured_result = self._process_structured_output(
                    visible_raw=visible_raw,
                    think_text=think_text,
                    usage=llm_response.usage,
                    response_model=llm_response.model or "",
                    response_provider=llm_response.provider_name or "",
                    pricing_info=active_pricing,
                    char=char,
                    char_id=char_id,
                    char_name=char_name,
                    origin_message_id=origin_message_id,
                    capabilities=effective_capabilities,
                    policy=policy,
                    sender=sender,
                    participants=participants,
                    user_input=visible_user_input,
                    image_data=original_image_data,
                    image_source=image_source,
                    req_id=req_id,
                    task_uid=task_uid,
                    event_type=event_type,
                    combined_messages=combined_messages,
                    preset_id=preset_id,
                    tools_on=_tools_on,
                    enabled_tools=_enabled_tools,
                    tool_depth=0,
                    image_descriptions=image_descriptions,
                    structured_model_cls=structured_model_cls,
                    sample_id=sample_id,
                )
                if structured_result is not None:
                    self._consume_temporary_system_infos(char_id, extra_system_infos)
                return structured_result

            inline_graph_json: Optional[str] = None
            if (bool(self.settings.get("GRAPH_EXTRACTION_ENABLED", False))
                    and bool(self.settings.get("GRAPH_EXTRACTION_INLINE", False))):
                visible_raw, inline_graph_json = _strip_graph_tag(visible_raw)

            with character_lock(char_id):
                processed = char.process_response_nlp_commands(
                    visible_raw,
                    self.settings.get("SAVE_MISSED_MEMORY", False),
                )
                targets: list[str] = []
                if hasattr(char, "consume_pending_targets"):
                    try:
                        targets = char.consume_pending_targets()
                    except Exception:
                        targets = []
                if hasattr(char, "flush_variables"):
                    char.flush_variables()
                created_memory_ids = list(getattr(char, "_last_created_memory_ids", None) or [])
                voice_profile = None
                if hasattr(char, "to_voice_profile"):
                    try:
                        voice_profile = char.to_voice_profile()
                    except Exception:
                        voice_profile = None
            target = targets[-1] if targets else "Player"

            final_text = processed
            if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
                final_text = re.sub(
                    r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                    "[Изображение]",
                    final_text
                )

            usage_cost_fallback = active_pricing.estimate_usage_cost(llm_response.usage) if active_pricing else None
            usage_snapshot = self._build_usage_snapshot(
                llm_response.usage,
                model=llm_response.model or "",
                provider=llm_response.provider_name or "",
                cost_fallback=usage_cost_fallback,
                cost_fallback_currency=getattr(active_pricing, "currency", None),
                cost_fallback_source=getattr(active_pricing, "source", None),
            )
            sample_id = str((getattr(llm_response, "raw", {}) or {}).get("finetune_sample_id") or "").strip() or None

            assistant_message_id = ""
            if policy.write_to_history:
                assistant_message_id = self.event_writer.write_turn(
                    responder_character_id=char_id,
                    sender=sender,
                    participants=participants,
                    user_input=visible_user_input,
                    image_data=original_image_data,
                    image_source=image_source,
                    image_descriptions=image_descriptions,
                    req_id=req_id,
                    origin_message_id=origin_message_id,
                    assistant_text=final_text,
                    assistant_target=target,
                    event_type=event_type,
                    task_uid=task_uid,
                    thinking=think_text or None,
                    llm_usage=usage_snapshot,
                    sample_id=sample_id,
                )

            self._store_last_usage(
                llm_response.usage,
                model=llm_response.model or "",
                provider=llm_response.provider_name or "",
                cost_fallback=usage_cost_fallback,
                cost_fallback_currency=getattr(active_pricing, "currency", None),
                cost_fallback_source=getattr(active_pricing, "source", None),
            )

            self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)

            self._consume_temporary_system_infos(char_id, extra_system_infos)

            self.event_bus.emit(Events.History.MESSAGE_COMPLETED, {
                "character_id": char_id,
                "character_ref": char,
                "user_input": visible_user_input,
                "assistant_output": final_text,
                "created_memory_ids": created_memory_ids,
                "inline_graph_json": inline_graph_json,
            })

            return ChatGenerationResult(
                text=final_text,
                character_id=char_id,
                voice_profile=voice_profile,
                target=target,
                targets=targets,
                think=think_text or None,
                message_id=assistant_message_id,
                sample_id=sample_id or "",
            )

        except Exception as e:
            logger.error(f"Error during LLM generation/processing: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": str(e)})
            return None

    # Default RAG output templates
    _DEFAULT_RAG_MEM_ITEM = "[{score:.3f}] N:{id} ({type}, prio={priority}, date={date}) {content}"
    _DEFAULT_RAG_HIST_ITEM = "- [{score:.3f}] ({date}){meta} {content}"
    _DEFAULT_RAG_WRAPPER = "<relevant_memories>\n{memory_block}\n</relevant_memories>\n\n<past_context>\n{history_block}\n</past_context>"

    def process_rag(self, char_id, system_input, user_input, prompt_set_path=None):
        # ---------------------------------------------------------------------
        # RAG выполняется ДО BUILD_PROMPT
        # Возвращает готовый RAG-блок отдельным сообщением. Исходный
        # system_input (событие или служебная инструкция) не изменяется:
        # актуальная инструкция должна оставаться после справочного контекста.
        # Templates can be customized per prompt set via Structural/ files:
        #   rag_memory_item.txt, rag_history_item.txt, rag_wrapper.txt
        from utils.template_loader import load_optional_template

        final_input = False
        if user_input:
            final_input = user_input
        elif system_input:
            final_input = system_input
        if final_input:
            try:
                from managers.rag.rag_manager import RAGManager

                rag = RAGManager.for_character(char_id)
                rag_limit = int(self.settings.get("RAG_MAX_RESULTS", 8))
                rag_thr = float(self.settings.get("RAG_SIM_THRESHOLD", 0.4))
                results = rag.search_relevant(str(final_input), limit=rag_limit, threshold=rag_thr)
                forgotten_count = rag.get_forgotten_count()

                if results:
                    mem_tpl = load_optional_template(
                        prompt_set_path, "Structural/rag_memory_item.txt", self._DEFAULT_RAG_MEM_ITEM
                    )
                    hist_tpl = load_optional_template(
                        prompt_set_path, "Structural/rag_history_item.txt", self._DEFAULT_RAG_HIST_ITEM
                    )
                    wrapper_tpl = load_optional_template(
                        prompt_set_path, "Structural/rag_wrapper.txt", self._DEFAULT_RAG_WRAPPER
                    )

                    clip_max = int(self.settings.get("RAG_CLIP_MAX_CHARS", 700))

                    def _clip(s, n=clip_max):
                        t = str(s or "").strip()
                        return (t[:n] + "…") if len(t) > n else t

                    mem_lines = []
                    hist_lines = []
                    graph_lines = []

                    for r in results:
                        if not isinstance(r, dict):
                            continue
                        src = r.get("source")
                        if src == "memory":
                            try:
                                mem_lines.append(mem_tpl.format(
                                    score=float(r.get("score", 0)),
                                    id=r.get("id", "?"),
                                    type=r.get("type", ""),
                                    priority=r.get("priority", ""),
                                    date=r.get("date_created", ""),
                                    content=_clip(r.get("content")),
                                ))
                            except (KeyError, IndexError, ValueError):
                                mem_lines.append(f"[{r.get('score', 0):.3f}] N:{r.get('id', '?')} {_clip(r.get('content'))}")
                        elif src == "graph":
                            graph_lines.append(f"- [{r.get('score', 0):.2f}] {_clip(r.get('content'))}")
                        elif src == "history":
                            sp = r.get("speaker") or ""
                            tg = r.get("target") or ""
                            meta = ""
                            if sp and tg:
                                meta = f" ({sp}→{tg})"
                            elif sp:
                                meta = f" ({sp})"
                            elif tg:
                                meta = f" (→{tg})"
                            try:
                                hist_lines.append(hist_tpl.format(
                                    score=float(r.get("score", 0)),
                                    date=r.get("date", ""),
                                    meta=meta,
                                    content=_clip(r.get("content")),
                                    speaker=sp,
                                    target=tg,
                                    role=r.get("role", ""),
                                ))
                            except (KeyError, IndexError, ValueError):
                                hist_lines.append(f"- [{r.get('score', 0):.3f}] {_clip(r.get('content'))}")

                    if mem_lines or hist_lines or graph_lines:
                        mem_header = "# score=RAG relevance (0..1); forgotten memories — use N:id with memory ops\n"
                        memory_block_str = (mem_header + "\n".join(mem_lines)) if mem_lines else ""
                        graph_block_str = "\n".join(graph_lines) if graph_lines else ""
                        try:
                            rag_block = wrapper_tpl.format(
                                memory_block=memory_block_str,
                                history_block="\n".join(hist_lines) if hist_lines else "",
                                graph_block=graph_block_str,
                            )
                        except (KeyError, IndexError):
                            parts = []
                            if mem_lines:
                                parts.append("<relevant_memories>\n" + memory_block_str + "\n</relevant_memories>")
                            if hist_lines:
                                parts.append("<past_context>\n" + "\n".join(hist_lines) + "\n</past_context>")
                            if graph_lines:
                                parts.append("<entity_knowledge>\n" + graph_block_str + "\n</entity_knowledge>")
                            rag_block = "\n\n".join(parts)
                        # If the wrapper template doesn't include {graph_block},
                        # append graph entries separately so they are never silently dropped.
                        if graph_lines and "{graph_block}" not in wrapper_tpl:
                            rag_block += "\n\n<entity_knowledge>\n" + graph_block_str + "\n</entity_knowledge>"
                        if forgotten_count > 0:
                            rag_block += f"\nForgotten pool: {forgotten_count} memories"

                        logger.info(
                            f"[{char_id}] RAG blocks built as separate message "
                            f"(mem={len(mem_lines)}, hist={len(hist_lines)}, graph={len(graph_lines)}).")
                        return rag_block
            except Exception as e:
                logger.warning(f"[{char_id}] Failed to run RAG (ignored): {e}", exc_info=True)
        return ""

    # ---------------------------------------------------------------------
    # Structured Output processing
    # ---------------------------------------------------------------------

    def _process_structured_output(
        self,
        visible_raw: str,
        think_text: str,
        usage: Optional[LLMUsage],
        response_model: str,
        response_provider: str,
        pricing_info,
        char,
        char_id: str,
        char_name: str,
        origin_message_id: str | None,
        capabilities: dict,
        policy,
        sender: str,
        participants: list,
        user_input: str,
        image_data: list,
        image_source: str,
        req_id: str | None,
        task_uid: str | None,
        event_type: str,
        combined_messages: list | None = None,
        preset_id: int | None = None,
        tools_on: bool = False,
        enabled_tools: list = None,
        tool_depth: int = 0,
        image_descriptions: dict[str, str] | None = None,
        structured_model_cls=None,
        sample_id: str | None = None,
    ) -> Optional[ChatGenerationResult]:
        try:
            structured = parse_structured_response(visible_raw, model_cls=structured_model_cls)
        except StructuredResponseParseError as e:
            logger.error(
                f"[ModelController] Failed to parse structured response for {char_id}: {e}. "
                f"Falling back to legacy processing."
            )
            # Fallback to legacy tag-based processing
            with character_lock(char_id):
                processed = char.process_response_nlp_commands(
                    visible_raw, self.settings.get("SAVE_MISSED_MEMORY", False)
                )
                fallback_targets: list[str] = []
                if hasattr(char, "consume_pending_targets"):
                    try:
                        fallback_targets = char.consume_pending_targets()
                    except Exception:
                        fallback_targets = []
                if hasattr(char, "flush_variables"):
                    char.flush_variables()
                voice_profile = None
                if hasattr(char, "to_voice_profile"):
                    try:
                        voice_profile = char.to_voice_profile()
                    except Exception:
                        voice_profile = None
            fallback_target = fallback_targets[-1] if fallback_targets else "Player"

            usage_cost_fallback = pricing_info.estimate_usage_cost(usage) if pricing_info else None
            self._store_last_usage(
                usage,
                model=response_model,
                provider=response_provider,
                cost_fallback=usage_cost_fallback,
                cost_fallback_currency=getattr(pricing_info, "currency", None),
                cost_fallback_source=getattr(pricing_info, "source", None),
            )

            self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)
            return ChatGenerationResult(
                text=processed,
                character_id=char_id,
                voice_profile=voice_profile,
                target=fallback_target,
                targets=fallback_targets,
                think=think_text or None,
                sample_id=sample_id or "",
            )

        self._sanitize_structured_segment_fields(structured, capabilities)

        # Apply and snapshot character state in a short critical section. Tool
        # execution and any follow-up provider request happen after this lock.
        with character_lock(char_id):
            char.process_structured_response(
                structured,
                save_as_missed=self.settings.get("SAVE_MISSED_MEMORY", False),
            )
            targets: list[str] = []
            if hasattr(char, "consume_pending_targets"):
                try:
                    targets = char.consume_pending_targets()
                except Exception:
                    targets = []
            if hasattr(char, "flush_variables"):
                char.flush_variables()
            created_memory_ids = list(getattr(char, "_last_created_memory_ids", None) or [])
            voice_profile = None
            if hasattr(char, "to_voice_profile"):
                try:
                    voice_profile = char.to_voice_profile()
                except Exception:
                    voice_profile = None
        target = targets[-1] if targets else "Player"

        # --- Tool call path ---
        _active_tools = enabled_tools or []
        _tool_max_depth = int(self.settings.get("TOOL_MAX_DEPTH", 2))
        _tool_allowed = (
            structured.tool_call
            and tools_on
            and tool_depth < _tool_max_depth
            and (not _active_tools or structured.tool_call.name in _active_tools)
        )
        if not _tool_allowed and structured.tool_call and tools_on:
            logger.warning(
                f"[ModelController] Tool '{structured.tool_call.name}' called by model "
                f"but not in enabled list {_active_tools} — ignoring."
            )
        if _tool_allowed:
            return self._handle_tool_call(
                structured=structured,
                visible_raw=visible_raw,
                think_text=think_text,
                usage=usage,
                response_model=response_model,
                response_provider=response_provider,
                pricing_info=pricing_info,
                char=char,
                char_id=char_id,
                char_name=char_name,
                origin_message_id=origin_message_id,
                capabilities=capabilities,
                policy=policy,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                image_source=image_source,
                req_id=req_id,
                task_uid=task_uid,
                event_type=event_type,
                combined_messages=combined_messages or [],
                preset_id=preset_id,
                enabled_tools=_active_tools,
                tool_depth=tool_depth,
                structured_model_cls=structured_model_cls,
                sample_id=sample_id,
                image_descriptions=image_descriptions,
                targets=targets,
                voice_profile=voice_profile,
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
        # Attach raw LLM JSON for the debug panel (not saved to history)
        result_dict["_raw_json"] = visible_raw
        final_text = result_dict["response"]

        if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
            final_text = re.sub(
                r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                "[Изображение]",
                final_text,
            )

        usage_cost_fallback = pricing_info.estimate_usage_cost(usage) if pricing_info else None
        usage_snapshot = self._build_usage_snapshot(
            usage,
            model=response_model,
            provider=response_provider,
            cost_fallback=usage_cost_fallback,
            cost_fallback_currency=getattr(pricing_info, "currency", None),
            cost_fallback_source=getattr(pricing_info, "source", None),
        )

        # Extract image_description from structured response (inline description for structured mode)
        _structured_image_descriptions: dict[str, str] | None = dict(image_descriptions or {}) or None
        if getattr(structured, "image_description", None):
            _detail = str(self.settings.get("IMAGE_DESCRIPTION_DETAIL", "normal") or "normal")
            if _structured_image_descriptions is None:
                _structured_image_descriptions = {}
            _structured_image_descriptions[_detail] = structured.image_description.strip()
            logger.debug(f"[ModelController][{char_id}] Structured image_description captured ({_detail}).")

        assistant_message_id = ""
        if policy.write_to_history:
            history_dict = {k: v for k, v in result_dict.items()
                            if not k.startswith("_") or k == "_raw_json"}
            assistant_message_id = self.event_writer.write_turn(
                responder_character_id=char_id,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                image_source=image_source,
                image_descriptions=_structured_image_descriptions,
                req_id=req_id,
                origin_message_id=origin_message_id,
                assistant_text=final_text,
                assistant_target=target,
                event_type=event_type,
                task_uid=task_uid,
                structured_data=history_dict,
                thinking=think_text or None,
                llm_usage=usage_snapshot,
                sample_id=sample_id,
            )

        self._store_last_usage(
            usage,
            model=response_model,
            provider=response_provider,
            cost_fallback=usage_cost_fallback,
            cost_fallback_currency=getattr(pricing_info, "currency", None),
            cost_fallback_source=getattr(pricing_info, "source", None),
        )

        self.event_bus.emit(Events.Model.ON_SUCCESSFUL_RESPONSE)

        # Build inline_graph_json from structured entities/relations (if graph extraction enabled)
        inline_graph_json: Optional[str] = None
        if (bool(self.settings.get("GRAPH_EXTRACTION_ENABLED", False))
                and (structured.entities or structured.relations)):
            try:
                import json as _json
                graph_payload = {
                    "entities": list(structured.entities) if structured.entities else [],
                    "relations": list(structured.relations) if structured.relations else [],
                }
                inline_graph_json = _json.dumps(graph_payload, ensure_ascii=False)
            except Exception as _ge:
                logger.warning(f"[ModelController] Failed to build graph JSON from structured entities/relations: {_ge}")

        # Notify graph extraction (and any future subscribers).
        self.event_bus.emit(Events.History.MESSAGE_COMPLETED, {
            "character_id": char_id,
            "character_ref": char,
            "user_input": user_input,
            "assistant_output": final_text,
            "created_memory_ids": created_memory_ids,
            "inline_graph_json": inline_graph_json,
            "memories_already_tagged": True,
            "from_structured_output": True,
        })

        return ChatGenerationResult(
            text=final_text,
            character_id=char_id,
            voice_profile=voice_profile,
            target=target,
            targets=targets,
            think=think_text or None,
            structured=result_dict,
            message_id=assistant_message_id,
            sample_id=sample_id or "",
        )

    # ---------------------------------------------------------------------
    # Tool call handler (structured output tools)
    # ---------------------------------------------------------------------

    def _handle_tool_call(
        self,
        structured,
        visible_raw: str,
        think_text: str,
        usage: Optional[LLMUsage],
        response_model: str,
        response_provider: str,
        pricing_info,
        char,
        char_id: str,
        char_name: str,
        origin_message_id: str | None,
        capabilities: dict,
        policy,
        sender: str,
        participants: list,
        user_input: str,
        image_data: list,
        image_source: str,
        req_id: str | None,
        task_uid: str | None,
        event_type: str,
        combined_messages: list,
        preset_id: int | None,
        enabled_tools: list,
        tool_depth: int,
        structured_model_cls=None,
        sample_id: str | None = None,
        image_descriptions: dict[str, str] | None = None,
        targets: list[str] | None = None,
        voice_profile=None,
    ) -> Optional[ChatGenerationResult]:
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
        result_dict["_raw_json"] = visible_raw
        first_text = result_dict.get("response", "")

        targets = list(targets or [])
        target = targets[-1] if targets else "Player"

        # Write first turn to history
        usage_cost_fallback = pricing_info.estimate_usage_cost(usage) if pricing_info else None
        usage_snapshot = self._build_usage_snapshot(
            usage,
            model=response_model,
            provider=response_provider,
            cost_fallback=usage_cost_fallback,
            cost_fallback_currency=getattr(pricing_info, "currency", None),
            cost_fallback_source=getattr(pricing_info, "source", None),
        )

        first_assistant_message_id = ""
        if policy.write_to_history:
            first_assistant_message_id = self.event_writer.write_turn(
                responder_character_id=char_id,
                sender=sender,
                participants=participants,
                user_input=user_input,
                image_data=image_data,
                image_source=image_source,
                image_descriptions=None,
                req_id=req_id,
                origin_message_id=origin_message_id,
                assistant_text=first_text,
                assistant_target=target,
                event_type=event_type,
                task_uid=task_uid,
                structured_data=result_dict,
                thinking=think_text or None,
                llm_usage=usage_snapshot,
                sample_id=sample_id,
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
            "message_id": first_assistant_message_id,
        }, delivery=EventDelivery.ORDERED)

        # Emit tool executing indicator for UI
        self.event_bus.emit(Events.Model.ON_TOOL_EXECUTING, {
            "tool_name": tool_name,
            "character_id": char_id,
        })

        # Execute the tool
        logger.info(f"[ModelController] Executing tool '{tool_name}' with args: {tool_args}")
        self.model.tool_manager.set_char_context(char_id)
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
        }, delivery=EventDelivery.ORDERED)

        # Build tool result message(s) for the second LLM call.
        # TOOL_RESULT_MSG_MODE controls which role(s) are used to inject the result:
        #   "system" — only a system message (may be ignored by some providers mid-conversation)
        #   "user"   — only a user message with [SYSTEM INFO] tag
        #   "both"   — both (default, most reliable across providers)
        _result_mode = str(self.settings.get("TOOL_RESULT_MSG_MODE", "both"))
        _instruction = (
            "\n\nThe tool has finished. "
            "Use the results above to give the player a complete answer. "
            "Do NOT call any tools again unless the question explicitly requires it. "
            "Respond in JSON format."
        )
        _system_content = f"[Tool result: {tool_name}]\n{tool_result}{_instruction}"
        _user_content   = f"[SYSTEM INFO] [Tool result: {tool_name}]\n{tool_result}{_instruction}"

        # Build messages for second call: append first response JSON + tool result
        combined_messages_v2 = list(combined_messages)
        try:
            first_response_json = structured.model_dump_json(exclude_none=True)
        except Exception:
            first_response_json = first_text
        combined_messages_v2.append({"role": "assistant", "content": first_response_json})
        if _result_mode in ("system", "both"):
            combined_messages_v2.append({"role": "system", "content": _system_content})
        if _result_mode in ("user", "both"):
            combined_messages_v2.append({"role": "user", "content": _user_content})

        # Second LLM call
        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character_id": char_id,
            "character_name": char_name or char_id or "Мита",
        })

        llm_response_2 = self.model.generate(
            combined_messages_v2,
            preset_id=preset_id,
            capabilities_override=(capabilities or None),
            structured_model=structured_model_cls,
        )

        if not llm_response_2 or not llm_response_2.text:
            logger.error(f"[ModelController] Second LLM call after tool '{tool_name}' returned empty.")
            error_message = getattr(llm_response_2, "error_message", None) or _(
                "Не удалось получить ответ после инструмента.",
                "Failed to get response after tool."
            )
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": error_message
            })
            # Return first response as fallback
            return ChatGenerationResult(
                text=first_text,
                character_id=char_id,
                voice_profile=voice_profile,
                target=target,
                targets=targets,
                think=think_text or None,
                structured=result_dict,
                message_id=first_assistant_message_id,
            )

        visible_raw_2, think_text_2 = self._split_response_thinking(llm_response_2)
        merged_usage = usage.merged_with(llm_response_2.usage) if usage else llm_response_2.usage

        combined_think = think_text
        if think_text_2:
            combined_think = (combined_think + "\n\n" + think_text_2) if combined_think else think_text_2

        # Process second response (depth+1 prevents infinite tool loops)
        # user_input is empty so the user message is not written to history again
        sample_id_2 = str((getattr(llm_response_2, "raw", {}) or {}).get("finetune_sample_id") or "").strip() or None

        # Process second response (depth+1 prevents infinite tool loops)
        # user_input is empty so the user message is not written to history again
        return self._process_structured_output(
            visible_raw=visible_raw_2,
            think_text=combined_think or "",
            usage=merged_usage,
            response_model=llm_response_2.model or response_model,
            response_provider=llm_response_2.provider_name or response_provider,
            pricing_info=pricing_info,
            char=char,
            char_id=char_id,
            char_name=char_name,
            origin_message_id=origin_message_id,
            capabilities=capabilities,
            policy=policy,
            sender=sender,
            participants=participants,
            user_input="",
            image_data=[],
            image_source=image_source,
            req_id=req_id,
            task_uid=task_uid,
            event_type=event_type,
            combined_messages=combined_messages_v2,
            preset_id=preset_id,
            tools_on=True,
            enabled_tools=enabled_tools,
            tool_depth=tool_depth + 1,
            image_descriptions=image_descriptions,
            structured_model_cls=structured_model_cls,
            sample_id=sample_id_2,
        )

    # ---------------------------------------------------------------------
    # Reload prompts
    # ---------------------------------------------------------------------

    def _on_reload_prompts_async(self, event: Event):
        # Скачивание промптов — блокирующий IO, ему не нужен asyncio-loop.
        executors().submit(Pools.IO, self._reload_prompts)

    def _reload_prompts(self):
        try:
            from utils.prompt_downloader import PromptDownloader

            success = PromptDownloader().download_and_replace_prompts()

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
    def _fix_projected_ui_message(self, raw: dict, ui_msg: dict) -> dict:
        if not isinstance(raw, dict) or not isinstance(ui_msg, dict):
            return ui_msg

        raw_role = str(raw.get("role") or "").strip().lower()
        speaker = str(raw.get("speaker") or "").strip()
        sender = str(raw.get("sender") or "").strip()

        def is_player(x: str) -> bool:
            return str(x or "").strip().lower() == "player"

        has_explicit_non_player_actor = any(
            actor and not is_player(actor) for actor in (speaker, sender)
        )
        is_player_message = (
            ((raw_role == "user") and not has_explicit_non_player_actor)
            or is_player(speaker)
            or is_player(sender)
        )

        if is_player_message:
            out = dict(ui_msg)
            out["role"] = "user"
            out["speaker"] = "Player"
            out["sender"] = "Player"
            c = out.get("content")
            if isinstance(c, list):
                out["content"] = [it for it in c if not (isinstance(it, dict) and it.get("type") == "meta")]
            return out

        return ui_msg

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

