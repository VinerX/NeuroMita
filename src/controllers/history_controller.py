from __future__ import annotations
from typing import Dict, Any, List, Optional
import datetime
import base64
import time
import threading
from io import BytesIO

from core.events import get_event_bus, Events, Event
from core.response_status import response_status_kind
from main_logger import logger


class HistoryController:
    _SUMMARY_TEXT_VAR = "HISTORY_COMPRESSION_SUMMARY"
    _SUMMARY_COUNT_VAR = "HISTORY_COMPRESSION_SUMMARY_COUNT"

    def __init__(self):
        self.event_bus = get_event_bus()
        self._messages_since_last_periodic_compression: Dict[str, int] = {}
        self._compression_guard = threading.Lock()
        self._compression_inflight: set[str] = set()
        self._background_compression_inflight: set[str] = set()
        self._background_compression_timers: Dict[str, threading.Timer] = {}
        self._compression_cooldowns: Dict[str, float] = {}
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.History.PREPARE_FOR_PROMPT, self._on_prepare_for_prompt, weak=False)
        self.event_bus.subscribe(Events.History.SAVE_AFTER_RESPONSE, self._on_save_after_response, weak=False)
        self.event_bus.subscribe(Events.History.MESSAGE_COMPLETED, self._on_message_completed, weak=False)

    def _get_setting(self, key: str, default: Any = None) -> Any:
        try:
            res = self.event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {'key': key, 'default': default},
                timeout=1.0
            )
            return res[0] if res else default
        except Exception:
            return default

    def _on_prepare_for_prompt(self, event: Event) -> Dict[str, Any]:
        data = event.data or {}

        char_id: str = data.get('character_id')
        if not char_id:
            logger.error("[HistoryController] PREPARE_FOR_PROMPT без character_id")
            return {'history': []}

        character = data.get("character_ref")
        if character is None:
            logger.error(f"[HistoryController] PREPARE_FOR_PROMPT для '{char_id}' без character_ref")
            return {'history': []}

        if getattr(character, "char_id", None) != char_id:
            logger.error(
                f"[HistoryController] character_ref.char_id != character_id "
                f"({getattr(character, 'char_id', None)} != {char_id})"
            )
            return {'history': []}

        event_type: str = data.get('event_type', 'chat')
        memory_limit: int = int(data.get('memory_limit', 40))
        is_gm: bool = bool(data.get('is_game_master', False))
        save_missed_history: bool = bool(data.get('save_missed_history', True))
        image_cfg: Dict[str, Any] = data.get('image_quality', {}) or {}
        disable_compression: bool = bool(data.get('disable_compression', False))

        effective_limit = 8 if is_gm else memory_limit
        if effective_limit <= 0:
            effective_limit = 1

        history_data = character.history_manager.load_history()
        llm_messages_history: List[Dict[str, Any]] = history_data.get("messages", []) or []
        if not isinstance(llm_messages_history, list):
            llm_messages_history = []

        # фильтр мусорных user (например " " из старых цепочек)
        filtered: List[Dict[str, Any]] = []
        for m in llm_messages_history:
            if not isinstance(m, dict):
                continue
            if m.get("role") == "user" and not self._has_visible_message_content(m.get("content")):
                continue
            filtered.append(m)
        llm_messages_history = filtered

        output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))
        use_external_summary = output_target == "history"
        history_summary = self._get_history_summary(character) if use_external_summary else ""
        summary_count = self._get_history_summary_count(character)
        summary_count = max(0, min(summary_count, len(llm_messages_history)))

        if not disable_compression and self._needs_emergency_sync_compression(
            llm_messages_history=llm_messages_history,
            effective_limit=effective_limit,
            summary_count=summary_count,
        ):
            llm_messages_history, history_summary, summary_count = self._process_history_compression(
                character,
                llm_messages_history,
                effective_limit,
                history_summary=history_summary,
                summary_count=summary_count,
                background_mode=False,
            )

        unsummarized_history = llm_messages_history[summary_count:]
        if summary_count > 0:
            missed_messages, history_limited = self._split_history_by_dialog_limit(
                unsummarized_history,
                effective_limit,
            )
        else:
            # Preserve full context until an async compression actually succeeds.
            missed_messages = []
            history_limited = unsummarized_history

        if missed_messages and save_missed_history:
            logger.info(f"[HistoryController] Сохраняю {len(missed_messages)} пропущенных сообщений для персонажа {char_id}.")
            character.history_manager.save_missed_history(missed_messages)

        if image_cfg.get('enabled', False):
            history_limited = self._apply_history_image_quality_reduction(history_limited, image_cfg)

        # ключевая часть: подготовка для LLM (без лишних полей + с префиксами speaker/target)
        history_for_llm = self._sanitize_history_for_llm(character, history_limited)

        return {'history': history_for_llm, 'history_summary': history_summary}

    def _decorate_messages_with_character_info(
        self,
        messages: List[Dict[str, Any]],
        char_id: str,
        character_name: str
    ) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        out: List[Dict[str, Any]] = []
        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue

            mm = m.copy()
            mm.setdefault("character_id", char_id)
            if character_name:
                mm.setdefault("character_name", character_name)
            out.append(mm)
        return out

    def _messages_equal_shallow(self, a: dict, b: dict) -> bool:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        if a.get("role") != b.get("role"):
            return False
        return a.get("content") == b.get("content")


    def _on_save_after_response(self, event: Event):
        data = event.data or {}
        char_id: str = data.get('character_id')

        if not char_id:
            logger.error("[HistoryController] SAVE_AFTER_RESPONSE без character_id")
            return False

        character = data.get("character_ref")
        if character is None:
            logger.error(f"[HistoryController] SAVE_AFTER_RESPONSE для '{char_id}' без character_ref")
            return False

        if getattr(character, "char_id", None) != char_id:
            logger.error(
                f"[HistoryController] SAVE_AFTER_RESPONSE mismatch "
                f"({getattr(character, 'char_id', None)} != {char_id})"
            )
            return False

        # backward compat: либо append new_messages, либо overwrite messages
        append_mode = bool(data.get("append", False))
        new_messages: List[Dict[str, Any]] = data.get("new_messages") or []
        messages: List[Dict[str, Any]] = data.get("messages") or []

        try:
            if append_mode:
                history_data = character.history_manager.load_history()
                existing = history_data.get("messages", []) or []
                if not isinstance(existing, list):
                    existing = []

                existing_ids = set()
                for m in existing[-300:]:
                    if isinstance(m, dict):
                        mid = str(m.get("message_id") or "")
                        if mid:
                            existing_ids.add(mid)

                for m in new_messages:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("message_id") or "")
                    if mid and mid in existing_ids:
                        continue
                    existing.append(m)
                    if mid:
                        existing_ids.add(mid)

                character.save_character_state_to_history(existing)
                logger.debug(f"[HistoryController] История персонажа {char_id} append (+{len(new_messages)}).")
                return True

            character.save_character_state_to_history(messages)
            logger.debug(f"[HistoryController] История персонажа {char_id} сохранена ({len(messages)} сообщений).")
            return True
        except Exception as e:
            logger.error(f"[HistoryController] Ошибка сохранения истории для {char_id}: {e}", exc_info=True)
            return False

    def _on_message_completed(self, event: Event) -> None:
        data = event.data or {}
        char_id = str(data.get("character_id") or "").strip()
        character = data.get("character_ref")
        if not char_id or character is None:
            return
        if getattr(character, "char_id", None) != char_id:
            return
        self._start_background_compression(character)

    def _process_history_compression(
        self,
        character,
        llm_messages_history: List[Dict[str, Any]],
        effective_limit: int,
        *,
        history_summary: str = "",
        summary_count: int = 0,
        background_mode: bool = False,
    ) -> tuple[List[Dict[str, Any]], str, int]:
        compress_percent = float(self._get_setting("HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS", 0.85))
        enable_on_limit = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_ON_LIMIT", True))
        enable_periodic = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_PERIODIC", False))
        periodic_interval = int(self._get_setting("HISTORY_COMPRESSION_PERIODIC_INTERVAL", 20))
        output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))

        char_id = getattr(character, "char_id", "Unknown")

        keep_tail = int(effective_limit) if effective_limit and effective_limit > 0 else 1
        keep_tail = max(1, keep_tail)

        min_len_to_trigger = max(1, int(keep_tail * compress_percent))
        use_external_summary = (output_target == "history")
        source_messages = llm_messages_history[summary_count:]
        plan = self._build_compression_plan(
            source_messages=source_messages,
            keep_tail=keep_tail,
            min_len_to_trigger=min_len_to_trigger,
            enable_on_limit=enable_on_limit,
            enable_periodic=enable_periodic,
            periodic_interval=periodic_interval,
            background_mode=background_mode,
            char_id=char_id,
        )
        if not plan:
            return llm_messages_history, history_summary, summary_count

        messages_to_compress, reason = plan
        if not messages_to_compress:
            return llm_messages_history, history_summary, summary_count

        logger.info(
            f"[HistoryController][{char_id}] {reason}: попытка сжать "
            f"{len(messages_to_compress)} сообщений."
        )
        compressed_summary = self._compress_history_singleflight(
            character,
            messages_to_compress,
            previous_summary=history_summary if use_external_summary else "",
            background_mode=background_mode,
        )

        if not compressed_summary:
            logger.warning(f"[HistoryController][{char_id}] Сжатие истории не удалось.")
            return llm_messages_history, history_summary, summary_count

        new_summary, new_count = self._apply_compression_result(
            character,
            output_target=output_target,
            compressed_summary=compressed_summary,
            previous_summary=history_summary,
            summary_count=summary_count,
            compressed_count=len(messages_to_compress),
            history_len=len(llm_messages_history),
        )

        if background_mode:
            return llm_messages_history, new_summary, new_count

        if output_target == "memory":
            llm_messages_history = llm_messages_history[new_count:]
            _, llm_messages_history = self._split_history_by_dialog_limit(
                llm_messages_history,
                keep_tail,
            )

        if reason == "Periodic compression":
            self._messages_since_last_periodic_compression[char_id] = 0

        return llm_messages_history, new_summary, new_count

    def _build_compression_plan(
        self,
        *,
        source_messages: List[Dict[str, Any]],
        keep_tail: int,
        min_len_to_trigger: int,
        enable_on_limit: bool,
        enable_periodic: bool,
        periodic_interval: int,
        background_mode: bool,
        char_id: str,
    ) -> tuple[List[Dict[str, Any]], str] | None:
        dialog_count = self._count_dialog_messages(source_messages)
        if enable_on_limit and dialog_count >= min_len_to_trigger and dialog_count > keep_tail:
            messages_to_compress, _ = self._split_history_by_dialog_limit(source_messages, keep_tail)
            if messages_to_compress:
                return messages_to_compress, "On-limit compression"

        if enable_periodic and periodic_interval > 0:
            cnt = self._messages_since_last_periodic_compression.get(char_id, 0)
            if background_mode:
                cnt += 1
                self._messages_since_last_periodic_compression[char_id] = cnt
            if cnt >= periodic_interval:
                messages_to_compress = self._take_history_prefix_by_dialog_count(
                    source_messages,
                    periodic_interval,
                )
                if messages_to_compress:
                    return messages_to_compress, "Periodic compression"
                logger.info(f"[HistoryController][{char_id}] Нет сообщений для периодического сжатия.")
        return None

    def _apply_compression_result(
        self,
        character,
        *,
        output_target: str,
        compressed_summary: str,
        previous_summary: str,
        summary_count: int,
        compressed_count: int,
        history_len: int,
    ) -> tuple[str, int]:
        new_count = min(history_len, summary_count + compressed_count)
        new_summary = previous_summary

        if output_target == "memory":
            if hasattr(character, 'memory_system') and character.memory_system:
                character.memory_system.add_memory(
                    content=compressed_summary,
                    memory_type="summary"
                )
                logger.info(
                    f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
                    f"Сжатая сводка добавлена в MemorySystem."
                )
            else:
                logger.warning(
                    f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
                    f"MemorySystem недоступен для сводки."
                )
                return previous_summary, summary_count
        elif output_target == "history":
            new_summary = compressed_summary
            logger.info(
                f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
                f"Сжатая сводка вынесена в отдельное состояние истории."
            )
        else:
            logger.warning(
                f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
                f"Неизвестный target для сжатия истории: {output_target}"
            )

        self._set_history_summary_state(character, new_summary, new_count)
        return new_summary, new_count

    def _needs_emergency_sync_compression(
        self,
        *,
        llm_messages_history: List[Dict[str, Any]],
        effective_limit: int,
        summary_count: int,
    ) -> bool:
        if effective_limit <= 0:
            return False
        source_messages = llm_messages_history[summary_count:]
        emergency_limit = max(effective_limit * 2, effective_limit + 8)
        return self._count_dialog_messages(source_messages) > emergency_limit

    def _start_background_compression(self, character) -> None:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        delay_sec = self._compression_background_delay_seconds()
        remaining_cooldown = self._get_compression_cooldown_remaining(char_id)
        self._schedule_background_compression(character, delay_sec=max(delay_sec, remaining_cooldown))

    def _schedule_background_compression(self, character, *, delay_sec: float) -> None:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        timer = threading.Timer(
            max(0.0, float(delay_sec)),
            self._run_scheduled_background_compression,
            args=(character,),
        )
        timer.daemon = True
        timer.name = f"history-compress-delay-{char_id}"

        with self._compression_guard:
            previous_timer = self._background_compression_timers.get(char_id)
            if previous_timer is not None:
                previous_timer.cancel()
            self._background_compression_timers[char_id] = timer

        logger.info(
            f"[HistoryController][{char_id}] Scheduling background compression in "
            f"{max(0.0, float(delay_sec)):.2f}s."
        )
        timer.start()

    def _run_scheduled_background_compression(self, character) -> None:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        should_reschedule = False
        with self._compression_guard:
            self._background_compression_timers.pop(char_id, None)
            if char_id in self._background_compression_inflight:
                should_reschedule = True
            else:
                self._background_compression_inflight.add(char_id)
        if should_reschedule:
            reschedule_delay = max(1.0, self._compression_background_delay_seconds())
            self._schedule_background_compression(character, delay_sec=reschedule_delay)
            return
        worker = threading.Thread(
            target=self._run_post_response_compression,
            args=(character,),
            daemon=True,
            name=f"history-compress-{char_id}",
        )
        worker.start()

    def _run_post_response_compression(self, character) -> None:
        try:
            history_data = character.history_manager.load_history()
            llm_messages_history: List[Dict[str, Any]] = history_data.get("messages", []) or []
            if not isinstance(llm_messages_history, list):
                return

            filtered: List[Dict[str, Any]] = []
            for m in llm_messages_history:
                if not isinstance(m, dict):
                    continue
                if m.get("role") == "user" and not self._has_visible_message_content(m.get("content")):
                    continue
                filtered.append(m)
            llm_messages_history = filtered

            memory_limit = int(self._get_setting("MODEL_MESSAGE_LIMIT", 40))
            if memory_limit <= 0:
                memory_limit = 1
            effective_limit = 8 if getattr(character, "char_id", "") == "GameMaster" else memory_limit

            output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))
            history_summary = self._get_history_summary(character) if output_target == "history" else ""
            summary_count = max(0, min(self._get_history_summary_count(character), len(llm_messages_history)))

            self._process_history_compression(
                character,
                llm_messages_history,
                effective_limit,
                history_summary=history_summary,
                summary_count=summary_count,
                background_mode=True,
            )
        except Exception as e:
            logger.warning(
                f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
                f"Background compression failed: {e}",
                exc_info=True,
            )
        finally:
            char_id = getattr(character, "char_id", "Unknown") or "Unknown"
            with self._compression_guard:
                self._background_compression_inflight.discard(char_id)

    def _compress_history_singleflight(
        self,
        character,
        messages_to_compress: List[Dict[str, Any]],
        *,
        previous_summary: str = "",
        background_mode: bool = False,
    ) -> Optional[str]:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        with self._compression_guard:
            if char_id in self._compression_inflight:
                logger.info(
                    f"[HistoryController][{char_id}] Compression already in flight; "
                    f"skipping duplicate request."
                )
                return None
            self._compression_inflight.add(char_id)

        try:
            return self._compress_history(
                character,
                messages_to_compress,
                previous_summary=previous_summary,
                background_mode=background_mode,
            )
        finally:
            with self._compression_guard:
                self._compression_inflight.discard(char_id)

    def _compress_history(
        self,
        character,
        messages_to_compress: List[Dict[str, Any]],
        *,
        previous_summary: str = "",
        background_mode: bool = False,
    ) -> Optional[str]:
        try:
            template_path = str(self._get_setting(
                "HISTORY_COMPRESSION_PROMPT_TEMPLATE",
                "Prompts/System/compression_prompt.txt"
            ))
            with open(template_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except Exception as e:
            logger.error(
                f"[HistoryController] Ошибка чтения шаблона сжатия истории '{template_path}': {e}",
                exc_info=True
            )
            return None

        try:
            formatted_messages = "\n".join([
                f"[{msg.get('time', '')}] "
                f"[{'Player' if msg.get('role') == 'user' else 'Character or System'}]: {msg.get('content')}"
                if msg.get('time')
                else f"[{'Player' if msg.get('role') == 'user' else 'Character or System'}]: {msg.get('content')}"
                for msg in messages_to_compress
            ])
            previous_summary_limit = int(self._get_setting("HISTORY_COMPRESSION_PREVIOUS_SUMMARY_MAX_CHARS", 6000))
            previous_summary_trimmed = self._truncate_text_for_prompt(previous_summary, previous_summary_limit)

            full_prompt = prompt_template.replace("{history_messages}", formatted_messages)
            full_prompt = full_prompt.replace("{your character}", getattr(character, "name", "Character"))
            full_prompt = full_prompt.replace("{current_character_name}", getattr(character, "name", "Character"))
            full_prompt = full_prompt.replace("{previous_summary}", previous_summary_trimmed)
            max_attempts = max(1, int(self._get_setting("HISTORY_COMPRESSION_MAX_ATTEMPTS", 3)))
            base_retry_delay = max(0.0, float(self._get_setting("HISTORY_COMPRESSION_RETRY_BASE_DELAY_SEC", 2.0)))
            max_retry_delay = max(base_retry_delay, float(self._get_setting("HISTORY_COMPRESSION_RETRY_MAX_DELAY_SEC", 20.0)))
            request_timeout = max(1.0, float(self._get_setting("HISTORY_COMPRESSION_REQUEST_TIMEOUT_SEC", 60.0)))
            char_id = getattr(character, "char_id", "Unknown") or "Unknown"

            cooldown_remaining = self._get_compression_cooldown_remaining(char_id)
            if cooldown_remaining > 0:
                logger.info(
                    f"[HistoryController][{char_id}] Compression skipped because provider cooldown is active "
                    f"for another {cooldown_remaining:.2f}s."
                )
                return None

            hc_provider = str(self._get_setting("HC_PROVIDER", "Current"))
            preset_id: Optional[int] = None
            if hc_provider and hc_provider not in ("Current", "Текущий"):
                # Try numeric ID first (legacy / direct ID usage).
                try:
                    preset_id = int(hc_provider)
                except ValueError:
                    # Look up by display name via ApiPresets event.
                    try:
                        meta_res = self.event_bus.emit_and_wait(
                            Events.ApiPresets.GET_PRESET_LIST, timeout=1.0
                        )
                        meta = meta_res[0] if meta_res else None
                        if meta:
                            for bucket in ("custom", "builtin"):
                                for pm in (meta.get(bucket) or []):
                                    if getattr(pm, "name", None) == hc_provider:
                                        pid = getattr(pm, "id", None)
                                        if isinstance(pid, int):
                                            preset_id = pid
                                            break
                                if preset_id is not None:
                                    break
                    except Exception as e:
                        logger.warning(f"[HistoryController] Preset name lookup failed: {e}")
                    if preset_id is None:
                        logger.warning(
                            f"[HistoryController] Не удалось найти пресет '{hc_provider}', используется текущий."
                        )
                if preset_id is not None:
                    logger.info(f"[HistoryController] Используется пресет для сжатия истории: {preset_id}")

            return self._run_compression_request(
                character=character,
                full_prompt=full_prompt,
                preset_id=preset_id,
                max_attempts=max_attempts,
                base_retry_delay=base_retry_delay,
                max_retry_delay=max_retry_delay,
                request_timeout=request_timeout,
                background_mode=background_mode,
            )

            with response_status_kind("compression"):
                res = self.event_bus.emit_and_wait(
                    Events.Model.GENERATE_RESPONSE,
                    {
                        'user_input': '',
                        'system_input': full_prompt,
                        'image_data': [],
                        'stream_callback': None,
                        'message_id': None,
                        'event_type': 'compress',
                        'preset_id': preset_id
                    },
                    timeout=60.0
                )
            if not res:
                logger.warning("[HistoryController] GENERATE_RESPONSE не вернул результат для сжатия истории.")
                return None

            compressed_summary = res[0]
            if isinstance(compressed_summary, str) and compressed_summary.strip():
                logger.info("[HistoryController] История успешно сжата.")
                return compressed_summary
            logger.warning("[HistoryController] Пустая сводка после сжатия истории.")
            return None

        except Exception as e:
            logger.error(f"[HistoryController] Ошибка при сжатии истории: {e}", exc_info=True)
            return None

    def _run_compression_request(
        self,
        *,
        character,
        full_prompt: str,
        preset_id: Optional[int],
        max_attempts: int,
        base_retry_delay: float,
        max_retry_delay: float,
        request_timeout: float,
        background_mode: bool,
    ) -> Optional[str]:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        last_failure: Dict[str, Any] = {}

        for attempt in range(1, max_attempts + 1):
            with response_status_kind("compression"):
                res = self.event_bus.emit_and_wait(
                    Events.Model.GENERATE_RESPONSE,
                    {
                        'user_input': '',
                        'system_input': full_prompt,
                        'image_data': [],
                        'stream_callback': None,
                        'message_id': None,
                        'event_type': 'compress',
                        'preset_id': preset_id,
                        'return_details': True,
                        'request_options_override': {
                            'max_attempts': 1,
                            'retry_delay': 0.0,
                            'request_timeout': request_timeout,
                            'suppress_failure_events': True,
                        },
                    },
                    timeout=request_timeout
                )

            result_payload = res[0] if res else None
            if isinstance(result_payload, dict):
                if result_payload.get("ok") and str(result_payload.get("text") or "").strip():
                    self._clear_compression_cooldown(char_id)
                    logger.info("[HistoryController] РСЃС‚РѕСЂРёСЏ СѓСЃРїРµС€РЅРѕ СЃР¶Р°С‚Р°.")
                    return str(result_payload.get("text")).strip()
                last_failure = result_payload
            elif isinstance(result_payload, str) and result_payload.strip():
                self._clear_compression_cooldown(char_id)
                logger.info("[HistoryController] РСЃС‚РѕСЂРёСЏ СѓСЃРїРµС€РЅРѕ СЃР¶Р°С‚Р°.")
                return result_payload.strip()
            else:
                last_failure = {
                    "ok": False,
                    "text": "",
                    "error": "",
                    "details": "",
                    "status_code": None,
                    "retryable": False,
                    "retry_after_sec": None,
                }

            retryable = bool(last_failure.get("retryable", False))
            retry_after_sec = self._coerce_positive_float(last_failure.get("retry_after_sec"))
            status_code = last_failure.get("status_code")
            error_text = str(last_failure.get("details") or last_failure.get("error") or "").strip()
            logger.warning(
                f"[HistoryController][{char_id}] Compression attempt {attempt}/{max_attempts} failed: "
                f"status={status_code}, retryable={retryable}, details={error_text or 'n/a'}"
            )

            if not retryable:
                break

            delay_sec = retry_after_sec
            if delay_sec is None:
                delay_sec = min(max_retry_delay, base_retry_delay * (2 ** (attempt - 1)))
            self._set_compression_cooldown(char_id, delay_sec)

            if attempt < max_attempts:
                time.sleep(delay_sec)

        logger.warning("[HistoryController] РЎР¶Р°С‚РёРµ РёСЃС‚РѕСЂРёРё Р·Р°РІРµСЂС€РёР»РѕСЃСЊ Р±РµР· СѓСЃРїРµС…Р°.")
        if background_mode and self._get_compression_cooldown_remaining(char_id) > 0:
            self._schedule_background_compression(
                character,
                delay_sec=max(
                    self._compression_background_delay_seconds(),
                    self._get_compression_cooldown_remaining(char_id),
                ),
            )
        return None

    def _compression_background_delay_seconds(self) -> float:
        return max(0.0, float(self._get_setting("HISTORY_COMPRESSION_BACKGROUND_DELAY_SEC", 8.0)))

    def _coerce_positive_float(self, value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            out = float(value)
            if out <= 0:
                return None
            return out
        except Exception:
            return None

    def _get_compression_cooldown_remaining(self, char_id: str) -> float:
        now = time.monotonic()
        with self._compression_guard:
            until = float(self._compression_cooldowns.get(char_id, 0.0) or 0.0)
            if until <= now:
                self._compression_cooldowns.pop(char_id, None)
                return 0.0
            return until - now

    def _set_compression_cooldown(self, char_id: str, delay_sec: float) -> None:
        delay_sec = max(0.0, float(delay_sec))
        if delay_sec <= 0:
            return
        with self._compression_guard:
            self._compression_cooldowns[char_id] = time.monotonic() + delay_sec

    def _clear_compression_cooldown(self, char_id: str) -> None:
        with self._compression_guard:
            self._compression_cooldowns.pop(char_id, None)

    def _get_history_summary(self, character) -> str:
        try:
            return str(character.get_variable(self._SUMMARY_TEXT_VAR, "") or "").strip()
        except Exception:
            return ""

    def _get_history_summary_count(self, character) -> int:
        try:
            value = character.get_variable(self._SUMMARY_COUNT_VAR, 0)
            return int(value or 0)
        except Exception:
            return 0

    def _set_history_summary_state(self, character, summary: str, summary_count: int) -> None:
        try:
            character.set_variable(self._SUMMARY_TEXT_VAR, str(summary or "").strip())
            character.set_variable(self._SUMMARY_COUNT_VAR, max(0, int(summary_count or 0)))
            if hasattr(character, "flush_variables"):
                character.flush_variables()
        except Exception as e:
            logger.warning(f"[HistoryController] Не удалось сохранить состояние summary: {e}", exc_info=True)

    def _truncate_text_for_prompt(self, text: str, limit: int) -> str:
        if limit <= 0:
            return ""

        text = str(text or "").strip()
        if len(text) <= limit:
            return text

        keep = max(0, limit - len("\n...[truncated]"))
        return text[:keep].rstrip() + "\n...[truncated]"

    def _process_image_quality(self, image_bytes: bytes, target_quality: int) -> Optional[bytes]:
        if not image_bytes:
            return None

        if target_quality <= 0:
            logger.info("[HistoryController] Изображение будет удалено (target_quality <= 0).")
            return None

        try:
            from PIL import Image
            original_size = len(image_bytes)
            img = Image.open(BytesIO(image_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')

            byte_arr = BytesIO()
            img.save(byte_arr, format='JPEG', quality=target_quality)
            processed_bytes = byte_arr.getvalue()
            processed_size = len(processed_bytes)
            logger.debug(
                f"[HistoryController] Качество изображения изменено на {target_quality}. "
                f"Размер: {original_size} -> {processed_size} байт."
            )
            return processed_bytes
        except Exception as e:
            logger.error(f"[HistoryController] Ошибка при обработке качества изображения: {e}", exc_info=True)
            return image_bytes

    def _apply_history_image_quality_reduction(
        self,
        messages: List[Dict[str, Any]],
        image_cfg: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        history_length = len(messages)

        start_index_cfg = int(image_cfg.get('start_index', 25))
        use_percentage = bool(image_cfg.get('use_percentage', False))
        min_quality = int(image_cfg.get('min_quality', 30))
        decrease_rate = int(image_cfg.get('decrease_rate', 5))
        initial_quality = int(image_cfg.get('screen_capture_quality', 75))

        if use_percentage:
            actual_start_index = int(history_length * (start_index_cfg / 100.0))
        else:
            actual_start_index = start_index_cfg

        actual_start_index = max(0, min(actual_start_index, history_length))

        logger.info(
            f"[HistoryController] Снижение качества изображений: длина истории={history_length}, "
            f"старт={actual_start_index}, initial_quality={initial_quality}, "
            f"min_quality={min_quality}, rate={decrease_rate}"
        )

        updated_messages: List[Dict[str, Any]] = []

        for i, msg in enumerate(messages):
            if i < actual_start_index:
                updated_messages.append(msg)
                continue

            # Skip degradation for messages that already have a text description stored.
            # The description replaces the image in history; no base64 to degrade.
            # Supports both new dict format and legacy string.
            _has_desc = bool(msg.get("image_descriptions") or msg.get("image_description"))
            if _has_desc:
                updated_messages.append(msg)
                continue

            if msg.get("role") in ["user", "assistant"] and isinstance(msg.get("content"), list):
                new_content_chunks = []
                image_processed = False

                for item in msg["content"]:
                    if item.get("type") == "image_url" and item.get("image_url") and item["image_url"].get("url"):
                        image_processed = True
                        base64_url = item["image_url"]["url"]
                        if "," in base64_url:
                            img_base64 = base64_url.split(',', 1)[1]
                        else:
                            img_base64 = base64_url
                        try:
                            img_bytes = base64.b64decode(img_base64)
                            relative_index = i - actual_start_index
                            calculated_quality = initial_quality - (decrease_rate * relative_index)
                            target_quality = max(min_quality, calculated_quality)

                            logger.info(
                                f"[HistoryController] Сообщение {i}: rel_idx={relative_index}, "
                                f"calc_quality={calculated_quality}, target_quality={target_quality}"
                            )
                            processed_bytes = self._process_image_quality(img_bytes, target_quality)

                            if processed_bytes:
                                new_content_chunks.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64.b64encode(processed_bytes).decode('utf-8')}"
                                    }
                                })
                            else:
                                logger.info(
                                    f"[HistoryController] Изображение в сообщении {i} удалено (качество <= 0)."
                                )
                        except Exception as e:
                            logger.error(
                                f"[HistoryController] Ошибка при обработке изображения в сообщении {i}: {e}",
                                exc_info=True
                            )
                            new_content_chunks.append(item)
                    else:
                        new_content_chunks.append(item)

                if image_processed:
                    if new_content_chunks:
                        new_msg = msg.copy()
                        new_msg["content"] = new_content_chunks
                        updated_messages.append(new_msg)
                    else:
                        if any(ch.get("type") == "text" for ch in msg["content"]):
                            new_msg = msg.copy()
                            new_msg["content"] = [ch for ch in msg["content"] if ch.get("type") == "text"]
                            updated_messages.append(new_msg)
                        else:
                            logger.info(
                                f"[HistoryController] Сообщение {i} удалено: все изображения удалены и текста нет."
                            )
                else:
                    updated_messages.append(msg)
            else:
                updated_messages.append(msg)

        return updated_messages
    
    def _apply_llm_prefix(self, role: str, speaker: str, target: str, content):
        speaker = str(speaker or "Player")
        target = str(target or "Player")

        prefix = ""
        if role == "user":
            if speaker != "Player":
                if target and target != "Player":
                    prefix = f"[Собеседник: {speaker} -> {target}] "
                else:
                    prefix = f"[Собеседник: {speaker}] "
        elif role == "assistant":
            if target and target != "Player":
                prefix = f"[To: {target}] "

        if not prefix:
            return content

        if isinstance(content, str):
            return prefix + content

        if isinstance(content, list):
            new_chunks = []
            inserted = False
            for it in content:
                if isinstance(it, dict) and it.get("type") == "text" and not inserted:
                    txt = it.get("text")
                    if txt is None:
                        txt = it.get("content", "")
                    it2 = dict(it)
                    if "text" in it2:
                        it2["text"] = prefix + str(txt or "")
                    else:
                        it2["content"] = prefix + str(txt or "")
                    new_chunks.append(it2)
                    inserted = True
                else:
                    new_chunks.append(it)
            if not inserted:
                new_chunks.insert(0, {"type": "text", "text": prefix})
            return new_chunks

        return prefix + str(content)


    def _sanitize_history_for_llm(self, character, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Возвращает историю в формате, безопасном для провайдеров:
        только role/content (+ префиксы по speaker/target для понимания диалога).
        """
        if not messages:
            return []

        owner_id = str(getattr(character, "char_id", "") or "")
        out: List[Dict[str, Any]] = []

        for m in messages:
            if not isinstance(m, dict):
                continue

            role = str(m.get("role") or "")
            if role not in ("user", "assistant", "system", "event"):
                continue

            content = m.get("content")

            speaker = str(m.get("speaker") or m.get("sender") or ("Player" if role == "user" else owner_id) or "Player")
            target = str(m.get("target") or "Player")

            content = self._apply_llm_prefix(role, speaker, target, content)

            # sanitize keys: strict role/content only
            out.append({"role": role, "content": content})

        return out


    def _has_visible_message_content(self, content: Any) -> bool:
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

    def _is_dialog_message(self, message: Dict[str, Any]) -> bool:
        if not isinstance(message, dict):
            return False
        if str(message.get("role") or "") not in ("user", "assistant"):
            return False
        return self._has_visible_message_content(message.get("content"))

    def _count_dialog_messages(self, messages: List[Dict[str, Any]]) -> int:
        return sum(1 for message in messages if self._is_dialog_message(message))

    def _split_history_by_dialog_limit(
        self,
        messages: List[Dict[str, Any]],
        dialog_limit: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if dialog_limit <= 0:
            return list(messages), []

        total_dialog_messages = self._count_dialog_messages(messages)
        if total_dialog_messages <= dialog_limit:
            return [], list(messages)

        omitted_dialog_messages = total_dialog_messages - dialog_limit
        seen_dialog_messages = 0
        for index, message in enumerate(messages):
            if self._is_dialog_message(message):
                seen_dialog_messages += 1
                if seen_dialog_messages >= omitted_dialog_messages:
                    boundary = index + 1
                    return list(messages[:boundary]), list(messages[boundary:])

        return [], list(messages)

    def _take_history_prefix_by_dialog_count(
        self,
        messages: List[Dict[str, Any]],
        dialog_count: int,
    ) -> List[Dict[str, Any]]:
        if dialog_count <= 0:
            return []

        seen_dialog_messages = 0
        for index, message in enumerate(messages):
            if self._is_dialog_message(message):
                seen_dialog_messages += 1
                if seen_dialog_messages >= dialog_count:
                    return list(messages[:index + 1])

        return []
