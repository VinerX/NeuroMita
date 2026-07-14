from __future__ import annotations
from typing import Dict, Any, List, Optional
from pathlib import Path
import datetime
import base64
import json
import time
import threading
from io import BytesIO

from core.character_locks import character_lock
from core.events import get_event_bus, Events, Event
from core.executors import Pools, executors
from core.response_status import response_status_kind
from core.services import services, use
from main_logger import logger
from services.contracts import (
    ApiPresetService,
    GenerationService,
    HistoryService,
    PreparedHistory,
    SettingsService,
    UtilityGenerationRequest,
)


class HistoryController(HistoryService):
    _SUMMARY_TEXT_VAR = "HISTORY_COMPRESSION_SUMMARY"
    _SUMMARY_COUNT_VAR = "HISTORY_COMPRESSION_SUMMARY_COUNT"
    _SUMMARY_SEGMENTS_VAR = "HISTORY_COMPRESSION_SUMMARY_SEGMENTS"
    _DEFAULT_COMPRESSION_PROMPT = (
        "Summarize the conversation below into a compact factual memory for "
        "{current_character_name}. Preserve important events, decisions, "
        "relationships, names, promises, and unresolved topics. Do not invent "
        "facts. If a previous summary exists, merge it without duplicating "
        "information.\n\nPrevious summary:\n{previous_summary}\n\n"
        "Conversation:\n{history_messages}\n\nSummary:"
    )

    # Режимы вывода сжатия истории (HISTORY_COMPRESSION_OUTPUT_TARGET):
    #   layered — слоистая сводка в истории (по умолчанию): новое пишется отдельным
    #             слоем, старые слои изредка схлопываются (без «испорченного телефона»);
    #   history — единый блоб-сводка в истории, переписывается целиком (легаси);
    #   memory  — сводка уходит отдельной памятью в MemorySystem (легаси).
    _DEFAULT_OUTPUT_TARGET = "layered"
    _EXTERNAL_SUMMARY_TARGETS = ("history", "layered")

    def __init__(self):
        self.event_bus = get_event_bus()
        self._messages_since_last_periodic_compression: Dict[str, int] = {}
        self._compression_guard = threading.Lock()
        self._compression_inflight: set[str] = set()
        self._background_compression_inflight: set[str] = set()
        self._background_compression_timers: Dict[str, threading.Timer] = {}
        self._compression_cooldowns: Dict[str, float] = {}
        self._closed = False

        services().register(HistoryService, self, replace=True)
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.History.SAVE_AFTER_RESPONSE, self._on_save_after_response, weak=False)
        self.event_bus.subscribe(Events.History.MESSAGE_COMPLETED, self._on_message_completed, weak=False)

    def close(self) -> None:
        with self._compression_guard:
            if getattr(self, "_closed", False):
                return
            self._closed = True
            timers = tuple(self._background_compression_timers.values())
            self._background_compression_timers.clear()
            self._compression_cooldowns.clear()
        for timer in timers:
            timer.cancel()
        self.event_bus.unsubscribe(
            Events.History.SAVE_AFTER_RESPONSE,
            self._on_save_after_response,
        )
        self.event_bus.unsubscribe(
            Events.History.MESSAGE_COMPLETED,
            self._on_message_completed,
        )

    def _get_setting(self, key: str, default: Any = None) -> Any:
        return use(SettingsService).get(key, default)

    # ------------------------------------------------------------------
    # HistoryService
    # ------------------------------------------------------------------
    def prepare_for_prompt(
        self,
        *,
        character,
        memory_limit: int,
        is_game_master: bool,
        save_missed_history: bool,
        image_quality: Dict[str, Any],
    ) -> PreparedHistory:
        """Готовит историю для промпта. Только чтение и нарезка — никаких LLM-вызовов.

        Сжатие живёт исключительно в фоне (см. _start_background_compression).
        Раньше отсюда мог запуститься синхронный LLM-вызов на 60 секунд, а вызывающий
        ждал 5 секунд по таймауту шины — в результате запрос уходил в модель БЕЗ истории.
        """
        char_id = str(getattr(character, "char_id", "") or "")
        if not char_id:
            raise ValueError("prepare_for_prompt: character без char_id")

        # Реентерабельно: обычно нас уже держит generate_chat того же персонажа.
        # Нужно, чтобы фоновое сжатие не подменило summary/summary_count между
        # чтением сводки и нарезкой окна.
        with character_lock(char_id):
            return self._prepare_for_prompt_locked(
                character, memory_limit, is_game_master, save_missed_history, image_quality
            )

    def _prepare_for_prompt_locked(
        self,
        character,
        memory_limit: int,
        is_game_master: bool,
        save_missed_history: bool,
        image_quality: Dict[str, Any],
    ) -> PreparedHistory:
        char_id = str(getattr(character, "char_id", "") or "")
        effective_limit = 8 if is_game_master else int(memory_limit)
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

        output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", self._DEFAULT_OUTPUT_TARGET))
        use_external_summary = output_target in self._EXTERNAL_SUMMARY_TARGETS
        history_summary = self._get_history_summary(character) if use_external_summary else ""
        summary_count = self._get_history_summary_count(character)
        summary_count = max(0, min(summary_count, len(llm_messages_history)))

        # Окно контекста ограничено всегда: промпт не может распухнуть только из-за
        # того, что фоновое сжатие ещё не догнало историю.
        unsummarized_history = llm_messages_history[summary_count:]
        missed_messages, history_limited = self._split_history_by_dialog_limit(
            unsummarized_history,
            effective_limit,
        )

        if missed_messages and save_missed_history:
            logger.info(f"[HistoryController] Сохраняю {len(missed_messages)} пропущенных сообщений для персонажа {char_id}.")
            character.history_manager.save_missed_history(missed_messages)

        if image_quality.get('enabled', False):
            history_limited = self._apply_history_image_quality_reduction(history_limited, image_quality)

        # ключевая часть: подготовка для LLM (без лишних полей + с префиксами speaker/target)
        history_for_llm = self._sanitize_history_for_llm(character, history_limited)

        return PreparedHistory(messages=history_for_llm, summary=history_summary)

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
    ) -> None:
        compress_percent = float(self._get_setting("HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS", 1.0))
        keep_last_setting = int(self._get_setting("HISTORY_COMPRESSION_KEEP_LAST", 10))
        enable_on_limit = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_ON_LIMIT", True))
        enable_periodic = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_PERIODIC", False))
        periodic_interval = int(self._get_setting("HISTORY_COMPRESSION_PERIODIC_INTERVAL", 20))
        output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", self._DEFAULT_OUTPUT_TARGET))

        char_id = getattr(character, "char_id", "Unknown")

        # Окно контекста — сколько последних сообщений модель видит в промпте.
        context_limit = int(effective_limit) if effective_limit and effective_limit > 0 else 1
        context_limit = max(1, context_limit)

        # keep_last — сколько сообщений остаётся НЕсжатыми после сжатия (абсолютная величина,
        # напр. 10: «дошло до 40 → сжалось до 10»). Больше окна контекста держать бессмысленно.
        keep_last = max(1, keep_last_setting)
        keep_last = min(keep_last, context_limit)

        # Порог запуска сжатия: процент от окна контекста, допускается > 1 (1.2 → 48 при 40).
        # Раньше процент почти не работал: сверх него требовалось ещё dialog_count > context_limit.
        trigger_at = max(1, round(context_limit * compress_percent))
        trigger_at = max(trigger_at, keep_last + 1)

        use_external_summary = output_target in self._EXTERNAL_SUMMARY_TARGETS
        source_messages = llm_messages_history[summary_count:]
        plan = self._build_compression_plan(
            source_messages=source_messages,
            keep_last=keep_last,
            trigger_at=trigger_at,
            enable_on_limit=enable_on_limit,
            enable_periodic=enable_periodic,
            periodic_interval=periodic_interval,
            char_id=char_id,
        )
        if not plan:
            return

        messages_to_compress, reason = plan
        if not messages_to_compress:
            return

        logger.info(
            f"[HistoryController][{char_id}] {reason}: попытка сжать "
            f"{len(messages_to_compress)} сообщений."
        )
        is_layered = (output_target == "layered")
        # В layered-режиме прошлую сводку в промпт НЕ подаём: суммируем только новый
        # кусок и дописываем его отдельным слоем — это и убирает «испорченный телефон».
        chunk_previous_summary = "" if is_layered else (history_summary if use_external_summary else "")
        compressed_summary = self._compress_history_singleflight(
            character,
            messages_to_compress,
            previous_summary=chunk_previous_summary,
        )

        if not compressed_summary:
            logger.warning(f"[HistoryController][{char_id}] Сжатие истории не удалось.")
            return

        if is_layered:
            _, new_count = self._apply_layered_compression_result(
                character,
                compressed_summary=compressed_summary,
                summary_count=summary_count,
                compressed_count=len(messages_to_compress),
                history_len=len(llm_messages_history),
            )
        else:
            _, new_count = self._apply_compression_result(
                character,
                output_target=output_target,
                compressed_summary=compressed_summary,
                previous_summary=history_summary,
                summary_count=summary_count,
                compressed_count=len(messages_to_compress),
                history_len=len(llm_messages_history),
            )

        # Сжатие реально применилось (summary_count продвинулся) — сообщаем UI,
        # чтобы живые счётчики (напр. «сообщений в окне» в песочнице) обновились.
        if new_count != summary_count:
            self._emit_compressed(char_id)

        if reason == "Periodic compression":
            self._messages_since_last_periodic_compression[char_id] = 0

    def _emit_compressed(self, char_id: str) -> None:
        try:
            self.event_bus.emit(Events.History.COMPRESSED, {"character_id": char_id})
        except Exception:
            pass

    def _build_compression_plan(
        self,
        *,
        source_messages: List[Dict[str, Any]],
        keep_last: int,
        trigger_at: int,
        enable_on_limit: bool,
        enable_periodic: bool,
        periodic_interval: int,
        char_id: str,
    ) -> tuple[List[Dict[str, Any]], str] | None:
        dialog_count = self._count_dialog_messages(source_messages)
        if enable_on_limit and dialog_count >= trigger_at and dialog_count > keep_last:
            messages_to_compress, _ = self._split_history_by_dialog_limit(source_messages, keep_last)
            if messages_to_compress:
                return messages_to_compress, "On-limit compression"

        if enable_periodic and periodic_interval > 0:
            cnt = self._messages_since_last_periodic_compression.get(char_id, 0) + 1
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

    def _start_background_compression(self, character) -> None:
        if getattr(self, "_closed", False):
            return
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        delay_sec = self._compression_background_delay_seconds()
        remaining_cooldown = self._get_compression_cooldown_remaining(char_id)
        self._schedule_background_compression(character, delay_sec=max(delay_sec, remaining_cooldown))

    def _schedule_background_compression(self, character, *, delay_sec: float) -> None:
        if getattr(self, "_closed", False):
            return
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        timer = threading.Timer(
            max(0.0, float(delay_sec)),
            self._run_scheduled_background_compression,
            args=(character,),
        )
        timer.daemon = True
        timer.name = f"history-compress-delay-{char_id}"

        with self._compression_guard:
            if getattr(self, "_closed", False):
                return
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
            if self._closed:
                return
            if char_id in self._background_compression_inflight:
                should_reschedule = True
            else:
                self._background_compression_inflight.add(char_id)
        if should_reschedule:
            reschedule_delay = max(1.0, self._compression_background_delay_seconds())
            self._schedule_background_compression(character, delay_sec=reschedule_delay)
            return

        # Единый фоновый LLM-пул (concurrency=1): сжатие и graph extraction
        # больше не конкурируют друг с другом и не плодят ad-hoc потоки.
        try:
            executors().try_submit(
                Pools.BACKGROUND_LLM, self._run_post_response_compression, character
            )
        except Exception as e:
            logger.warning(f"[HistoryController][{char_id}] Не удалось поставить сжатие в очередь: {e}")
            with self._compression_guard:
                self._background_compression_inflight.discard(char_id)

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

            output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", self._DEFAULT_OUTPUT_TARGET))
            history_summary = self._get_history_summary(character) if output_target in self._EXTERNAL_SUMMARY_TARGETS else ""
            summary_count = max(0, min(self._get_history_summary_count(character), len(llm_messages_history)))

            self._process_history_compression(
                character,
                llm_messages_history,
                effective_limit,
                history_summary=history_summary,
                summary_count=summary_count,
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
    ) -> Optional[str]:
        configured_template_path = str(self._get_setting(
            "HISTORY_COMPRESSION_PROMPT_TEMPLATE",
            "Prompts/System/compression_prompt.txt",
        ) or "").strip()
        prompt_template = ""
        resolved_template_path = configured_template_path
        if configured_template_path:
            try:
                from core.app_paths import base_dir

                candidate = Path(configured_template_path).expanduser()
                if not candidate.is_absolute():
                    candidate = base_dir() / candidate
                resolved_template_path = str(candidate.resolve())
                prompt_template = candidate.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning(
                    "[HistoryController] Compression template unavailable at %s; "
                    "using built-in fallback: %s",
                    resolved_template_path,
                    exc,
                )
        if not prompt_template:
            prompt_template = self._DEFAULT_COMPRESSION_PROMPT

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
                    # Look up by display name via ApiPresetService.
                    try:
                        meta = use(ApiPresetService).list_meta()
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
                messages_to_compress=messages_to_compress,
                previous_summary=previous_summary_trimmed,
                full_prompt=full_prompt,
                preset_id=preset_id,
                max_attempts=max_attempts,
                base_retry_delay=base_retry_delay,
                max_retry_delay=max_retry_delay,
                request_timeout=request_timeout,
            )

        except Exception as e:
            logger.error(f"[HistoryController] Ошибка при сжатии истории: {e}", exc_info=True)
            return None

    def _run_compression_request(
        self,
        *,
        character,
        messages_to_compress: List[Dict[str, Any]],
        previous_summary: str,
        full_prompt: str,
        preset_id: Optional[int],
        max_attempts: int,
        base_retry_delay: float,
        max_retry_delay: float,
        request_timeout: float,
    ) -> Optional[str]:
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        generation = use(GenerationService)
        last_failure = None

        for attempt in range(1, max_attempts + 1):
            with response_status_kind("compression"):
                result = generation.generate_utility(
                    UtilityGenerationRequest(
                        prompt=full_prompt,
                        character_id=char_id,
                        kind="compress",
                        preset_id=preset_id,
                        max_attempts=1,
                        retry_delay=0.0,
                        request_timeout=request_timeout,
                    )
                )

            if result.ok and result.text.strip():
                self._clear_compression_cooldown(char_id)
                logger.info("[HistoryController] History compressed successfully.")
                return result.text.strip()

            last_failure = result
            error_text = (result.details or result.error).strip()
            logger.warning(
                f"[HistoryController][{char_id}] Compression attempt {attempt}/{max_attempts} failed: "
                f"status={result.status_code}, retryable={result.retryable}, details={error_text or 'n/a'}"
            )

            if not result.retryable:
                break

            delay_sec = self._coerce_positive_float(result.retry_after_sec)
            if delay_sec is None:
                delay_sec = min(max_retry_delay, base_retry_delay * (2 ** (attempt - 1)))
            self._set_compression_cooldown(char_id, delay_sec)

            if attempt < max_attempts:
                time.sleep(delay_sec)

        logger.warning("[HistoryController] History compression finished without success.")
        if self._get_compression_cooldown_remaining(char_id) > 0:
            self._schedule_background_compression(
                character,
                delay_sec=max(
                    self._compression_background_delay_seconds(),
                    self._get_compression_cooldown_remaining(char_id),
                ),
            )
        failure_details = ""
        if last_failure is not None:
            failure_details = (last_failure.details or last_failure.error).strip()
        fallback_summary = self._build_local_compression_fallback(
            character,
            messages_to_compress,
            previous_summary=previous_summary,
            failure_details=failure_details,
        )
        if fallback_summary:
            self._clear_compression_cooldown(char_id)
            return fallback_summary
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
        # Короткая критическая секция: сам LLM-вызов сжатия идёт вне блокировки,
        # иначе генерация ждала бы его минуту.
        try:
            with character_lock(getattr(character, "char_id", "") or ""):
                character.set_variable(self._SUMMARY_TEXT_VAR, str(summary or "").strip())
                character.set_variable(self._SUMMARY_COUNT_VAR, max(0, int(summary_count or 0)))
                if hasattr(character, "flush_variables"):
                    character.flush_variables()
        except Exception as e:
            logger.warning(f"[HistoryController] Не удалось сохранить состояние summary: {e}", exc_info=True)

    # ── Слоистая сводка (layered) ─────────────────────────────────────────────

    def _now_iso(self) -> str:
        try:
            return datetime.datetime.now().isoformat(timespec="seconds")
        except Exception:
            return ""

    def _load_summary_segments(self, character) -> List[Dict[str, Any]]:
        """Слои сводки layered-режима. Если их ещё нет — миграция из старого блоба."""
        try:
            raw = character.get_variable(self._SUMMARY_SEGMENTS_VAR, None)
        except Exception:
            raw = None

        segments: List[Dict[str, Any]] = []
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    segments = [s for s in parsed if isinstance(s, dict)]
            except Exception:
                segments = []
        elif isinstance(raw, list):
            segments = [s for s in raw if isinstance(s, dict)]

        if segments:
            return segments

        # миграция: старый одиночный блоб-сводка → один слой
        blob = self._get_history_summary(character)
        if blob:
            return [{
                "text": blob,
                "msg_count": self._get_history_summary_count(character),
                "level": 1,
                "created": self._now_iso(),
            }]
        return []

    def _render_summary_segments(self, segments: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for s in segments:
            if not isinstance(s, dict):
                continue
            text = str(s.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()

    def _set_summary_segments_state(self, character, segments, rendered, summary_count) -> None:
        try:
            with character_lock(getattr(character, "char_id", "") or ""):
                character.set_variable(self._SUMMARY_SEGMENTS_VAR, json.dumps(segments, ensure_ascii=False))
                # блоб держим синхронным с рендером слоёв — для рендера [HISTORY SUMMARY]
                # и обратной совместимости (_get_history_summary читает именно его).
                character.set_variable(self._SUMMARY_TEXT_VAR, str(rendered or "").strip())
                character.set_variable(self._SUMMARY_COUNT_VAR, max(0, int(summary_count or 0)))
                if hasattr(character, "flush_variables"):
                    character.flush_variables()
        except Exception as e:
            logger.warning(f"[HistoryController] Не удалось сохранить слои сводки: {e}", exc_info=True)

    def _maybe_rollup_segments(
        self, character, segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Роллап: когда слоёв слишком много — схлопнуть самые старые K в один.

        Это единственное место, где происходит повторная суммаризация, и то —
        редко и только над старым. Свежие слои остаются нетронутыми.
        """
        max_segments = int(self._get_setting("HISTORY_COMPRESSION_LAYERED_MAX_SEGMENTS", 6))
        batch = int(self._get_setting("HISTORY_COMPRESSION_LAYERED_ROLLUP_BATCH", 3))
        if max_segments <= 0 or batch <= 1:
            return segments
        if len(segments) <= max_segments:
            return segments

        batch = min(batch, len(segments) - 1)  # хотя бы один свежий слой должен остаться
        if batch <= 1:
            return segments

        oldest = segments[:batch]
        rest = segments[batch:]
        char_id = getattr(character, "char_id", "Unknown") or "Unknown"
        logger.info(f"[HistoryController][{char_id}] Роллап {len(oldest)} старых слоёв сводки в один.")

        merged_text = self._compress_history_singleflight(
            character,
            [{"role": "system", "content": str(s.get("text") or "")} for s in oldest],
            previous_summary="",
        )
        if not merged_text or not str(merged_text).strip():
            logger.warning(f"[HistoryController][{char_id}] Роллап слоёв не удался — оставляю как есть.")
            return segments

        merged = {
            "text": str(merged_text).strip(),
            "msg_count": sum(int(s.get("msg_count") or 0) for s in oldest),
            "level": max((int(s.get("level") or 0) for s in oldest), default=0) + 1,
            "created": self._now_iso(),
        }
        return [merged] + rest

    def _apply_layered_compression_result(
        self,
        character,
        *,
        compressed_summary: str,
        summary_count: int,
        compressed_count: int,
        history_len: int,
    ) -> tuple[str, int]:
        segments = self._load_summary_segments(character)
        segments.append({
            "text": str(compressed_summary or "").strip(),
            "msg_count": int(compressed_count),
            "level": 0,
            "created": self._now_iso(),
        })
        segments = self._maybe_rollup_segments(character, segments)
        new_count = min(history_len, summary_count + compressed_count)
        rendered = self._render_summary_segments(segments)
        self._set_summary_segments_state(character, segments, rendered, new_count)
        logger.info(
            f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
            f"Layered summary: {len(segments)} слоёв, свёрнуто {new_count} сообщений."
        )
        return rendered, new_count

    def _truncate_text_for_prompt(self, text: str, limit: int) -> str:
        if limit <= 0:
            return ""

        text = str(text or "").strip()
        if len(text) <= limit:
            return text

        keep = max(0, limit - len("\n...[truncated]"))
        return text[:keep].rstrip() + "\n...[truncated]"

    def _content_to_plain_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "text":
                    value = item.get("text")
                    if value is None:
                        value = item.get("content", "")
                    text = str(value or "").strip()
                    if text:
                        parts.append(text)
                elif item_type == "image_url":
                    parts.append("[image]")
            return " ".join(part for part in parts if part).strip()

        return str(content or "").strip()

    def _build_local_compression_fallback(
        self,
        character,
        messages_to_compress: List[Dict[str, Any]],
        *,
        previous_summary: str = "",
        failure_details: str = "",
    ) -> Optional[str]:
        if not bool(self._get_setting("HISTORY_COMPRESSION_LOCAL_FALLBACK_ENABLED", True)):
            return None

        summary_limit = max(200, int(self._get_setting("HISTORY_COMPRESSION_LOCAL_FALLBACK_MAX_CHARS", 4000)))
        per_message_limit = max(40, int(self._get_setting("HISTORY_COMPRESSION_LOCAL_FALLBACK_MESSAGE_MAX_CHARS", 220)))
        max_messages = max(1, int(self._get_setting("HISTORY_COMPRESSION_LOCAL_FALLBACK_MAX_MESSAGES", 24)))

        lines: List[str] = []
        previous_summary = str(previous_summary or "").strip()
        if previous_summary:
            lines.append(
                self._truncate_text_for_prompt(
                    previous_summary,
                    min(summary_limit // 2, max(200, per_message_limit * 3)),
                )
            )

        assistant_name = str(getattr(character, "name", "") or "Character")
        for msg in messages_to_compress:
            if not isinstance(msg, dict):
                continue

            text = self._content_to_plain_text(msg.get("content"))
            if not text:
                continue

            role = str(msg.get("role") or "")
            if role == "user":
                speaker = "Player"
            elif role == "assistant":
                speaker = assistant_name
            elif role == "system":
                speaker = "System"
            else:
                speaker = role.title() or "Event"

            lines.append(f"{speaker}: {self._truncate_text_for_prompt(text, per_message_limit)}")
            if len(lines) >= max_messages + (1 if previous_summary else 0):
                break

        fallback_summary = "\n".join(line for line in lines if line).strip()
        if not fallback_summary:
            return None

        fallback_summary = self._truncate_text_for_prompt(fallback_summary, summary_limit)
        logger.warning(
            f"[HistoryController][{getattr(character, 'char_id', 'Unknown')}] "
            f"Using local compression fallback after provider failure: {failure_details or 'n/a'}"
        )
        return fallback_summary

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
