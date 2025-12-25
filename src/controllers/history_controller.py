from __future__ import annotations
from typing import Dict, Any, List, Optional
import datetime
import base64
from io import BytesIO

from core.events import get_event_bus, Events, Event
from main_logger import logger


class HistoryController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._messages_since_last_periodic_compression: Dict[str, int] = {}
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.History.PREPARE_FOR_PROMPT, self._on_prepare_for_prompt, weak=False)
        self.event_bus.subscribe(Events.History.SAVE_AFTER_RESPONSE, self._on_save_after_response, weak=False)

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

    def _get_character(self, char_id: str):
        try:
            res = self.event_bus.emit_and_wait(
                Events.Model.GET_CHARACTER,
                {'name': char_id},
                timeout=1.0
            )
            return res[0] if res else None
        except Exception as e:
            logger.error(f"[HistoryController] Не удалось получить персонажа '{char_id}': {e}", exc_info=True)
            return None

    def _on_prepare_for_prompt(self, event: Event) -> Dict[str, Any]:
        data = event.data or {}
        char_id: str = data.get('character_id')
        if not char_id:
            logger.error("[HistoryController] PREPARE_FOR_PROMPT без character_id")
            return {'history': []}

        character = self._get_character(char_id)
        if not character:
            logger.error(f"[HistoryController] Персонаж '{char_id}' не найден")
            return {'history': []}

        event_type: str = data.get('event_type', 'chat')
        memory_limit: int = int(data.get('memory_limit', 40))
        is_gm: bool = bool(data.get('is_game_master', False))
        save_missed_history: bool = bool(data.get('save_missed_history', True))
        image_cfg: Dict[str, Any] = data.get('image_quality', {}) or {}

        # НОВОЕ: даём возможность безопасно получить “контекст для подсчёта” без компрессии истории
        disable_compression: bool = bool(data.get('disable_compression', False))

        effective_limit = 8 if is_gm else memory_limit
        if effective_limit <= 0:
            effective_limit = 1

        history_data = character.history_manager.load_history()
        llm_messages_history: List[Dict[str, Any]] = history_data.get("messages", [])

        # ВАЖНО: compression может мутировать историю/память -> отключаем для token_count и похожих запросов
        if not disable_compression:
            llm_messages_history = self._process_history_compression(
                character, llm_messages_history, effective_limit
            )

        missed_messages: List[Dict[str, Any]] = llm_messages_history[:-effective_limit]
        history_limited: List[Dict[str, Any]] = llm_messages_history[-effective_limit:]

        if missed_messages and save_missed_history:
            logger.info(
                f"[HistoryController] Сохраняю {len(missed_messages)} пропущенных сообщений для персонажа {char_id}."
            )
            character.history_manager.save_missed_history(missed_messages)

        if image_cfg.get('enabled', False):
            history_limited = self._apply_history_image_quality_reduction(
                history_limited, image_cfg
            )

        return {'history': history_limited}

    def _on_save_after_response(self, event: Event):
        data = event.data or {}
        char_id: str = data.get('character_id')
        messages: List[Dict[str, Any]] = data.get('messages') or []

        if not char_id:
            logger.error("[HistoryController] SAVE_AFTER_RESPONSE без character_id")
            return False

        character = self._get_character(char_id)
        if not character:
            logger.error(f"[HistoryController] Персонаж '{char_id}' не найден при сохранении истории")
            return False

        try:
            character.save_character_state_to_history(messages)
            logger.debug(f"[HistoryController] История персонажа {char_id} сохранена ({len(messages)} сообщений).")
            return True
        except Exception as e:
            logger.error(f"[HistoryController] Ошибка сохранения истории для {char_id}: {e}", exc_info=True)
            return False

    def _process_history_compression(
        self,
        character,
        llm_messages_history: List[Dict[str, Any]],
        effective_limit: int
    ) -> List[Dict[str, Any]]:
        compress_percent = float(self._get_setting("HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS", 0.85))
        enable_on_limit = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_ON_LIMIT", False))
        enable_periodic = bool(self._get_setting("ENABLE_HISTORY_COMPRESSION_PERIODIC", False))
        periodic_interval = int(self._get_setting("HISTORY_COMPRESSION_PERIODIC_INTERVAL", 20))
        output_target = str(self._get_setting("HISTORY_COMPRESSION_OUTPUT_TARGET", "memory"))

        char_id = getattr(character, "char_id", "Unknown")

        keep_tail = int(effective_limit) if effective_limit and effective_limit > 0 else 1
        keep_tail = max(1, keep_tail)

        min_len_to_trigger = max(1, int(keep_tail * compress_percent))

        if enable_on_limit and len(llm_messages_history) >= min_len_to_trigger and len(llm_messages_history) > keep_tail:
            messages_to_compress = llm_messages_history[:-keep_tail]

            logger.info(
                f"[HistoryController][{char_id}] История близка/превышает лимит. "
                f"Попытка сжать {len(messages_to_compress)} сообщений, сохранить хвост {keep_tail}."
            )

            compressed_summary = self._compress_history(character, messages_to_compress)

            if compressed_summary:
                if output_target == "memory":
                    if hasattr(character, 'memory_system') and character.memory_system:
                        character.memory_system.add_memory(
                            content=compressed_summary,
                            memory_type="summary"
                        )
                        logger.info(f"[HistoryController][{char_id}] Сжатая сводка добавлена в MemorySystem.")
                    else:
                        logger.warning(f"[HistoryController][{char_id}] MemorySystem недоступен для сводки.")

                    llm_messages_history = llm_messages_history[-keep_tail:]

                elif output_target == "history":
                    summary_message = {
                        "role": "system",
                        "content": f"[HISTORY SUMMARY]: {compressed_summary}"
                    }
                    tail_to_keep = max(keep_tail - 1, 0)
                    tail = llm_messages_history[-tail_to_keep:] if tail_to_keep else []
                    llm_messages_history = [summary_message] + tail

                    logger.info(
                        f"[HistoryController][{char_id}] Сжатая сводка добавлена в историю, старые сообщения удалены."
                    )
                else:
                    logger.warning(
                        f"[HistoryController][{char_id}] Неизвестный target для сжатия истории: {output_target}"
                    )

                logger.info(
                    f"[HistoryController][{char_id}] История после on-limit compression: {len(llm_messages_history)} сообщений."
                )
            else:
                logger.warning(f"[HistoryController][{char_id}] Сжатие истории по лимиту не удалось.")

        # --- Periodic compression ---
        if enable_periodic and periodic_interval > 0:
            cnt = self._messages_since_last_periodic_compression.get(char_id, 0) + 1
            self._messages_since_last_periodic_compression[char_id] = cnt

            if cnt >= periodic_interval:
                messages_to_compress = llm_messages_history[:periodic_interval]

                if not messages_to_compress:
                    logger.info(f"[HistoryController][{char_id}] Нет сообщений для периодического сжатия.")
                    self._messages_since_last_periodic_compression[char_id] = 0
                    return llm_messages_history

                logger.info(
                    f"[HistoryController][{char_id}] Периодическое сжатие: попытка сжать "
                    f"{len(messages_to_compress)} сообщений."
                )
                compressed_summary = self._compress_history(character, messages_to_compress)

                if compressed_summary:
                    if output_target == "memory":
                        if hasattr(character, 'memory_system') and character.memory_system:
                            character.memory_system.add_memory(
                                content=compressed_summary,
                                memory_type="summary"
                            )
                            logger.info(f"[HistoryController][{char_id}] Сжатая сводка добавлена в MemorySystem.")
                        else:
                            logger.warning(f"[HistoryController][{char_id}] MemorySystem недоступен для сводки.")

                        # Удаляем сжатый префикс и держим хвост
                        llm_messages_history = llm_messages_history[len(messages_to_compress):]
                        llm_messages_history = llm_messages_history[-keep_tail:]

                    elif output_target == "history":
                        summary_message = {
                            "role": "system",
                            "content": f"[HISTORY SUMMARY]: {compressed_summary}"
                        }
                        remaining = llm_messages_history[len(messages_to_compress):]
                        tail_to_keep = max(keep_tail - 1, 0)
                        tail = remaining[-tail_to_keep:] if tail_to_keep else []
                        llm_messages_history = [summary_message] + tail

                        logger.info(
                            f"[HistoryController][{char_id}] Периодическая сводка добавлена в историю, старые сообщения удалены."
                        )
                    else:
                        logger.warning(
                            f"[HistoryController][{char_id}] Неизвестный target для сжатия истории: {output_target}"
                        )

                    logger.info(
                        f"[HistoryController][{char_id}] История после periodic compression: {len(llm_messages_history)} сообщений."
                    )
                else:
                    logger.warning(f"[HistoryController][{char_id}] Периодическое сжатие истории не удалось.")

                self._messages_since_last_periodic_compression[char_id] = 0

        return llm_messages_history

    def _compress_history(self, character, messages_to_compress: List[Dict[str, Any]]) -> Optional[str]:
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

            full_prompt = prompt_template.replace("{history_messages}", formatted_messages)
            full_prompt = full_prompt.replace("{your character}", getattr(character, "name", "Character"))

            hc_provider = str(self._get_setting("HC_PROVIDER", "Current"))
            preset_id: Optional[int] = None
            if hc_provider != "Current":
                try:
                    preset_id = int(hc_provider)
                    logger.info(f"[HistoryController] Используется пресет для сжатия истории: {preset_id}")
                except ValueError:
                    logger.warning(
                        f"[HistoryController] Некорректный HC_PROVIDER='{hc_provider}', используется текущий пресет."
                    )

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