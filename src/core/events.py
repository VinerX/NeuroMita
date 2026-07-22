from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.executors import PoolSaturated, Pools, executors
from core.serial_dispatcher import SerialDispatcher
from main_logger import logger


_ORDERED_EVENT_NAMES = frozenset(
    {
        "create_task",
        "update_task_status",
        "task_created",
        "task_status_changed",
        "notify_task_update",
        "prepare_stream_ui",
        "append_stream_chunk_ui",
        "finish_stream_ui",
        "update_chat_ui",
    }
)

_COMMAND_EVENT_NAMES = frozenset(
    {
        "installable_install",
        "installable_uninstall",
        "installable_initialize",
        "run_install_with_ui",
        "run_install_headless",
        "install_cancel_queued",
        "install_cancel_running",
    }
)


class EventDelivery(str, Enum):
    CRITICAL = "critical"
    COMMAND = "command"
    ORDERED = "ordered"
    BEST_EFFORT = "best_effort"


@dataclass(slots=True)
class Event:
    name: str
    data: Any = None
    timestamp: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = time.time()


class EventSubscription:
    def __init__(
        self,
        bus: "EventBus",
        event_name: str,
        callback: Callable[..., Any],
        *,
        weak: bool,
    ) -> None:
        self._bus_ref = weakref.ref(bus)
        self._event_name = str(event_name)
        self._callback: Callable[..., Any] | None = None
        self._callback_ref: weakref.ReferenceType[Any] | None = None
        if weak:
            try:
                if getattr(callback, "__self__", None) is not None:
                    self._callback_ref = weakref.WeakMethod(callback)
                else:
                    self._callback_ref = weakref.ref(callback)
            except TypeError:
                self._callback = callback
        else:
            self._callback = callback
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        bus = self._bus_ref()
        callback = self._callback
        if callback is None and self._callback_ref is not None:
            callback = self._callback_ref()
        if bus is not None and callback is not None:
            bus.unsubscribe(self._event_name, callback)

    def __enter__(self) -> "EventSubscription":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class EventBus:
    """Non-blocking fact bus with isolated critical and ordered channels."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Any]] = {}
        self._lock = threading.RLock()
        self._running = True
        self._critical = SerialDispatcher(
            "event-critical",
            lanes=4,
            capacity_per_lane=4096,
        )
        self._commands = SerialDispatcher(
            "event-command",
            lanes=1,
            capacity_per_lane=512,
        )
        self._ordered = SerialDispatcher(
            "event-ordered",
            lanes=8,
            capacity_per_lane=4096,
        )
        self._dropped = 0

    def subscribe(
        self,
        event_name: str,
        callback: Callable[..., Any],
        weak: bool = True,
    ) -> EventSubscription:
        if not callable(callback):
            raise TypeError("callback must be callable")
        normalized = str(event_name)
        if self._looks_like_query(normalized):
            raise ValueError(
                f"'{normalized}' is a query, not a fact event. "
                "Read state through a typed service instead."
            )

        with self._lock:
            subscribers = self._subscribers.setdefault(normalized, [])
            if not any(self._is_same_callback(ref, callback) for ref in subscribers):
                stored: Any
                if weak:
                    cleanup = self._create_cleanup_callback(normalized)
                    try:
                        if getattr(callback, "__self__", None) is not None:
                            stored = weakref.WeakMethod(callback, cleanup)
                        else:
                            stored = weakref.ref(callback, cleanup)
                    except TypeError:
                        stored = callback
                else:
                    stored = callback
                subscribers.append(stored)
        return EventSubscription(self, normalized, callback, weak=weak)

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        normalized = str(event_name)
        with self._lock:
            subscribers = self._subscribers.get(normalized)
            if not subscribers:
                return
            kept = [
                ref for ref in subscribers if not self._is_same_callback(ref, callback)
            ]
            if kept:
                self._subscribers[normalized] = kept
            else:
                self._subscribers.pop(normalized, None)

    def unsubscribe_owner(self, owner: Any) -> int:
        if owner is None:
            return 0
        removed = 0
        with self._lock:
            for event_name in tuple(self._subscribers):
                kept: list[Any] = []
                for ref in self._subscribers[event_name]:
                    callback = ref() if isinstance(ref, weakref.ReferenceType) else ref
                    if callback is None or getattr(callback, "__self__", None) is owner:
                        removed += 1
                    else:
                        kept.append(ref)
                if kept:
                    self._subscribers[event_name] = kept
                else:
                    self._subscribers.pop(event_name, None)
        return removed

    def try_emit(
        self,
        event_name: str,
        data: Any = None,
        sync: bool = False,
        *,
        delivery: EventDelivery | str | None = None,
        order_key: Any = None,
    ) -> bool:
        if not self._running:
            return False
        normalized = str(event_name)
        if self._looks_like_query(normalized):
            raise ValueError(
                f"'{normalized}' is a query, not a fact event. "
                "Read state through a typed service instead."
            )

        event = Event(name=normalized, data=data)
        with self._lock:
            subscribers = self._get_active_subscribers(normalized)
        if not subscribers:
            return True

        selected = self._delivery_for(normalized, sync=sync, delivery=delivery)
        if selected is EventDelivery.BEST_EFFORT:
            pool = executors().pool(Pools.EVENT_BUS)
            try:
                pool.try_submit(self._dispatch_event, subscribers, event)
            except PoolSaturated:
                self._record_drop(normalized, selected)
                return False
            return True

        if selected is EventDelivery.ORDERED:
            dispatcher = self._ordered
            key = self._order_key(event, explicit=order_key)
        elif selected is EventDelivery.COMMAND:
            dispatcher = self._commands
            key = "command"
        else:
            dispatcher = self._critical
            key = normalized
        accepted = dispatcher.submit(
            self._dispatch_event,
            subscribers,
            event,
            key=key,
            description=f"{selected.value}:{normalized}",
        )
        if not accepted:
            self._record_drop(normalized, selected)
        return accepted

    def emit(
        self,
        event_name: str,
        data: Any = None,
        sync: bool = False,
        *,
        delivery: EventDelivery | str | None = None,
        order_key: Any = None,
    ) -> None:
        accepted = self.try_emit(
            event_name,
            data,
            sync,
            delivery=delivery,
            order_key=order_key,
        )
        selected = self._delivery_for(str(event_name), sync=sync, delivery=delivery)
        if not accepted and selected is not EventDelivery.BEST_EFFORT and self._running:
            logger.error(f"Critical event '{event_name}' was rejected")

    def flush(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        if not self._commands.wait_idle(timeout=max(0.0, deadline - time.monotonic())):
            return False
        if not self._critical.wait_idle(timeout=max(0.0, deadline - time.monotonic())):
            return False
        return self._ordered.wait_idle(timeout=max(0.0, deadline - time.monotonic()))

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def dropped_events(self) -> int:
        return self._dropped

    def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        self._commands.close(drain=True, timeout=3.0)
        self._critical.close(drain=True, timeout=3.0)
        self._ordered.close(drain=True, timeout=3.0)

    def _dispatch_event(
        self,
        subscribers: tuple[Callable[..., Any], ...] | list[Callable[..., Any]],
        event: Event,
    ) -> None:
        for callback in subscribers:
            self._safe_call(callback, event)

    def _safe_call(self, callback: Callable[..., Any], event: Event) -> None:
        try:
            callback(event)
        except Exception as exc:
            logger.error(
                f"Event subscriber failed for '{event.name}': {exc}",
                exc_info=True,
            )

    def _get_active_subscribers(self, event_name: str) -> List[Callable[..., Any]]:
        subscribers = self._subscribers.get(event_name)
        if not subscribers:
            return []
        active: list[Callable[..., Any]] = []
        dead: list[Any] = []
        for ref in subscribers:
            callback = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if callback is None:
                dead.append(ref)
            else:
                active.append(callback)
        if dead:
            self._subscribers[event_name] = [ref for ref in subscribers if ref not in dead]
            if not self._subscribers[event_name]:
                self._subscribers.pop(event_name, None)
        return active

    def _create_cleanup_callback(self, event_name: str) -> Callable[[Any], None]:
        bus_ref = weakref.ref(self)

        def cleanup(dead_ref: Any) -> None:
            bus = bus_ref()
            if bus is None:
                return
            with bus._lock:
                subscribers = bus._subscribers.get(event_name)
                if not subscribers:
                    return
                try:
                    subscribers.remove(dead_ref)
                except ValueError:
                    return
                if not subscribers:
                    bus._subscribers.pop(event_name, None)

        return cleanup

    @staticmethod
    def _is_same_callback(ref: Any, callback: Callable[..., Any]) -> bool:
        target = ref() if isinstance(ref, weakref.ReferenceType) else ref
        return target is not None and target == callback

    @staticmethod
    def _looks_like_query(event_name: str) -> bool:
        normalized = str(event_name).strip().lower()
        return normalized.startswith("get_") or "_get_" in normalized

    @staticmethod
    def _delivery_for(
        event_name: str,
        *,
        sync: bool,
        delivery: EventDelivery | str | None,
    ) -> EventDelivery:
        if delivery is not None:
            return delivery if isinstance(delivery, EventDelivery) else EventDelivery(str(delivery))
        if event_name in _COMMAND_EVENT_NAMES:
            return EventDelivery.COMMAND
        if sync or event_name in _ORDERED_EVENT_NAMES:
            return EventDelivery.ORDERED
        return EventDelivery.CRITICAL

    @staticmethod
    def _order_key(event: Event, *, explicit: Any = None) -> Any:
        if explicit is not None:
            return explicit
        data = event.data if isinstance(event.data, dict) else {}
        return (
            data.get("stream_id")
            or data.get("task_uid")
            or data.get("uid")
            or data.get("character_id")
            or event.name
        )

    def _record_drop(self, event_name: str, delivery: EventDelivery) -> None:
        self._dropped += 1
        logger.error(
            f"Event channel saturated; rejected '{event_name}' "
            f"({delivery.value})"
        )


_global_event_bus: Optional[EventBus] = None
_event_bus_shutdown = False


def get_event_bus() -> EventBus:
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
        if _event_bus_shutdown:
            _global_event_bus.shutdown()
    return _global_event_bus


def shutdown_event_bus() -> None:
    global _global_event_bus, _event_bus_shutdown
    _event_bus_shutdown = True
    if _global_event_bus is not None:
        _global_event_bus.shutdown()


def subscribe(
    event_name: str,
    callback: Callable[..., Any],
    weak: bool = True,
) -> EventSubscription:
    return get_event_bus().subscribe(event_name, callback, weak)


def unsubscribe(event_name: str, callback: Callable[..., Any]) -> None:
    get_event_bus().unsubscribe(event_name, callback)


def try_emit(
    event_name: str,
    data: Any = None,
    sync: bool = False,
    *,
    delivery: EventDelivery | str | None = None,
    order_key: Any = None,
) -> bool:
    return get_event_bus().try_emit(
        event_name,
        data,
        sync,
        delivery=delivery,
        order_key=order_key,
    )


def emit(
    event_name: str,
    data: Any = None,
    sync: bool = False,
    *,
    delivery: EventDelivery | str | None = None,
    order_key: Any = None,
) -> None:
    get_event_bus().emit(
        event_name,
        data,
        sync,
        delivery=delivery,
        order_key=order_key,
    )
class Events:
    """
    Константы с именами событий, сгруппированные по логическим модулям.
    Доступ возможен как Events.EVENT_NAME, так и Events.GROUP.EVENT_NAME.
    """

    # УДАЛЕНО (стало сервисами в core/services.py + services/contracts.py):
    #   Core.GET_EVENT_LOOP, Core.RUN_IN_LOOP      -> LoopService
    #   Settings.GET_SETTING/GET_SETTINGS          -> SettingsService
    #   Settings.GET_APP_VARS                      -> AppVarsService
    #   Character.GET/GET_ALL/GET_CURRENT_*        -> CharacterRegistry
    #   Server.GET_GAME_CONNECTION                 -> GameLinkService
    #   Prompt.BUILD_PROMPT                        -> PromptBuilderService
    #   History.PREPARE_FOR_PROMPT                 -> HistoryService
    #   Model.GENERATE_RESPONSE                    -> GenerationService
    # Это были синхронные вызовы функций, замаскированные под события: каждый
    # тянул поток, executor и таймаут, а вложенность доходила до 5 уровней.

    class Core:
        """Системные и межкомпонентные события"""
        LOOP_READY = "loop_ready"
        SETTING_CHANGED = "setting_changed"

    class GUI:
        """События, предназначенные для GuiController и его суб-контроллеров"""
        UPDATE_TOKEN_COUNT = "update_token_count"
        UPDATE_STATUS = "update_status"
        UPDATE_DEBUG_INFO = "update_debug_info"
        SHOW_MITA_THINKING = "show_mita_thinking"
        SHOW_MITA_ERROR = "show_mita_error"
        HIDE_MITA_STATUS = "hide_mita_status"
        SHOW_MITA_VOICING = "show_mita_voicing"
        HIDE_MITA_VOICING = "hide_mita_voicing"
        PULSE_MITA_ERROR = "pulse_mita_error"
        SHOW_LOADING_POPUP = "show_loading_popup"
        CLOSE_LOADING_POPUP = "close_loading_popup"
        CLEAR_USER_INPUT = "clear_user_input"
        CLEAR_USER_INPUT_UI = "clear_user_input_ui"
        PREPARE_STREAM_UI = "prepare_stream_ui"
        APPEND_STREAM_CHUNK_UI = "append_stream_chunk_ui"
        FINISH_STREAM_UI = "finish_stream_ui"
        CHECK_AND_INSTALL_FFMPEG = "check_and_install_ffmpeg"
        UPDATE_STATUS_COLORS = "update_status_colors"
        UPDATE_CHAT_UI = "update_chat_ui"
        INSERT_TEXT_TO_INPUT = "insert_text_to_input"
        SEND_TEXT_MESSAGE = "send_text_message"
        CHECK_USER_ENTRY_EXISTS = "check_user_entry_exists"
        SWITCH_VOICEOVER_SETTINGS = "switch_voiceover_settings"
        SHOW_INFO_MESSAGE = "show_info_message"
        UPDATE_CHAT_FONT_SIZE = "update_chat_font_size"
        RELOAD_CHAT_HISTORY = "reload_chat_history"
        REMOVE_LAST_CHAT_WIDGETS = "remove_last_chat_widgets"
        UPDATE_TOKEN_COUNT_UI = "update_token_count_ui"
        GET_GUI_WINDOW_ID = "get_gui_window_id"
        CHECK_TRITON_DEPENDENCIES = "check_triton_dependencies"
        SHOW_ERROR_MESSAGE = "show_error_message"
        UPDATE_LOCAL_VOICE_COMBOBOX = "update_local_voice_combobox" 
        SHOW_EULA_DIALOG = "show_eula_dialog"
        SHOW_GUIDE = "show_guide"
        HIDE_GUIDE = "hide_guide"
        SHOW_WINDOW = "show_window"
        CLOSE_WINDOW = "close_window"
        CLOSE_ALL_WINDOWS = "close_all_windows"
        SET_SETTINGS_ICON_INDICATOR = "set_settings_icon_indicator"

        VOICEOVER_UI_READY = "voiceover_ui_ready"
        VOICEOVER_REFRESH = "voiceover_refresh"
        VOICEOVER_MODEL_SELECTED = "voiceover_model_selected"

    class Model:
        """События для управления LLM, персонажами и историей"""
        LOAD_HISTORY = "load_history"
        GET_CHAT_HISTORY = "get_chat_history"
        LOAD_MORE_HISTORY = "load_more_history"
        SCHEDULE_G4F_UPDATE = "schedule_g4f_update"
        GET_CURRENT_CONTEXT_TOKENS = "get_current_context_tokens"
        GET_TOKEN_STATS = "get_token_stats"
        CALCULATE_COST = "calculate_cost"
        RELOAD_PROMPTS_ASYNC = "reload_prompts_async"
        GET_DEBUG_INFO = "get_debug_info"
        ON_STARTED_RESPONSE_GENERATION = "on_started_response_generation"
        # Сжатие истории — ОТДЕЛЬНЫЙ статус, со своими старт/финиш-событиями.
        # Не переиспользуем ON_STARTED_RESPONSE_GENERATION: (1) оно триггерит и
        # sandbox-диагностику «последнего запроса», (2) детект «это сжатие» через
        # ContextVar не переживал смену потока диспетчера → статус залипал как
        # «… думает» и не гасился. Свои события снимают обе проблемы.
        ON_COMPRESSION_STARTED = "on_compression_started"
        ON_COMPRESSION_FINISHED = "on_compression_finished"
        ON_SUCCESSFUL_RESPONSE = "on_successful_response"
        ON_FAILED_RESPONSE = "on_failed_response"
        ON_FAILED_RESPONSE_ATTEMPT = "on_failed_attempt_for_response"
        ON_TOOL_EXECUTING = "on_tool_executing"   # payload: {tool_name, character_id}
        ON_TOOL_DONE = "on_tool_done"             # payload: {tool_name, character_id}
        ADD_TEMPORARY_SYSTEM_INFO = "add_temporary_system_info"
        GET_LLM_PROCESSING_STATUS = "get_llm_processing_status"
        GET_GAME_STATE = "get_game_state"
        PEEK_TEMPORARY_SYSTEM_INFOS = "peek_temporary_system_infos"

    class Chat:
        """События, управляющие логикой чата и отправкой сообщений"""
        SEND_MESSAGE = "send_message"
        CLEAR_CHAT = "clear_chat"
        ATTACH_IMAGES = "attach_images"
        STAGE_IMAGE = "stage_image"
        CLEAR_STAGED_IMAGES = "clear_staged_images"
        DELETE_MESSAGE = "chat_delete_message"
        DELETE_MESSAGES_FROM = "chat_delete_messages_from"
        REGENERATE = "chat_regenerate"
        REGENERATE_FROM = "chat_regenerate_from"
        RETRY_LAST = "chat_retry_last"
        INSERT_SYSTEM_MESSAGE = "chat_insert_system_message"
        SAVE_SNAPSHOT = "chat_save_snapshot"
        LOAD_SNAPSHOT = "chat_load_snapshot"

    class Audio:
        """События для управления озвучкой и аудиофайлами"""
        SELECT_VOICE_MODEL = "select_voice_model"
        INIT_VOICE_MODEL = "init_voice_model"
        CHECK_MODEL_INSTALLED = "check_model_installed"
        CHECK_MODEL_INITIALIZED = "check_model_initialized"
        CHANGE_VOICE_LANGUAGE = "change_voice_language"
        REFRESH_VOICE_MODULES = "refresh_voice_modules"
        DELETE_SOUND_FILES = "delete_sound_files"
        SET_WAITING_ANSWER = "set_waiting_answer"
        UPDATE_MODEL_LOADING_STATUS = "update_model_loading_status"
        FINISH_MODEL_LOADING = "finish_model_loading"
        CANCEL_MODEL_LOADING = "cancel_model_loading"
        GET_WAITING_ANSWER = "get_waiting_answer"
        # Окно «Мита сейчас говорит» — чтобы ASR не засчитывал её собственный
        # голос из микрофона. payload: {"active": bool} (открытое окно,
        # локальное воспроизведение) или {"duration": float} (окно по длине
        # аудио — для проигрывания в игре, где конец проигрывания нам не виден).
        MITA_SPEAKING_WINDOW = "mita_speaking_window"
        VOICEOVER_REQUESTED = "voiceover_requested"
        OPEN_VOICE_MODEL_SETTINGS = "open_voice_model_settings"
        OPEN_VOICE_MODEL_SETTINGS_DIALOG = "open_voice_model_settings_dialog"
        SHOW_VC_REDIST_DIALOG = "show_vc_redist_dialog"
        SHOW_TRITON_DIALOG = "show_triton_dialog"
        REFRESH_TRITON_STATUS = "refresh_triton_status"
        GET_TRITON_STATUS = "get_triton_status"

        # Новые (для LocalVoiceController)
        LOCAL_SEND_VOICE_REQUEST = "local_send_voice_request"
        LOCAL_INSTALL_MODEL = "local_install_voice_model"
        LOCAL_UNINSTALL_MODEL = "local_uninstall_voice_model"
        GET_ALL_LOCAL_MODEL_CONFIGS = "get_all_local_model_configs"

    class Speech:
        """События для распознавания речи и управления микрофоном"""
        GET_MIC_STATUS = "get_mic_status"
        SET_MICROPHONE = "set_microphone"
        START_SPEECH_RECOGNITION = "start_speech_recognition"
        STOP_SPEECH_RECOGNITION = "stop_speech_recognition"
        UPDATE_SPEECH_SETTINGS = "update_speech_settings"
        GET_INSTANT_SEND_STATUS = "get_instant_send_status"
        SET_INSTANT_SEND_STATUS = "set_instant_send_status"
        SPEECH_TEXT_RECOGNIZED = "speech_text_recognized"
        GET_MICROPHONE_LIST = "get_microphone_list"
        REFRESH_MICROPHONE_LIST = "refresh_microphone_list"
        SET_GIGAAM_OPTIONS = "set_gigaam_options"
        RESTART_SPEECH_RECOGNITION = "restart_speech_recognition"

        INSTALL_ASR_MODEL = "install_asr_model"
        CHECK_ASR_MODEL_INSTALLED = "check_asr_model_installed" 
        ASR_MODEL_INSTALL_STARTED = "asr_model_install_started"
        ASR_MODEL_INSTALL_PROGRESS = "asr_model_install_progress"
        ASR_MODEL_INSTALL_FINISHED = "asr_model_install_finished"
        ASR_MODEL_INSTALL_FAILED = "asr_model_install_failed"
        ASR_MODEL_INITIALIZED = "asr_model_initialized"
        ASR_FAILED = "asr_failed"
        
        GET_RECOGNIZER_SETTINGS_SCHEMA = "get_asr_settings_schema"
        GET_RECOGNIZER_SETTINGS = "get_asr_settings"
        SET_RECOGNIZER_OPTION = "set_recognizer_option"
        APPLY_RECOGNIZER_SETTINGS = "apply_recognizer_settings"
        ASR_MODEL_INIT_STARTED = "asr_model_init_started"
        GET_ASR_MODELS_GLOSSARY = "get_asr_models_glossary"
        GET_ASR_ENGINES_LIST = "get_asr_engines_list"
        

    class Capture:
        """События для захвата экрана и камеры"""
        CAPTURE_SCREEN = "capture_screen"
        GET_CAMERA_FRAMES = "get_camera_frames"
        GET_SCREEN_CAPTURE_STATUS = "get_screen_capture_status"
        GET_CAMERA_CAPTURE_STATUS = "get_camera_capture_status"
        STOP_SCREEN_CAPTURE = "stop_screen_capture"
        STOP_CAMERA_CAPTURE = "stop_camera_capture"
        START_SCREEN_CAPTURE = "start_screen_capture"
        START_CAMERA_CAPTURE = "start_camera_capture"
        START_IMAGE_REQUEST_TIMER = "start_image_request_timer"
        STOP_IMAGE_REQUEST_TIMER = "stop_image_request_timer"
        UPDATE_SCREEN_CAPTURE_EXCLUSION = "update_screen_capture_exclusion"
        CAPTURE_SETTINGS_LOADED = "capture_settings_loaded"
        SEND_PERIODIC_IMAGE_REQUEST = "send_periodic_image_request"
        UPDATE_LAST_IMAGE_REQUEST_TIME = "update_last_image_request_time"

    class Server:
        """События для взаимодействия с игровым клиентом через TCP сервер"""
        STOP_SERVER = "stop_server"
        SET_GAME_CONNECTION = "update_game_connection"
        SET_GAME_DATA = "set_game_data"
        SET_DIALOG_ACTIVE = "set_dialog_active"
        SET_ID_SOUND = "set_id_sound"
        GET_SERVER_DATA = "get_server_data"
        RESET_SERVER_DATA = "reset_server_data"
        GET_CHAT_SERVER = "get_chat_server"
        SET_PATCH_TO_SOUND_FILE = "set_patch_to_sound_file"
        SEND_TASK_UPDATE = "send_task_update"
        LOAD_SERVER_SETTINGS = "load_server_settings"
        ECHO_CHAT_MESSAGE_REQUESTED = "echo_chat_message_requested"
        BROADCAST_ASR_TEXT = "broadcast_asr_text"

    class Telegram:
        """События для взаимодействия с Telegram"""
        GET_SILERO_STATUS = "get_silero_status"
        REQUEST_TG_CODE = "request_tg_code"
        REQUEST_TG_PASSWORD = "request_tg_password"
        SET_SOUND_FILE_DATA = "set_sound_file_data"
        SET_SILERO_CONNECTED = "set_silero_connected"
        PROMPT_FOR_TG_CODE = "prompt_for_tg_code"
        PROMPT_FOR_TG_PASSWORD = "prompt_for_tg_password"
        TELEGRAM_SEND_VOICE_REQUEST = "telegram_send_voice_request"
        START_SILERO = "telegram_start_silero"
        STOP_SILERO = "telegram_stop_silero"

    class Settings:
        """События для управления настройками (чтение — через SettingsService)"""
        SAVE_SETTING = "save_setting"
        LOAD_SETTINGS = "load_settings"

    class VoiceModel:
        """События для управления локальными голосовыми моделями"""
        GET_MODEL_DATA = "get_voice_model_data"
        GET_INSTALLED_MODELS = "get_installed_models"
        GET_DEPENDENCIES_STATUS = "get_dependencies_status"
        GET_DEFAULT_DESCRIPTION = "get_default_description"
        GET_MODEL_DESCRIPTION = "get_model_description"
        GET_SETTING_DESCRIPTION = "get_setting_description"
        GET_SECTION_VALUES = "get_section_values"
        INSTALL_MODEL = "install_voice_model"
        UNINSTALL_MODEL = "uninstall_voice_model"
        SAVE_SETTINGS = "save_voice_model_settings"
        CLOSE_DIALOG = "close_voice_model_dialog"
        OPEN_DOC = "open_voice_model_doc"
        UPDATE_DESCRIPTION = "update_voice_model_description"
        CLEAR_DESCRIPTION = "clear_voice_model_description"
        MODEL_INSTALL_STARTED = "voice_model_install_started"
        MODEL_INSTALL_FINISHED = "voice_model_install_finished"
        MODEL_UNINSTALL_STARTED = "voice_model_uninstall_started"
        MODEL_UNINSTALL_FINISHED = "voice_model_uninstall_finished"
        REFRESH_MODEL_PANELS = "refresh_voice_model_panels"
        REFRESH_SETTINGS_DISPLAY = "refresh_voice_settings_display"

    class Task:
        """События для управления задачами"""
        CREATE_TASK = "create_task"
        UPDATE_TASK_STATUS = "update_task_status"
        GET_TASK = "get_task"
        TASK_CREATED = "task_created"
        TASK_STATUS_CHANGED = "task_status_changed"
        NOTIFY_TASK_UPDATE = "notify_task_update"

    class ApiPresets:
        """События для управления API пресетами"""
        GET_PRESET_LIST = "get_preset_list"
        GET_PRESET_FULL = "get_preset_full"
        SAVE_CUSTOM_PRESET = "save_custom_preset"
        DELETE_CUSTOM_PRESET = "delete_custom_preset"
        EXPORT_PRESET = "export_preset"
        IMPORT_PRESET = "import_preset"
        TEST_CONNECTION = "test_connection"
        TEST_RESULT = "test_result"
        TEST_FAILED = "test_failed"
        SET_GEMINI_CASE = "set_gemini_case"
        PRESET_SAVED = "preset_saved"
        PRESET_DELETED = "preset_deleted"
        PRESET_IMPORTED = "preset_imported"
        SAVE_PRESET_STATE = "save_preset_state"
        LOAD_PRESET_STATE = "load_preset_state"
        GET_CURRENT_PRESET_ID = "get_current_preset_id"
        SET_CURRENT_PRESET_ID = "set_current_preset_id"
        UPDATE_PRESET_MODELS = "update_preset_models"
        SAVE_PRESETS_ORDER = "save_presets_order"

    class History:
        """Работа с историей диалога (подготовка промпта — HistoryService)"""
        SAVE_AFTER_RESPONSE = "save_history_after_response"
        MESSAGE_COMPLETED = "history_message_completed"
        # Эмитится ПОСЛЕ фактического применения сжатия (история подрезана,
        # summary_count обновлён). Для обновления живых счётчиков в UI.
        COMPRESSED = "history_compressed"

    class RAG:
        GET_EMBEDDING = "rag_get_embedding"
        GET_EMBEDDINGS = "rag_get_embeddings"
        MODEL_CHANGED = "rag_model_changed"

    class Install:
        """Унифицированные события для менеджера установок"""
        RUN_WITH_UI = "run_install_with_ui"
        RUN_HEADLESS = "run_install_headless"

        TASK_STARTED = "install_task_started"
        TASK_PROGRESS = "install_task_progress"
        TASK_LOG = "install_task_log"
        TASK_FINISHED = "install_task_finished"
        TASK_FAILED = "install_task_failed"
        CATALOG_CHANGED = "install_catalog_changed"
        RUN_BLOCKING = "run_install_blocking"

        # Очередь установок (выполняются строго по одной за раз).
        # QUEUE_CHANGED: снимок очереди {"running": {...}|None, "pending": [{...}]}.
        # CANCEL_QUEUED: запрос отмены ещё не начатой задачи {"task_id": ...}.
        QUEUE_CHANGED = "install_queue_changed"
        CANCEL_QUEUED = "install_cancel_queued"
        CANCEL_RUNNING = "install_cancel_running"

    class Installable:
        LIST = "installable_list"
        GET = "installable_get"
        GET_STATUS = "installable_get_status"
        INSTALL = "installable_install"
        UNINSTALL = "installable_uninstall"
        INITIALIZE = "installable_initialize"
        # ConfigurableComponent: settings schema + load/save (used by AI Hub
        # "Settings" tab). Each handler returns its payload synchronously via
        GET_SETTINGS_SCHEMA = "installable_get_settings_schema"
        LOAD_SETTINGS = "installable_load_settings"
        SAVE_SETTINGS = "installable_save_settings"

    class Character:
        SET_CURRENT = "character_set_current"
        RELOAD_DATA = "character_reload_data"
        RELOAD_PROMPTS = "character_reload_prompts"
        CLEAR_HISTORY = "character_clear_history"
        CLEAR_ALL_HISTORIES = "character_clear_all_histories"

        CURRENT_CHANGED = "character_current_changed"

    class Protocols:
        GET_PROTOCOL_LIST = "get_protocol_list"
        GET_PROTOCOL_FULL = "get_protocol_full"
        GET_TRANSFORM_LIST = "get_transform_list"
        BUILD_HTTP_REQUEST = "build_protocol_http_request"

    class AI:
        """События для AI hub / engine процессов"""
        GET_ENGINE = "ai_get_engine"
        ENGINE_EVENT = "ai_engine_event"
        RESTART_SERVICE = "ai_restart_service"
        SERVICE_RESTARTED = "ai_service_restarted"

    class EmbeddingPresets:
        """События для управления пресетами провайдеров эмбеддингов"""
        GET_PRESET_LIST = "embed_get_preset_list"
        GET_PRESET_FULL = "embed_get_preset_full"
        SAVE_CUSTOM_PRESET = "embed_save_custom_preset"
        DELETE_CUSTOM_PRESET = "embed_delete_custom_preset"
        RENAME_CUSTOM_PRESET = "embed_rename_custom_preset"
        REORDER_PRESETS = "embed_reorder_presets"
        TEST_PRESET = "embed_test_preset"
        TEST_RESULT = "embed_test_result"
        PRESET_SAVED = "embed_preset_saved"
        PRESET_DELETED = "embed_preset_deleted"
