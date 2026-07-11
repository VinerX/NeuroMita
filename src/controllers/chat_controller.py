# src/controllers/chat_controller.py
import os
import tempfile
import base64
import threading
import uuid
import datetime
from typing import Any

from main_logger import logger
from core.events import Event, EventDelivery, Events, get_event_bus
from core.executors import Pools, PoolSaturated, executors
from core.services import use
from managers.task_manager import TaskStatus
from core.request_policy import RequestPolicy, resolve_policy
from services.contracts import (
    CharacterRegistry,
    ChatGenerationRequest,
    ChatGenerationResult,
    GenerationService,
)


class StructuredJsonStreamFilter:
    """
    Streaming-time filter for structured JSON responses.

    When the model returns a JSON object (structured output), the raw stream
    contains JSON syntax rather than readable text.  This filter extracts the
    values of every ``"text"`` key found in the stream (i.e. segment texts)
    and emits them in order, discarding all JSON scaffolding.

    Activated lazily: call feed() with the first chunk; if it starts with ``{``
    the filter enters JSON mode automatically.
    """

    KEY = '"text"'

    def __init__(self):
        self._buf = ""
        self._state = "SCANNING"   # SCANNING | EXPECT_COLON | EXPECT_QUOTE | IN_VALUE
        self._escape_next = False
        self._json_mode = False    # set True once we see the leading {

    def is_json_mode(self) -> bool:
        return self._json_mode

    def feed(self, chunk: str) -> str:
        """Return text to display; returns raw chunk unchanged if not in JSON mode."""
        self._buf += str(chunk)

        # Detect JSON mode on the very first non-empty feed.
        # Some models wrap JSON in a markdown code fence (```json\n{...}\n```).
        # Strip that prefix before checking for the leading '{'.
        if not self._json_mode:
            stripped = self._buf.lstrip()
            if not stripped:
                return ""
            # Skip optional ```json / ``` fence header
            if stripped.startswith("```"):
                newline = stripped.find("\n")
                if newline == -1:
                    # Haven't received the newline yet — wait for more data
                    return ""
                stripped = stripped[newline + 1:].lstrip()
                if not stripped:
                    return ""
            if stripped[0] == "{":
                # Advance _buf to the actual '{' so the parser starts correctly
                self._buf = stripped
                self._json_mode = True
            else:
                # Not JSON — pass through unchanged
                out = self._buf
                self._buf = ""
                return out

        out = ""
        while self._buf:
            if self._state == "SCANNING":
                pos = self._buf.find(self.KEY)
                if pos == -1:
                    keep = len(self.KEY) - 1
                    if len(self._buf) > keep:
                        self._buf = self._buf[-keep:]
                    break
                self._buf = self._buf[pos + len(self.KEY):]
                self._state = "EXPECT_COLON"

            elif self._state == "EXPECT_COLON":
                c = self._buf[0]
                if c in " \t\n\r":
                    self._buf = self._buf[1:]
                elif c == ":":
                    self._buf = self._buf[1:]
                    self._state = "EXPECT_QUOTE"
                else:
                    self._state = "SCANNING"

            elif self._state == "EXPECT_QUOTE":
                c = self._buf[0]
                if c in " \t\n\r":
                    self._buf = self._buf[1:]
                elif c == '"':
                    self._buf = self._buf[1:]
                    self._state = "IN_VALUE"
                    self._escape_next = False
                else:
                    self._state = "SCANNING"

            elif self._state == "IN_VALUE":
                c = self._buf[0]
                self._buf = self._buf[1:]
                if self._escape_next:
                    self._escape_next = False
                    if c == "n":
                        out += "\n"
                    elif c == "t":
                        out += "\t"
                    elif c in ('"', "\\", "/"):
                        out += c
                    elif c == "u":
                        if len(self._buf) >= 4:
                            try:
                                out += chr(int(self._buf[:4], 16))
                            except ValueError:
                                out += "\\u" + self._buf[:4]
                            self._buf = self._buf[4:]
                        else:
                            # Not enough chars yet — restore state and wait for next chunk
                            self._buf = "u" + self._buf
                            self._escape_next = True
                            break
                elif c == "\\":
                    self._escape_next = True
                elif c == '"':
                    self._state = "SCANNING"
                    if out and not out.endswith(" "):
                        out += " "
                else:
                    out += c
        return out

    def flush_visible(self) -> str:
        if self._state == "IN_VALUE":
            tail = self._buf
            self._buf = ""
            self._state = "SCANNING"
            return tail
        self._buf = ""
        return ""


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
        # Сбрасываем буфер видимых символов, удержанных для поиска границ тегов
        tail = self._buf
        self._buf = ""
        return tail

    def think_text(self) -> str:
        """Возвращает весь собранный текст размышлений."""
        return "".join(self._think_parts).strip()


class ChatController:
    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        # Генераций может идти несколько (игра + чат + idle), поэтому счётчик,
        # а не bool: одиночный флаг гасил статус после первой завершившейся.
        self._inflight_lock = threading.Lock()
        self._inflight = 0

        self.staged_images = []
        self._owned_staged_images = set()
        self._subscribe_to_events()

    @property
    def llm_processing(self) -> bool:
        with self._inflight_lock:
            return self._inflight > 0

    def _enter_generation(self) -> None:
        with self._inflight_lock:
            self._inflight += 1

    def _exit_generation(self) -> None:
        with self._inflight_lock:
            self._inflight = max(0, self._inflight - 1)

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Chat.SEND_MESSAGE, self._on_send_message, weak=False)
        self.event_bus.subscribe("send_periodic_image_request", self._on_send_periodic_image_request, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_CHAT, self._on_clear_chat, weak=False)

        self.event_bus.subscribe(Events.Chat.STAGE_IMAGE, self._on_stage_image, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_STAGED_IMAGES, self._on_clear_staged_images, weak=False)

        self.event_bus.subscribe(Events.Chat.DELETE_MESSAGE, self._on_delete_message, weak=False)
        self.event_bus.subscribe(Events.Chat.DELETE_MESSAGES_FROM, self._on_delete_messages_from, weak=False)
        self.event_bus.subscribe(Events.Chat.REGENERATE, self._on_regenerate, weak=False)
        self.event_bus.subscribe(Events.Chat.REGENERATE_FROM, self._on_regenerate_from, weak=False)
        self.event_bus.subscribe(Events.Chat.INSERT_SYSTEM_MESSAGE, self._on_insert_system_message, weak=False)
        self.event_bus.subscribe(Events.Chat.SAVE_SNAPSHOT, self._on_save_snapshot, weak=False)
        self.event_bus.subscribe(Events.Chat.LOAD_SNAPSHOT, self._on_load_snapshot, weak=False)

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
        return use(CharacterRegistry).name_of(str(character_id))

    def _run_request(
        self,
        user_input: str,
        system_input: str = "",
        image_data: list[bytes] | None = None,
        image_source: str = "",
        task_uid: str | None = None,
        event_type: str | None = None,
        character_id: str | None = None,
        sender: str = "Player",
        participants: list[str] | None = None,
        req_id: str | None = None,
        origin_message_id: str | None = None,
        policy: dict | None = None,
        images_shown: bool = False,
    ):
        """Полный путь одного запроса. Выполняется в пуле GENERATION.

        Раньше это была корутина, внутри которой стоял блокирующий sync EventBus RPC —
        то есть на всё время генерации замирал весь asyncio-loop (озвучка, сервер
        игры, telegram), а вызывающий поток шины стоял на fut.result(600).
        """
        eff_policy = None
        stream_id = str(task_uid or req_id or f"stream:{uuid.uuid4().hex}")
        stream_started = False
        stream_finished = False
        stream_current_role = None
        self._enter_generation()
        try:
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
            
            def on_think_chunk(think_chunk: str):
                nonlocal stream_current_role, stream_started
                if stream_current_role != "think":
                    self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI, {
                        "stream_id": stream_id,
                        "character_id": character_id or "",
                        "character_name": effective_character_name,
                        "speaker_name": effective_character_name,
                        "role": "think",
                    }, delivery=EventDelivery.ORDERED)
                    stream_current_role = "think"
                    stream_started = True

                self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {
                    "stream_id": stream_id,
                    "chunk": think_chunk,
                    "role": "think",
                }, delivery=EventDelivery.ORDERED)

            stream_think_filter = ThinkTagStreamFilter(on_think_chunk=on_think_chunk if show_think_in_gui else None) if is_streaming else None
            stream_json_filter  = StructuredJsonStreamFilter() if is_streaming else None

            def _emit_visible_assistant(text: str):
                nonlocal stream_current_role, stream_started
                if not text:
                    return
                if stream_current_role != "assistant":
                    self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI, {
                        "stream_id": stream_id,
                        "character_id": character_id or "",
                        "character_name": effective_character_name,
                        "speaker_name": effective_character_name,
                        "role": "assistant",
                    }, delivery=EventDelivery.ORDERED)
                    stream_current_role = "assistant"
                    stream_started = True
                self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {
                    "stream_id": stream_id,
                    "chunk": text,
                    "role": "assistant",
                }, delivery=EventDelivery.ORDERED)

            def stream_callback_handler(chunk: str):
                if not eff_policy.echo_to_ui:
                    return
                chunk_str = str(chunk or "")
                if not chunk_str:
                    return

                # 1. Filter out <think> blocks (emits them separately)
                visible = stream_think_filter.feed(chunk_str) if stream_think_filter else chunk_str

                # 2. Filter JSON structured output → emit only segment text
                if visible and stream_json_filter is not None:
                    visible = stream_json_filter.feed(visible)

                _emit_visible_assistant(visible)

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

            if system_input and eff_policy.echo_to_ui and image_source != "mita_camera":
                ch = self._get_character_ref(character_id)
                if ch and hasattr(ch, "history_manager"):
                    ch.history_manager.append_message({
                        "role": "system",
                        "content": system_input,
                        "message_id": f"sys:{uuid.uuid4().hex}",
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                    "role": "system",
                    "response": system_input,
                    "is_initial": False,
                    "emotion": "",
                    "character_id": character_id or "",
                }, delivery=EventDelivery.ORDERED)

            if image_data and eff_policy.echo_to_ui and not images_shown:
                img_display_role = "assistant" if image_source == "mita_camera" else "user"
                img_content = [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(img).decode('utf-8')}"},
                        "display_role": img_display_role,
                    }
                    for img in image_data
                ]
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                    "role": img_display_role,
                    "response": img_content,
                    "is_initial": False,
                    "emotion": "",
                    "character_id": character_id or "",
                }, delivery=EventDelivery.ORDERED)

            result: ChatGenerationResult | None = use(GenerationService).generate_chat(
                ChatGenerationRequest(
                    character_id=character_id,
                    user_input=user_input,
                    system_input=system_input,
                    image_data=list(image_data or []),
                    image_source=image_source,
                    stream_callback=stream_callback_handler if is_streaming else None,
                    event_type=effective_event_type,
                    sender=sender,
                    participants=list(participants or []),
                    req_id=req_id,
                    origin_message_id=origin_message_id,
                    task_uid=task_uid,
                    policy=eff_policy,
                )
            )

            if result is None:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.FAILED_ON_GENERATION,
                        "error": "Failed to generate response"
                    })
                return None

            response_text = result.text
            voice_profile = result.voice_profile
            effective_character_id = result.character_id or character_id
            target = result.target
            targets: list[str] = result.targets
            think_text = result.think
            structured_data = result.structured
            assistant_message_id = result.message_id

            if not response_text:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.FAILED_ON_GENERATION,
                        "error": "Empty response"
                    })
                if eff_policy.echo_to_ui:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": "Пустой ответ модели"})
                return None

            effective_character_name = self._resolve_character_name(effective_character_id)

            if is_streaming and eff_policy.echo_to_ui:
                # Мы НЕ вызываем PREPARE_STREAM_UI здесь, так как он будет вызван
                # динамически в stream_callback_handler при получении первого чанка
                # (либо для think, либо для assistant).
                pass

            # Flush any held-back tail from stream filters
            if is_streaming and eff_policy.echo_to_ui:
                tail = stream_think_filter.flush_visible() if stream_think_filter else ""
                if tail and stream_json_filter is not None:
                    tail = stream_json_filter.feed(tail)
                if stream_json_filter is not None:
                    tail = (tail or "") + stream_json_filter.flush_visible()
                if tail:
                    _emit_visible_assistant(tail)

            if response_text and self.settings.get("USE_VOICEOVER") and eff_policy.allow_voiceover:
                if isinstance(voice_profile, dict):
                    is_game_master = (voice_profile.get("character_id") == "GameMaster")
                    if (not is_game_master) or bool(self.settings.get("GM_VOICE", False)):
                        if task_uid:
                            self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                                "uid": task_uid,
                                "status": TaskStatus.VOICING,
                                "result": self._build_task_result(response_text, target, structured_data, targets)
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
                            "message_id": assistant_message_id,
                        })
                    else:
                        if task_uid:
                            self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                                "uid": task_uid,
                                "status": TaskStatus.SUCCESS,
                                "result": self._build_task_result(response_text, target, structured_data, targets)
                            })
                else:
                    if task_uid:
                        self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                            "uid": task_uid,
                            "status": TaskStatus.SUCCESS,
                            "result": self._build_task_result(response_text, target, structured_data, targets)
                        })
            else:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        "uid": task_uid,
                        "status": TaskStatus.SUCCESS,
                        "result": self._build_task_result(response_text, target, structured_data, targets)
                    })

            if is_streaming and eff_policy.echo_to_ui:
                if not stream_started and response_text:
                    _emit_visible_assistant(response_text)

                finish_payload = {"stream_id": stream_id}
                if structured_data:
                    finish_payload["structured_data"] = structured_data
                self.event_bus.emit(Events.GUI.FINISH_STREAM_UI, finish_payload, delivery=EventDelivery.ORDERED)
                stream_finished = True
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
                    }, delivery=EventDelivery.ORDERED)
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                    "role": "assistant",
                    "response": response_text if response_text is not None else "...",
                    "is_initial": False,
                    "emotion": "",
                    "character_id": effective_character_id or "",
                    "character_name": effective_character_name or "",
                    "speaker_name": effective_character_name or "",
                    "target": target,
                    "targets": targets,
                    "structured_data": structured_data,
                    "message_id": assistant_message_id,
                }, delivery=EventDelivery.ORDERED)
            self.event_bus.emit(Events.GUI.UPDATE_STATUS)
            self.event_bus.emit(Events.GUI.UPDATE_DEBUG_INFO)
            self.event_bus.emit(Events.GUI.UPDATE_TOKEN_COUNT)

            return response_text

        except Exception as e:
            logger.error(f"Ошибка в обработке запроса: {e}", exc_info=True)
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.FAILED_ON_GENERATION,
                    "error": str(e)
                })
            if eff_policy and eff_policy.echo_to_ui:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {"error": f"Ошибка: {str(e)[:50]}..."})
            return None
        finally:
            if stream_started and not stream_finished:
                try:
                    self.event_bus.emit(
                        Events.GUI.FINISH_STREAM_UI,
                        {"stream_id": stream_id, "aborted": True},
                        delivery=EventDelivery.ORDERED,
                    )
                except Exception:
                    pass
            self._exit_generation()

    def _submit_request(self, **kwargs) -> None:
        """Ставит запрос в пул генераций. Переполнение — явный отказ, а не рост очереди."""
        task_uid = kwargs.get("task_uid")
        try:
            executors().try_submit(Pools.GENERATION, self._run_request, **kwargs)
        except PoolSaturated:
            logger.warning("Очередь генераций переполнена — запрос отклонён.")
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.FAILED_ON_GENERATION,
                    "error": "Generation queue is full",
                })
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": "Слишком много запросов одновременно. Подождите ответа."
            })

    def _on_send_message(self, event: Event):
        data = event.data or {}
        image_data = data.get("image_data", [])

        if image_data:
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)

        self._submit_request(
            user_input=data.get("user_input", ""),
            system_input=data.get("system_input", ""),
            image_data=image_data,
            image_source=data.get("image_source", ""),
            task_uid=data.get("task_uid"),
            event_type=str(data.get("event_type") or "chat"),
            character_id=self._normalize_character_id(data),
            sender=self._normalize_sender(data),
            participants=self._normalize_participants(data.get("participants")),
            req_id=data.get("req_id"),
            origin_message_id=data.get("origin_message_id"),
            policy=data.get("policy"),
            images_shown=bool(data.get("images_shown", False)),
        )

    @staticmethod
    def _build_task_result(response_text: str, target: str, structured_data: dict | None = None, targets: list[str] | None = None) -> dict:
        """Build the result dict for task_update, optionally including structured segments."""
        result = {"response": response_text, "target": target, "targets": targets or []}
        if structured_data:
            result["segments"] = structured_data.get("segments", [])
            result["attitude_change"] = structured_data.get("attitude_change", 0)
            result["boredom_change"] = structured_data.get("boredom_change", 0)
            result["stress_change"] = structured_data.get("stress_change", 0)
            result["memory_add"] = structured_data.get("memory_add", [])
            result["memory_update"] = structured_data.get("memory_update", [])
            result["memory_delete"] = structured_data.get("memory_delete", [])
            result["memory_merge"] = structured_data.get("memory_merge", [])
        return result

    def _on_get_llm_processing_status(self, event: Event):
        return self.llm_processing

    def _on_send_periodic_image_request(self, event: Event):
        data = event.data or {}

        if data.get("image_data"):
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)

        self._submit_request(
            user_input=data.get("user_input", ""),
            system_input=data.get("system_input", ""),
            image_data=data.get("image_data", []),
            image_source=data.get("image_source", ""),
            task_uid=data.get("task_uid"),
            event_type=data.get("event_type"),
            character_id=self._normalize_character_id(data),
            sender=self._normalize_sender(data),
            participants=self._normalize_participants(data.get("participants")),
            policy=data.get("policy"),
        )

    def _on_clear_chat(self, event: Event):
        pass

    def stage_image_bytes(self, img_bytes: bytes) -> int:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="nm_clip_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(img_bytes)

        self.staged_images.append(tmp_path)
        self._owned_staged_images.add(tmp_path)
        logger.info(f"Clipboard image staged: {tmp_path}")
        return len(self.staged_images)

    def clear_staged_images(self):
        for tmp_path in list(self._owned_staged_images):
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception as e:
                logger.warning(f"Failed to delete staged temp image {tmp_path}: {e}")
            finally:
                self._owned_staged_images.discard(tmp_path)
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

    # ── Debug panel helpers ──────────────────────────────────────────────────

    def _get_character_ref(self, character_id: str):
        if not character_id:
            return None
        return use(CharacterRegistry).get(str(character_id))

    def _get_current_character_id(self) -> str:
        return use(CharacterRegistry).current_id()

    def _on_delete_message(self, event: Event):
        data = event.data or {}
        message_id = data.get("message_id", "")
        character_id = data.get("character_id", "") or self._get_current_character_id()
        if not message_id:
            return
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] DELETE_MESSAGE: персонаж '{character_id}' не найден")
            return
        deleted = character.history_manager.delete_message(message_id)
        if deleted:
            self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
            logger.info(f"[ChatController] Удалено сообщение {message_id}")
        else:
            logger.warning(f"[ChatController] Сообщение {message_id} не найдено")

    def _on_delete_messages_from(self, event: Event):
        data = event.data or {}
        message_id = data.get("message_id", "")
        character_id = data.get("character_id", "") or self._get_current_character_id()
        edit_mode = bool(data.get("edit_mode", False))
        if not message_id:
            return
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] DELETE_MESSAGES_FROM: персонаж '{character_id}' не найден")
            return

        if edit_mode:
            # Find the message text before deleting
            history_data = character.history_manager.load_history()
            messages = history_data.get("messages", [])
            target_msg = next((m for m in messages if m.get("message_id") == message_id), None)
            if target_msg:
                content = target_msg.get("content", "")
                text = content if isinstance(content, str) else ""
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text") or item.get("content", "")
                            break
                character.history_manager.delete_messages_from(message_id)
                self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
                self.event_bus.emit(Events.GUI.INSERT_TEXT_TO_INPUT, text)
        else:
            character.history_manager.delete_messages_from(message_id)
            self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)

    def _on_regenerate(self, event: Event):
        data = event.data or {}
        character_id = data.get("character_id", "") or self._get_current_character_id()
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] REGENERATE: персонаж '{character_id}' не найден")
            return

        history_data = character.history_manager.load_history()
        messages = history_data.get("messages", [])

        # Find last assistant message
        last_assistant_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                last_assistant_idx = i
                break

        if last_assistant_idx is None:
            logger.warning("[ChatController] REGENERATE: нет assistant-сообщения в истории")
            return

        # Find the preceding user message
        last_user_idx = None
        last_user_text = ""
        for i in range(last_assistant_idx - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                content = messages[i].get("content", "")
                if isinstance(content, str):
                    last_user_text = content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            last_user_text = item.get("text") or item.get("content", "")
                            break
                break

        # Detect if the preceding user message is actually a system-as-user message
        # (stored with [Системное]: prefix). In that case keep it and just regenerate.
        _SYS_PREFIX = "[Системное]:"
        _is_sys_as_user = False
        if last_user_idx is not None:
            _raw = last_user_text
            if isinstance(_raw, str) and _raw.lstrip().startswith(_SYS_PREFIX):
                _is_sys_as_user = True

        if _is_sys_as_user:
            # Keep the system-as-user message, only remove the assistant response
            assistant = messages[last_assistant_idx]
            message_id = str(assistant.get("message_id") or "")
            if message_id:
                character.history_manager.delete_messages_from(message_id)
            else:
                character.history_manager.delete_messages_from_row(assistant.get("_history_row_id"))
            widgets_to_remove = self._count_widgets_for_slice(messages[last_assistant_idx:])
            self.event_bus.emit(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, {"count": widgets_to_remove})
            self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                "user_input": " ",
                "character_id": character_id,
            })
            return

        # Remove both the user and assistant messages to avoid duplication on re-send
        cut_idx = last_user_idx if last_user_idx is not None else last_assistant_idx
        cut_message = messages[cut_idx]
        message_id = str(cut_message.get("message_id") or "")
        if message_id:
            character.history_manager.delete_messages_from(message_id)
        else:
            character.history_manager.delete_messages_from_row(cut_message.get("_history_row_id"))

        widgets_to_remove = self._count_widgets_for_slice(messages[cut_idx:])
        self.event_bus.emit(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, {"count": widgets_to_remove})

        if last_user_text:
            self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                "user_input": last_user_text,
                "character_id": character_id,
            })

    def _count_widgets_for_slice(self, messages_slice: list) -> int:
        """Count how many chat display widgets will be rendered for a list of history messages.

        This accounts for extra widgets created per message:
        - StructuredOutputPanel (+1) when an assistant message has structured_data and
          SHOW_STRUCTURED_IN_GUI is not off.
        - Multiple target-group bubbles when segments have consecutive different targets.
        - ImageWidget (+1 each) for image_url items in message content.
        """
        show_structured = self.settings.get("SHOW_STRUCTURED_IN_GUI", "Выкл")
        struct_on = show_structured not in ("Выкл", "Off", "", False, None)

        count = 0
        for msg in messages_slice:
            role = msg.get("role", "")
            content = msg.get("content", "")
            structured_data = msg.get("structured_data")

            if role == "structured":
                # Separate "structured" role entries in history (legacy)
                if struct_on:
                    count += 1
                continue

            # Count main message bubbles
            if role == "assistant" and isinstance(structured_data, dict):
                segments = structured_data.get("segments") or []
                if segments:
                    # Replicate _group_segments_by_target logic to count target groups
                    n_groups = 1
                    cur_target = segments[0].get("target") or "Player"
                    for seg in segments[1:]:
                        t = seg.get("target") or "Player"
                        if t != cur_target:
                            n_groups += 1
                            cur_target = t
                    if n_groups > 1:
                        count += n_groups
                    else:
                        count += 1
                else:
                    count += 1
            else:
                count += 1

            # Structured panel is an extra widget after the last bubble
            if role == "assistant" and structured_data and struct_on:
                count += 1

            # Image widgets
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        if item.get("image_url", {}).get("url", ""):
                            count += 1

        return count

    def _on_regenerate_from(self, event: Event):
        """Delete everything after (and including) the message after the target, then re-send it."""
        data = event.data or {}
        message_id = data.get("message_id", "")
        character_id = data.get("character_id", "") or self._get_current_character_id()
        if not message_id:
            return
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] REGENERATE_FROM: персонаж '{character_id}' не найден")
            return

        history_data = character.history_manager.load_history()
        messages = history_data.get("messages", [])

        # Find the target message index
        target_idx = next((i for i, m in enumerate(messages) if m.get("message_id") == message_id), None)
        if target_idx is None:
            logger.warning(f"[ChatController] REGENERATE_FROM: сообщение {message_id} не найдено")
            return

        target_msg = messages[target_idx]
        target_role = target_msg.get("role", "user")

        # Detect user messages stored with [Системное]: prefix (as_user mode)
        # and treat them like system messages for regeneration purposes.
        _SYS_PREFIX = "[Системное]:"
        if target_role == "user":
            _raw = target_msg.get("content", "")
            if isinstance(_raw, list):
                for _it in _raw:
                    if isinstance(_it, dict) and _it.get("type") == "text":
                        _raw = _it.get("text") or _it.get("content", "")
                        break
            if isinstance(_raw, str) and _raw.lstrip().startswith(_SYS_PREFIX):
                target_role = "system"

        if target_role == "user":
            # Extract user text, cut history before this message, re-send
            content = target_msg.get("content", "")
            if isinstance(content, str):
                user_text = content
            else:
                user_text = ""
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            user_text = item.get("text") or item.get("content", "")
                            break

            # Cut history: remove user message + everything after
            message_id = str(target_msg.get("message_id") or "")
            if message_id:
                character.history_manager.delete_messages_from(message_id)
            else:
                character.history_manager.delete_messages_from_row(target_msg.get("_history_row_id"))

            # Widgets removed = everything from target_idx to end of current display
            widgets_to_remove = self._count_widgets_for_slice(messages[target_idx:])
            self.event_bus.emit(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, {"count": widgets_to_remove})

            if user_text:
                self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": user_text,
                    "character_id": character_id,
                })

        elif target_role == "assistant":
            # Find the preceding user message and re-send from there
            preceding_user_idx = None
            preceding_user_text = ""
            for i in range(target_idx - 1, -1, -1):
                if messages[i].get("role") == "user":
                    preceding_user_idx = i
                    content = messages[i].get("content", "")
                    if isinstance(content, str):
                        preceding_user_text = content
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                preceding_user_text = item.get("text") or item.get("content", "")
                                break
                    break

            cut_idx = preceding_user_idx if preceding_user_idx is not None else target_idx
            cut_message = messages[cut_idx]
            cut_message_id = str(cut_message.get("message_id") or "")
            if cut_message_id:
                character.history_manager.delete_messages_from(cut_message_id)
            else:
                character.history_manager.delete_messages_from_row(cut_message.get("_history_row_id"))

            widgets_to_remove = self._count_widgets_for_slice(messages[cut_idx:])
            self.event_bus.emit(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, {"count": widgets_to_remove})

            if preceding_user_text:
                self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                    "user_input": preceding_user_text,
                    "character_id": character_id,
                })

        elif target_role == "system":
            # Keep the system message, delete everything after, trigger generation
            message_id = str(target_msg.get("message_id") or "")
            if message_id:
                character.history_manager.delete_messages_after(message_id)
            else:
                character.history_manager.delete_messages_from_row(
                    target_msg.get("_history_row_id"),
                    include_target=False,
                )

            widgets_to_remove = self._count_widgets_for_slice(messages[target_idx + 1:])
            if widgets_to_remove > 0:
                self.event_bus.emit(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, {"count": widgets_to_remove})

            # If the system message is stored as role=user (as_user / [Системное]: mode),
            # the conversation already ends on a user turn — sending " " would create a
            # second consecutive user message which confuses Gemini.  Use empty string so
            # prompt_controller skips adding an extra user turn and the LLM responds
            # directly to the [Системное] message.
            trigger_input = "" if target_msg.get("role") == "user" else " "
            self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
                "user_input": trigger_input,
                "character_id": character_id,
            })

    def _on_insert_system_message(self, event: Event):
        import uuid
        import datetime
        data = event.data or {}
        text = str(data.get("text", "")).strip()
        character_id = data.get("character_id", "") or self._get_current_character_id()
        if not text:
            return
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] INSERT_SYSTEM_MESSAGE: персонаж '{character_id}' не найден")
            return
        as_user = bool(data.get("as_user", False))
        logger.info(f"[ChatController] INSERT_SYSTEM_MESSAGE: as_user={as_user}, text={text[:50]}")
        if as_user:
            role = "user"
            content = f"[Системное]: {text}"
            logger.info(f"[ChatController] Сохраняем как role='user' с префиксом: {content[:60]}")
        else:
            role = "system"
            content = text
            logger.info(f"[ChatController] Сохраняем как role='system': {content[:60]}")
        message = {
            "role": role,
            "content": content,
            "message_id": f"sys:{uuid.uuid4().hex}",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        character.history_manager.append_message(message)
        logger.info(f"[ChatController] Сообщение сохранено, эмитим RELOAD_CHAT_HISTORY")
        self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
        # Trigger generation so Mita responds to the system message.
        # A single space is used instead of "" so that:
        # 1. prompt_controller adds a proper user turn (required by Gemini API)
        # 2. Gemini provider doesn't corrupt the last assistant message
        # The space is filtered from future history by _has_visible_user_text().
        self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
            "user_input": " ",
            "character_id": character_id,
        })

    def _on_save_snapshot(self, event: Event):
        data = event.data or {}
        character_id = data.get("character_id", "") or self._get_current_character_id()
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] SAVE_SNAPSHOT: персонаж '{character_id}' не найден")
            return
        saved_path = character.history_manager.save_history_separate()
        if saved_path:
            logger.info(f"[ChatController] Snapshot сохранён: {saved_path}")
            self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                "title": "Snapshot",
                "message": f"Snapshot сохранён:\n{saved_path}",
            })
        else:
            logger.warning(f"[ChatController] SAVE_SNAPSHOT: не удалось сохранить для {character_id}")

    def _on_load_snapshot(self, event: Event):
        import json
        data = event.data or {}
        file_path = data.get("file_path", "")
        character_id = data.get("character_id", "") or self._get_current_character_id()
        if not file_path:
            return
        character = self._get_character_ref(character_id)
        if character is None:
            logger.warning(f"[ChatController] LOAD_SNAPSHOT: персонаж '{character_id}' не найден")
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                snapshot_data = json.load(f)
            # Поддержка старого формата: список сообщений без обёртки
            if isinstance(snapshot_data, list):
                snapshot_data = {"messages": snapshot_data, "variables": {}}
            character.history_manager.save_history(snapshot_data)
            self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
            logger.info(f"[ChatController] Snapshot загружен из {file_path}")
        except Exception as e:
            logger.error(f"[ChatController] Ошибка загрузки snapshot: {e}", exc_info=True)
