# src/controllers/chat_controller.py
import os
import asyncio
import tempfile
import base64
from typing import Any

from main_logger import logger
from core.events import get_event_bus, Events, Event
from managers.task_manager import TaskStatus
from core.request_policy import RequestPolicy, resolve_policy


class ThinkTagStreamFilter:
    """
    Streaming-time filter that prevents <think>...</think> from being echoed
    into the normal assistant stream output. Accumulates think text separately.

    Note: simple exact-tag matching (<think>, </think>) to keep it predictable.
    """
    START = "<think>"
    END = "</think>"

    def __init__(self, on_think_chunk=None):
        self._buf = ""
        self._in_think = False
        self._think_parts: list[str] = []
        self._keep_tail = max(len(self.START), len(self.END)) - 1
        self.on_think_chunk = on_think_chunk

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buf += str(chunk)
        out = ""

        while True:
            if self._in_think:
                idx = self._buf.find(self.END)
                if idx == -1:
                    if len(self._buf) > self._keep_tail:
                        new_think = self._buf[:-self._keep_tail]
                        self._think_parts.append(new_think)
                        if self.on_think_chunk:
                            self.on_think_chunk(new_think)
                        self._buf = self._buf[-self._keep_tail:]
                    break
                new_think = self._buf[:idx]
                self._think_parts.append(new_think)
                if self.on_think_chunk:
                    self.on_think_chunk(new_think)
                self._buf = self._buf[idx + len(self.END):]
                self._in_think = False
            else:
                idx = self._buf.find(self.START)
                if idx == -1:
                    if len(self._buf) > self._keep_tail:
                        out += self._buf[:-self._keep_tail]
                        self._buf = self._buf[-self._keep_tail:]
                    break
                out += self._buf[:idx]
                self._buf = self._buf[idx + len(self.START):]
                self._in_think = True

        return out

    def flush_visible(self) -> str:
        """Вызывается в конце потока для сбора оставшегося видимого текста."""
        if self._in_think:
            if self._buf:
                self._think_parts.append(self._buf)
            self._in_think = False
            self._buf = ""
        return ""

    def think_text(self) -> str:
        """Возвращает весь собранный текст размышлений."""
        return "".join(self._think_parts).strip()


class ChatController:
    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.llm_processing = False

        self.staged_images = []
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Chat.SEND_MESSAGE, self._on_send_message, weak=False)
        self.event_bus.subscribe(Events.Model.GET_LLM_PROCESSING_STATUS, self._on_get_llm_processing_status, weak=False)
        self.event_bus.subscribe("send_periodic_image_request", self._on_send_periodic_image_request, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_CHAT, self._on_clear_chat, weak=False)

        self.event_bus.subscribe(Events.Chat.STAGE_IMAGE, self._on_stage_image, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_STAGED_IMAGES, self._on_clear_staged_images, weak=False)

    def _normalize_character_id(self, data: dict) -> str | None:
        if not isinstance(data, dict):
            return None
        return data.get("character_id") or data.get("char_id") or data.get("character") or None

    def _normalize_sender(self, data: dict) -> str:
        if not isinstance(data, dict):
            return "Player"
        return str(data.get("sender") or data.get("from") or "Player")

    def _normalize_participants(self, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",")]
            value = [p for p in parts if p]

        if not isinstance(value, list):
            return []

        out: list[str] = []
        seen = set()
        for x in value:
            s = str(x or "").strip()
            if not s:
                continue
            if s.lower() == "player":
                s = "Player"
            if s in seen:
                continue
            out.append(s)
            seen.add(s)
        return out

    def _resolve_character_name(self, character_id: str | None) -> str:
        if not character_id:
            return ""
        try:
            res = self.event_bus.emit_and_wait(
                Events.Character.GET,
                {"character_id": str(character_id)},
                timeout=0.5
            )
            ch = res[0] if res else None
            name = getattr(ch, "name", None)
            if name:
                return str(name)
        except Exception:
            pass
        return str(character_id)

    async def async_send_message(
        self,
        user_input: str,
        system_input: str = "",
        image_data: list[bytes] | None = None,
        task_uid: str | None = None,
        event_type: str | None = None,
        character_id: str | None = None,
        sender: str = "Player",
        participants: list[str] | None = None,
        req_id: str | None = None,
        origin_message_id: str | None = None,
        policy: dict | None = None,
    ):
        eff_policy = None
        try:
            self.llm_processing = True

            effective_event_type = str(event_type or "chat")
            eff_policy = RequestPolicy.from_dict(policy) if isinstance(policy, dict) else resolve_policy(model_event_type=effective_event_type)

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.PENDING
                })

            is_streaming = bool(self.settings.get("ENABLE_STREAMING", False)) and eff_policy.allow_streaming and eff_policy.echo_to_ui

            show_think_in_gui = bool(self.settings.get("SHOW_THINK_IN_GUI", False))
            effective_character_name = self._resolve_character_name(character_id)
            
            self._stream_current_role = None

            def on_think_chunk(think_chunk: str):
                if self._stream_current_role != "think":
                    # При первом чанке размышлений подготавливаем UI
                    self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI, {
                        "character_id": character_id or "",
                        "character_name": effective_character_name,
                        "speaker_name": effective_character_name,
                        "role": "think"
                    })
                    self._stream_current_role = "think"
                
                # Отправляем чанки размышлений в UI в реальном времени
                self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {"chunk": think_chunk, "role": "think"})

            stream_think_filter = ThinkTagStreamFilter(on_think_chunk=on_think_chunk if show_think_in_gui else None) if is_streaming else None

            def stream_callback_handler(chunk: str):
                if not eff_policy.echo_to_ui:
                    return
                
                chunk_str = str(chunk or "")
                if not chunk_str:
                    return

                if stream_think_filter is None:
                    if self._stream_current_role != "assistant":
                        self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI, {
                            "character_id": character_id or "",
                            "character_name": effective_character_name,
                            "speaker_name": effective_character_name,
                            "role": "assistant"
                        })
                        self._stream_current_role = "assistant"
                    self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {"chunk": chunk_str, "role": "assistant"})
                    return
                
                visible = stream_think_filter.feed(chunk_str)
                if visible:
                    if self._stream_current_role != "assistant":
                        self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI, {
                            "character_id": character_id or "",
                            "character_name": effective_character_name,
                            "speaker_name": effective_character_name,
                            "role": "assistant"
                        })
                        self._stream_current_role = "assistant"
                    
                    self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {"chunk": visible, "role": "assistant"})

            if image_data:
                prepared: list[bytes] = []
                for img in image_data:
                    if isinstance(img, bytes):
                        prepared.append(img)
                    elif isinstance(img, str):
                        try:
                            b64 = img.split(",", 1)[-1]
                            prepared.append(base64.b64decode(b64))
                        except Exception:
                            continue
                image_data = prepared if prepared else None

            response_result = self.event_bus.emit_and_wait(
                Events.Model.GENERATE_RESPONSE,
                {
                    "user_input": user_input,
                    "system_input": system_input,
                    "image_data": image_data,
                    "stream_callback": stream_callback_handler if is_streaming else None,
                    "message_id": task_uid,
                    "event_type": effective_event_type,
                    "character_id": character_id,
                    "sender": sender,
                    "participants": participants or [],
                    "req_id": req_id,
                    "origin_message_id": origin_message_id,
                    "policy": eff_policy.to_dict(),
                },
                timeout=600.0
            )

            payload = response_result[0] if response_result else None
            if not payload:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.FAILED_ON_GENERATION,
                        "error": "Failed to generate response"
                    })
                self.llm_processing = False
                if eff_policy.echo_to_ui:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": "Превышено время ожидания ответа"})
                return None

            target = "Player"
            think_text = None
            if isinstance(payload, dict):
                response_text = payload.get("text")
                voice_profile = payload.get("voice_profile")
                effective_character_id = payload.get("character_id") or character_id
                target = str(payload.get("target") or "Player")
                think_text = payload.get("think")
            else:
                response_text = payload
                voice_profile = None
                effective_character_id = character_id

            if not response_text:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.FAILED_ON_GENERATION,
                        "error": "Empty response"
                    })
                self.llm_processing = False
                if eff_policy.echo_to_ui:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": "Пустой ответ модели"})
                return None

            effective_character_name = self._resolve_character_name(effective_character_id)

            if is_streaming and eff_policy.echo_to_ui:
                # Мы НЕ вызываем PREPARE_STREAM_UI здесь, так как он будет вызван
                # динамически в stream_callback_handler при получении первого чанка
                # (либо для think, либо для assistant).
                pass

            # If we filtered streaming output, we may have a small tail held back
            if is_streaming and eff_policy.echo_to_ui and stream_think_filter is not None:
                tail = stream_think_filter.flush_visible()
                if tail:
                    self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {"chunk": tail})

            if response_text and self.settings.get("USE_VOICEOVER") and eff_policy.allow_voiceover:
                if isinstance(voice_profile, dict):
                    is_game_master = (voice_profile.get("character_id") == "GameMaster")
                    if (not is_game_master) or bool(self.settings.get("GM_VOICE", False)):
                        if task_uid:
                            self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                                "uid": task_uid,
                                "status": TaskStatus.VOICING,
                                "result": {"response": response_text, "target": target}
                            })

                        speaker = voice_profile.get("silero_command", "")
                        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
                            speaker = voice_profile.get("miku_tts_name", "Player")

                        self.event_bus.emit(Events.Audio.VOICEOVER_REQUESTED, {
                            "text": response_text,
                            "speaker": speaker,
                            "task_uid": task_uid,
                            "character_id": effective_character_id,
                            "voice_profile": voice_profile,
                            "target": target,
                        })
                    else:
                        if task_uid:
                            self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                                "uid": task_uid,
                                "status": TaskStatus.SUCCESS,
                                "result": {"response": response_text, "target": target}
                            })
                else:
                    if task_uid:
                        self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                            "uid": task_uid,
                            "status": TaskStatus.SUCCESS,
                            "result": {"response": response_text, "target": target}
                        })
            else:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.SUCCESS,
                        "result": {"response": response_text, "target": target}
                    })

            if is_streaming and eff_policy.echo_to_ui:
                self.event_bus.emit(Events.GUI.FINISH_STREAM_UI)
                # При стриминге весь текст (think и assistant) уже выведен
                # в UI в реальном времени. Повторный UPDATE_CHAT_UI не нужен.
            elif (not is_streaming) and eff_policy.echo_to_ui:
                # Для не-стриминга отправляем think перед основным ответом
                if show_think_in_gui and think_text:
                    self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                        "role": "think",
                        "response": [
                            {"type": "meta", "speaker": effective_character_name or ""},
                            {"type": "text", "text": think_text.strip()},
                        ],
                        "is_initial": False,
                        "emotion": "",
                        "character_id": effective_character_id or "",
                        "character_name": effective_character_name or "",
                        "speaker_name": effective_character_name or ""
                    })
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                    "role": "assistant",
                    "response": response_text if response_text is not None else "...",
                    "is_initial": False,
                    "emotion": "",
                    "character_id": effective_character_id or "",
                    "character_name": effective_character_name or "",
                    "speaker_name": effective_character_name or "",
                    "target": target,
                })
            self.event_bus.emit(Events.GUI.UPDATE_STATUS)
            self.event_bus.emit(Events.GUI.UPDATE_DEBUG_INFO)
            self.event_bus.emit(Events.GUI.UPDATE_TOKEN_COUNT)

            self.llm_processing = False
            return response_text

        except asyncio.TimeoutError:
            logger.warning("Тайм-аут: генерация ответа заняла слишком много времени.")
            self.llm_processing = False
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.FAILED_ON_GENERATION,
                    "error": "Timeout"
                })
            if eff_policy and eff_policy.echo_to_ui:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": "Превышено время ожидания ответа"})
            return "Произошла ошибка при обработке вашего сообщения."
        except Exception as e:
            logger.error(f"Ошибка в async_send_message: {e}", exc_info=True)
            self.llm_processing = False
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.FAILED_ON_GENERATION,
                    "error": str(e)
                })
            if eff_policy and eff_policy.echo_to_ui:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": f"Ошибка: {str(e)[:50]}..."})
            return "Произошла ошибка при обработке вашего сообщения."

    def _on_send_message(self, event: Event):
        data = event.data or {}
        user_input = data.get("user_input", "")
        system_input = data.get("system_input", "")
        image_data = data.get("image_data", [])
        task_uid = data.get("task_uid")
        event_type = str(data.get("event_type") or "chat")
        character_id = self._normalize_character_id(data)
        sender = self._normalize_sender(data)
        participants = self._normalize_participants(data.get("participants"))
        req_id = data.get("req_id")
        origin_message_id = data.get("origin_message_id")
        policy = data.get("policy")

        if image_data:
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)

        loop_res = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_res[0] if loop_res else None

        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(
                self.async_send_message(
                    user_input=user_input,
                    system_input=system_input,
                    image_data=image_data,
                    task_uid=task_uid,
                    event_type=event_type,
                    character_id=character_id,
                    sender=sender,
                    participants=participants,
                    req_id=req_id,
                    origin_message_id=origin_message_id,
                    policy=policy,
                ),
                loop
            )
            try:
                return fut.result(timeout=600)
            except Exception as e:
                logger.error(f"async_send_message failed: {e}", exc_info=True)
                return None
        else:
            return asyncio.run(
                self.async_send_message(
                    user_input=user_input,
                    system_input=system_input,
                    image_data=image_data,
                    task_uid=task_uid,
                    event_type=event_type,
                    character_id=character_id,
                    sender=sender,
                    participants=participants,
                    req_id=req_id,
                    origin_message_id=origin_message_id,
                    policy=policy,
                )
            )

    def _on_get_llm_processing_status(self, event: Event):
        return self.llm_processing

    def _on_send_periodic_image_request(self, event: Event):
        data = event.data or {}

        if data.get("image_data"):
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)

        character_id = self._normalize_character_id(data)
        sender = self._normalize_sender(data)
        participants = self._normalize_participants(data.get("participants"))

        coro = self.async_send_message(
            user_input=data.get("user_input", ""),
            system_input=data.get("system_input", ""),
            image_data=data.get("image_data", []),
            task_uid=data.get("task_uid"),
            event_type=data.get("event_type"),
            character_id=character_id,
            sender=sender,
            participants=participants,
            policy=data.get("policy"),
        )

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            "coroutine": coro,
            "callback": None
        })

    def _on_clear_chat(self, event: Event):
        pass

    def stage_image_bytes(self, img_bytes: bytes) -> int:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="nm_clip_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(img_bytes)

        self.staged_images.append(tmp_path)
        logger.info(f"Clipboard image staged: {tmp_path}")
        return len(self.staged_images)

    def clear_staged_images(self):
        self.staged_images.clear()

    def _on_stage_image(self, event: Event):
        image_data = (event.data or {}).get("image_data")
        if image_data:
            if isinstance(image_data, bytes):
                self.stage_image_bytes(image_data)
            elif isinstance(image_data, str):
                self.staged_images.append(image_data)

    def _on_clear_staged_images(self, event: Event):
        self.clear_staged_images()