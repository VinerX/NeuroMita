# src/controllers/model_controller.py
from __future__ import annotations

import json
import datetime
import re
import copy
from typing import Optional, Any

from handlers.chat_handler import ChatModel
from utils import _
from core.events import get_event_bus, Events, Event
from main_logger import logger

from managers.api_preset_resolver import ApiPresetResolver
from managers.game_state_manager import GameState
from managers.context_counter import ContextCounter


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

    def __init__(self, settings, pip_installer, character_controller=None):
        self.settings = settings
        self.event_bus = get_event_bus()

        # UI history paging
        self.lazy_load_batch_size = 50
        self.total_messages_in_history = 0
        self.loaded_messages_offset = 0
        self.loading_more_history = False

        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
        self.model = ChatModel(settings, pip_installer)

        self.context_counter = ContextCounter(encoding_model="gpt-4o-mini")
        self._base_prompt_cache: dict[tuple[str, str], list[dict]] = {}

        self.game_state = GameState()
        self._temporary_system_infos: list[dict] = []

        # legacy compatibility (ChatModel держит ссылки на персонажей)
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
        self.event_bus.subscribe("model_settings_loaded", self._on_model_settings_loaded, weak=False)
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

    def _on_model_settings_loaded(self, event: Event):
        data = event.data or {}
        if data.get("api_key"):
            self.model.api_key = data["api_key"]
        if data.get("api_url"):
            self.model.api_url = data["api_url"]
        if data.get("api_model"):
            self.model.api_model = data["api_model"]
        if "makeRequest" in data:
            self.model.makeRequest = data["makeRequest"]

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
                match = None
                sl = s.lower()
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


    def _fanout_player_user_message_to_participants(self, user_message: dict | None, participants: list[str], current_char_id: str, sender: str):
        if sender != "Player":
            return
        if not user_message or not isinstance(user_message, dict):
            return

        content = user_message.get("content")
        if not isinstance(content, list):
            return

        has_text = False
        for it in content:
            if isinstance(it, dict) and it.get("type") == "text":
                txt = it.get("text")
                if txt is None:
                    txt = it.get("content", "")
                if str(txt or "").strip():
                    has_text = True
                    break
        if not has_text:
            return

        for pid in participants:
            if not pid or pid in ("Player", current_char_id):
                continue

            ch = self._get_character_ref(pid)
            if ch is None or not hasattr(ch, "history_manager"):
                continue

            try:
                hist = ch.history_manager.load_history()
                msgs = hist.get("messages", []) or []
                msg_copy = copy.deepcopy(user_message)
                msg_copy["fanout_from"] = current_char_id
                msgs.append(msg_copy)
                hist["messages"] = msgs

                if not isinstance(hist.get("variables"), dict):
                    hist["variables"] = getattr(ch, "variables", {}).copy() if hasattr(ch, "variables") else {}

                ch.history_manager.save_history(hist)
            except Exception as e:
                logger.warning(f"[ModelController] Fanout истории в {pid} не удался: {e}", exc_info=True)

    def _on_load_history(self, event: Event):
        self.loaded_messages_offset = 0
        self.total_messages_in_history = 0
        self.loading_more_history = False

        ch = self._get_current_character_ref()
        if not ch:
            self.event_bus.emit("history_loaded", {"messages": [], "total_messages": 0, "loaded_offset": 0})
            return

        base_history = ch.load_history()
        base_messages = base_history.get("messages", []) or []
        group = self._detect_group_participants(base_messages)

        def load_for(cid: str):
            cref = self._get_character_ref(cid)
            if not cref:
                return [], ""
            h = cref.load_history()
            msgs = h.get("messages", []) or []
            name = str(getattr(cref, "name", "") or cid)

            out = []
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                mm = dict(m)
                mm["character_id"] = cid
                mm["character_name"] = name
                out.append(mm)
            return out, name

        merged_raw: list[dict] = []
        if group:
            for cid in group:
                msgs, _ = load_for(cid)
                merged_raw.extend(msgs)
        else:
            cid = str(getattr(ch, "char_id", "") or "")
            cname = str(getattr(ch, "name", "") or cid)
            merged_raw = []
            for m in base_messages:
                if not isinstance(m, dict):
                    continue
                mm = dict(m)
                mm["character_id"] = cid
                mm["character_name"] = cname
                merged_raw.append(mm)

        decorated: list[tuple[float, int, dict]] = []
        seq = 0
        for m in merged_raw:
            if not isinstance(m, dict):
                continue
            ts = self._parse_msg_time_to_epoch(m.get("time", "") or "")
            decorated.append((ts, seq, m))
            seq += 1
        decorated.sort(key=lambda x: (x[0], x[1]))

        seen = set()
        final_msgs: list[dict] = []

        for _, _, m in decorated:
            role = str(m.get("role") or "")
            sender = str(m.get("sender") or "Player")
            target = str(m.get("target") or "")

            content = m.get("content")
            text = self._content_to_text(content)

            if role == "user" and not self._has_visible_user_text(content):
                continue

            if role == "assistant":
                speaker_id = str(m.get("character_id") or "")
                speaker_name = str(m.get("character_name") or speaker_id)
            elif role == "user" and sender != "Player":
                speaker_id = sender
                speaker_name = sender
                role = "assistant"
                if isinstance(content, list):
                    new_list = []
                    for it in content:
                        if isinstance(it, dict) and it.get("type") == "text":
                            txt = it.get("text")
                            if txt is None:
                                txt = it.get("content", "")
                            cleaned = self._strip_interlocutor_prefix(str(txt or ""))
                            it2 = dict(it)
                            if "text" in it2:
                                it2["text"] = cleaned
                            else:
                                it2["content"] = cleaned
                            new_list.append(it2)
                        else:
                            new_list.append(it)
                    content = new_list
                    text = self._content_to_text(content)
                elif isinstance(content, str):
                    content = self._strip_interlocutor_prefix(content)
                    text = content
            else:
                speaker_id = "Player"
                speaker_name = ""

            sig = self._signature_for_merge(m, as_speaker=speaker_id, text=text)
            if sig in seen:
                continue
            seen.add(sig)

            speaker_label = speaker_name
            if role == "assistant":
                if target and target != "Player":
                    speaker_label = f"{speaker_name} → {target}"

            mm = dict(m)
            mm["role"] = role
            mm["content"] = content

            if speaker_label:
                mm = self._decorate_for_ui(mm, speaker_label)

            final_msgs.append(mm)

        self.total_messages_in_history = len(final_msgs)

        max_display_messages = int(self.settings.get("MAX_CHAT_HISTORY_DISPLAY", 200))
        start_index = max(0, self.total_messages_in_history - max_display_messages)
        messages_to_load = final_msgs[start_index:]

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
        # Для merged-режима можно сделать пагинацию, но пока безопасно не догружать (чтобы не путать offsets).
        return

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

    def _on_generate_response(self, event: Event):
        data = event.data or {}

        user_input = data.get("user_input", "") or ""
        system_input = data.get("system_input", "") or ""
        image_data = data.get("image_data", []) or []
        stream_callback = data.get("stream_callback", None)
        event_type = (data.get("event_type") or "chat") or "chat"

        sender = str(data.get("sender") or "Player")
        participants = self._normalize_participants(data.get("participants") or [])

        preset_id_override = data.get("preset_id", None)
        character_id_override = self._normalize_character_id_from_data(data)

        char = None
        if character_id_override:
            char = self._get_character_ref(str(character_id_override))
            if char is None:
                logger.error(f"GENERATE_RESPONSE: неизвестный character_id='{character_id_override}' (нет фолбэка на current).")
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": _("Неизвестный персонаж.", "Unknown character.")})
                return None
        else:
            char = self._get_current_character_ref()

        if not char:
            logger.error("Генерация невозможна: персонаж не выбран.")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": _("Персонаж не выбран.", "Character not selected.")})
            return None

        char_id = getattr(char, "char_id", "") or ""
        char_name = getattr(char, "name", "") or ""

        if event_type == "compress":
            messages = []
            if system_input:
                messages.append({"role": "system", "content": system_input})

            preset_id = preset_id_override
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
                },
                timeout=10.0
            )
        except Exception as e:
            logger.error(f"Ошибка при BUILD_PROMPT: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": _("Не удалось сформировать промпт.", "Failed to build prompt.")})
            return None

        if not prompt_res or not isinstance(prompt_res[0], dict):
            logger.error("BUILD_PROMPT не вернул валидный результат")
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": _("Не удалось сформировать промпт.", "Failed to build prompt.")})
            return None

        prompt_data = prompt_res[0]
        combined_messages = prompt_data.get("messages", []) or []
        history_for_save = prompt_data.get("history_messages", []) or []
        user_message_for_history = prompt_data.get("user_message", None)

        if event_type == "chat":
            self._cache_base_prompt(char_id, "chat", combined_messages)

        self._fanout_player_user_message_to_participants(
            user_message=user_message_for_history,
            participants=participants,
            current_char_id=char_id,
            sender=sender
        )

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
            react_provider_label = str(self.settings.get("REACT_PROVIDER", _("Текущий", "Current")))
            preset_id = _resolve_label_to_preset_id(react_provider_label)
            if preset_id is None:
                preset_id = _resolve_label_to_preset_id(_get_char_provider_label(char_id, char_name))
        else:
            preset_id = _resolve_label_to_preset_id(_get_char_provider_label(char_id, char_name))

        self.event_bus.emit(Events.Model.ON_STARTED_RESPONSE_GENERATION, {
            "character_id": char_id,
            "character_name": char_name or char_id or "Мита",
        })

        try:
            use_stream_cb = stream_callback if event_type != "react" else None
            raw_text = self.model.generate(combined_messages, stream_callback=use_stream_cb, preset_id=preset_id)

            if not raw_text:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": _("Не удалось получить ответ.", "Text generation failed.")})
                return None

            processed = char.process_response_nlp_commands(raw_text, self.settings.get("SAVE_MISSED_MEMORY", False))

            target = None
            if hasattr(char, "consume_pending_target"):
                try:
                    target = char.consume_pending_target()
                except Exception:
                    target = None

            final_text = processed

            if bool(self.settings.get("REPLACE_IMAGES_WITH_PLACEHOLDERS", False)):
                final_text = re.sub(
                    r'https?://\S+\.(?:png|jpg|jpeg|gif|bmp)|data:image/\S+;base64,\S+',
                    "[Изображение]",
                    final_text
                )

            assistant_message = {"role": "assistant", "content": final_text}
            assistant_message["time"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            if target:
                assistant_message["target"] = target

            if event_type != "react":
                new_messages = []
                user_msg = prompt_data.get("user_message")
                if isinstance(user_msg, dict):
                    new_messages.append(user_msg)
                new_messages.append(assistant_message)

                self.event_bus.emit(Events.History.SAVE_AFTER_RESPONSE, {
                    "character_id": char_id,
                    "character_ref": char,
                    "append": True,
                    "new_messages": new_messages,
                })

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
                "target": target or "Player",
            }

        except Exception as e:
            logger.error(f"Error during LLM generation/processing: {e}", exc_info=True)
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": str(e)})
            return None

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

    def _parse_msg_time_to_epoch(self, time_str: str) -> float:
        if not time_str:
            return 0.0
        s = str(time_str).strip()
        if not s or s == "???":
            return 0.0

        for fmt in ("%d.%m.%Y_%H.%M", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return dt.timestamp()
            except Exception:
                continue
        return 0.0


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


    def _normalize_message_for_merge_key(self, msg: dict) -> str:
        role = msg.get("role", "")
        time_s = msg.get("time", "") or ""
        sender = msg.get("sender", "") or ""
        target = msg.get("target", "") or ""
        content = msg.get("content")

        try:
            content_norm = json.dumps(content, ensure_ascii=False, sort_keys=True)
        except Exception:
            content_norm = str(content)

        if role == "user" and str(sender or "Player") == "Player":
            return f"{role}|{time_s}|{sender}|{content_norm}"
        return f"{role}|{time_s}|{sender}|{target}|{msg.get('character_id','')}|{content_norm}"


    def _decorate_for_ui(self, msg: dict, speaker_name: str) -> dict:
        mm = dict(msg)
        role = mm.get("role")

        if role in ("user", "assistant"):
            content = mm.get("content")
            if isinstance(content, list):
                mm["content"] = [{"type": "meta", "speaker": speaker_name}] + content
            elif isinstance(content, str):
                mm["content"] = [{"type": "meta", "speaker": speaker_name}, {"type": "text", "text": content}]
            else:
                mm["content"] = [{"type": "meta", "speaker": speaker_name}, {"type": "text", "text": str(content)}]

        return mm


    def _detect_group_participants(self, messages: list[dict]) -> list[str]:
        if not messages:
            return []
        for m in reversed(messages[-50:]):
            if not isinstance(m, dict):
                continue
            pts = m.get("participants")
            if isinstance(pts, list):
                cleaned = [str(x) for x in pts if str(x).strip() and str(x) != "Player"]
                cleaned = list(dict.fromkeys(cleaned))
                if len(cleaned) >= 2:
                    return cleaned
        return []
    
    def _strip_interlocutor_prefix(self, s: str) -> str:
        if not isinstance(s, str):
            return str(s)
        s2 = s.strip()
        # убираем "[Собеседник: X]" из начала (чтобы не мусорить в UI и для дедупа)
        s2 = re.sub(r"^\[Собеседник:\s*[^\]]+\]\s*", "", s2, flags=re.IGNORECASE)
        return s2


    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out = []
            for it in content:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "text":
                    txt = it.get("text")
                    if txt is None:
                        txt = it.get("content", "")
                    out.append(str(txt or ""))
            return "\n".join(out)
        return str(content)


    def _minute_bucket(self, time_str: str) -> int:
        ts = 0.0
        try:
            ts = self._parse_msg_time_to_epoch(time_str)
        except Exception:
            ts = 0.0
        if ts <= 0:
            return -1
        return int(ts // 60)


    def _signature_for_merge(self, msg: dict, *, as_speaker: str, text: str) -> str:
        mb = self._minute_bucket(msg.get("time", "") or "")
        t = self._strip_interlocutor_prefix(text).strip()
        # ограничим длину для устойчивости дедупа на очень длинных тегированных сообщениях
        if len(t) > 2000:
            t = t[:2000]
        return f"{as_speaker}|{mb}|{t}"