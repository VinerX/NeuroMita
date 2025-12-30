import threading
from typing import Dict, List, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import weakref
from dataclasses import dataclass
from queue import Queue, Empty
import time
from main_logger import logger


@dataclass
class Event:
    """Базовый класс для всех событий"""
    name: str
    data: Any = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class EventBus:
    """
    Потокобезопасная система событий с поддержкой слабых ссылок
    для предотвращения утечек памяти
    """
    
    def __init__(self, max_workers: int = 5):
        self._subscribers: Dict[str, List[weakref.ref]] = {}
        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        wait_workers = max(8, max_workers * 2)
        self._wait_executor = ThreadPoolExecutor(max_workers=wait_workers)

        self._event_queue = Queue()
        self._running = True
        self._processor_thread = threading.Thread(target=self._process_events, daemon=True)
        self._processor_thread.start()
    
    def subscribe(self, event_name: str, callback: Callable, weak: bool = True) -> None:
        """
        Подписаться на событие
        
        Args:
            event_name: Имя события
            callback: Функция обратного вызова
            weak: Использовать слабую ссылку (рекомендуется True)
        """
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            
            if weak:
                # Используем слабую ссылку для предотвращения циклических ссылок
                weak_ref = weakref.ref(callback, self._create_cleanup_callback(event_name))
                self._subscribers[event_name].append(weak_ref)
            else:
                # Для статических функций можно использовать сильные ссылки
                self._subscribers[event_name].append(callback)
            
            logger.debug(f"Подписка на событие '{event_name}' добавлена")
    
    def unsubscribe(self, event_name: str, callback: Callable) -> None:
        """Отписаться от события"""
        with self._lock:
            if event_name not in self._subscribers:
                return
            
            # Удаляем callback из списка подписчиков
            self._subscribers[event_name] = [
                ref for ref in self._subscribers[event_name]
                if not self._is_same_callback(ref, callback)
            ]
            
            # Удаляем пустые списки
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]
    
    def emit(self, event_name: str, data: Any = None, sync: bool = False) -> None:
        """
        Отправить событие
        
        Args:
            event_name: Имя события
            data: Данные события
            sync: Выполнить синхронно (блокирующий вызов)
        """
        event = Event(name=event_name, data=data)
        
        # Добавить отладку
        with self._lock:
            subscribers_count = len(self._get_active_subscribers(event_name))
            if subscribers_count > 0:
                logger.debug(f"Emitting event '{event_name}' to {subscribers_count} subscribers")
            else:
                logger.warning(f"No subscribers for event '{event_name}'")
        
        if sync:
            self._emit_sync(event)
        else:
            self._event_queue.put(event)
    
    def emit_and_wait(self, event_name: str, data: Any = None, timeout: float = 5.0) -> List[Any]:
        """
        Отправить событие и дождаться результатов от всех подписчиков

        Returns:
            Список результатов от подписчиков
        """
        results: List[Any] = []
        result_queue: Queue = Queue()

        def result_wrapper(callback):
            def wrapper(*args, **kwargs):
                try:
                    result = callback(*args, **kwargs)
                    result_queue.put(result)
                except Exception as e:
                    logger.error("Произошла ошибка в событии, коллектим:")
                    callback_name = getattr(callback, "__qualname__", getattr(callback, "__name__", "unknown"))
                    event_name_for_log = "неизвестного события"
                    if args and isinstance(args[0], Event):
                        event_name_for_log = f"события '{args[0].name}'"
                    logger.error(
                        f"Ошибка в обработчике '{callback_name}' для {event_name_for_log}: {e}",
                        exc_info=True
                    )
                    result_queue.put(None)
            return wrapper

        with self._lock:
            subscribers = self._get_active_subscribers(event_name)

        if not subscribers:
            return results

        for subscriber in subscribers:
            wrapped = result_wrapper(subscriber)
            self._wait_executor.submit(wrapped, Event(name=event_name, data=data))

        start_time = time.time()
        collected = 0
        target = len(subscribers)

        while collected < target and (time.time() - start_time) < float(timeout):
            try:
                result = result_queue.get(timeout=0.1)
                if result is not None:
                    results.append(result)
                collected += 1
            except Empty:
                continue

        return results

    
    def shutdown(self) -> None:
        """Остановить систему событий"""
        self._running = False
        self._event_queue.put(None)  # Сигнал для остановки
        self._processor_thread.join(timeout=5)

        try:
            self._executor.shutdown(wait=True)
        finally:
            self._wait_executor.shutdown(wait=True)
    
    def _process_events(self) -> None:
        """Обработчик очереди событий (работает в отдельном потоке)"""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.1)
                if event is None:  # Сигнал остановки
                    break
                
                self._emit_async(event)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Ошибка при обработке события: {e}", exc_info=True)
    
    def _emit_sync(self, event: Event) -> None:
        """Синхронная отправка события"""
        with self._lock:
            subscribers = self._get_active_subscribers(event.name)
        
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception as e:
                logger.error(f"Ошибка при обработке события '{event.name}': {e}", exc_info=True)
    
    def _emit_async(self, event: Event) -> None:
        """Асинхронная отправка события"""
        with self._lock:
            subscribers = self._get_active_subscribers(event.name)
        
        for subscriber in subscribers:
            self._executor.submit(self._safe_call, subscriber, event)
    
    def _safe_call(self, callback: Callable, event: Event) -> None:
        """Безопасный вызов обработчика"""
        try:
            callback(event)
        except Exception as e:
            logger.error(f"Ошибка при обработке события '{event.name}': {e}", exc_info=True)
    
    def _get_active_subscribers(self, event_name: str) -> List[Callable]:
        """Получить список активных подписчиков"""
        if event_name not in self._subscribers:
            return []
        
        active_subscribers = []
        dead_refs = []
        
        for ref in self._subscribers[event_name]:
            if isinstance(ref, weakref.ref):
                callback = ref()
                if callback is not None:
                    active_subscribers.append(callback)
                else:
                    dead_refs.append(ref)
            else:
                # Сильная ссылка
                active_subscribers.append(ref)
        
        # Очистка мертвых ссылок
        if dead_refs:
            for dead_ref in dead_refs:
                self._subscribers[event_name].remove(dead_ref)
        
        return active_subscribers
    
    def _create_cleanup_callback(self, event_name: str):
        """Создать callback для очистки мертвых ссылок"""
        def cleanup(weak_ref):
            with self._lock:
                if event_name in self._subscribers:
                    try:
                        self._subscribers[event_name].remove(weak_ref)
                        if not self._subscribers[event_name]:
                            del self._subscribers[event_name]
                    except ValueError:
                        pass
        return cleanup
    
    def _is_same_callback(self, ref: Any, callback: Callable) -> bool:
        """Проверить, указывает ли ссылка на тот же callback"""
        if isinstance(ref, weakref.ref):
            return ref() is callback
        else:
            return ref is callback


# Глобальный экземпляр для удобства использования
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Получить глобальный экземпляр EventBus"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def shutdown_event_bus() -> None:
    """Остановить глобальный EventBus"""
    global _global_event_bus
    if _global_event_bus is not None:
        _global_event_bus.shutdown()
        _global_event_bus = None


# Удобные алиасы для быстрого доступа
def subscribe(event_name: str, callback: Callable, weak: bool = True) -> None:
    """Подписаться на событие через глобальный EventBus"""
    get_event_bus().subscribe(event_name, callback, weak)


def unsubscribe(event_name: str, callback: Callable) -> None:
    """Отписаться от события через глобальный EventBus"""
    get_event_bus().unsubscribe(event_name, callback)


def emit(event_name: str, data: Any = None, sync: bool = False) -> None:
    """Отправить событие через глобальный EventBus"""
    get_event_bus().emit(event_name, data, sync)


def emit_and_wait(event_name: str, data: Any = None, timeout: float = 5.0) -> List[Any]:
    """Отправить событие и дождаться результатов через глобальный EventBus"""
    return get_event_bus().emit_and_wait(event_name, data, timeout)


# Определение имен событий для типобезопасности

# src/core/events.py

class Events:
    """
    Константы с именами событий, сгруппированные по логическим модулям.
    Доступ возможен как Events.EVENT_NAME, так и Events.GROUP.EVENT_NAME.
    """

    class Core:
        """Системные и межкомпонентные события"""
        GET_EVENT_LOOP = "get_event_loop"
        LOOP_READY = "loop_ready"
        RUN_IN_LOOP = "run_in_loop"
        SETTING_CHANGED = "setting_changed"

    class GUI:
        """События, предназначенные для GuiController и его суб-контроллеров"""
        UPDATE_TOKEN_COUNT = "update_token_count"
        UPDATE_STATUS = "update_status"
        UPDATE_DEBUG_INFO = "update_debug_info"
        SHOW_MITA_THINKING = "show_mita_thinking"
        SHOW_MITA_ERROR = "show_mita_error"
        HIDE_MITA_STATUS = "hide_mita_status"
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
        CHECK_USER_ENTRY_EXISTS = "check_user_entry_exists"
        SWITCH_VOICEOVER_SETTINGS = "switch_voiceover_settings"
        SHOW_INFO_MESSAGE = "show_info_message"
        UPDATE_CHAT_FONT_SIZE = "update_chat_font_size"
        RELOAD_CHAT_HISTORY = "reload_chat_history"
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

    class Model:
        """События для управления LLM, персонажами и историей"""
        LOAD_HISTORY = "load_history"
        GET_CHAT_HISTORY = "get_chat_history"
        LOAD_MORE_HISTORY = "load_more_history"
        SCHEDULE_G4F_UPDATE = "schedule_g4f_update"
        GET_CHARACTER_NAME = "get_character_name"
        GET_CURRENT_CONTEXT_TOKENS = "get_current_context_tokens"
        CALCULATE_COST = "calculate_cost"
        GET_ALL_CHARACTERS = "get_all_characters"
        GET_CURRENT_CHARACTER = "get_current_character"
        SET_CHARACTER_TO_CHANGE = "set_character_to_change"
        CHECK_CHANGE_CHARACTER = "check_change_character"
        GET_CHARACTER = "get_character"
        RELOAD_CHARACTER_DATA = "reload_character_data"
        RELOAD_CHARACTER_PROMPTS = "reload_character_prompts"
        CLEAR_CHARACTER_HISTORY = "clear_character_history"
        CLEAR_ALL_HISTORIES = "clear_all_histories"
        RELOAD_PROMPTS_ASYNC = "reload_prompts_async"
        GET_DEBUG_INFO = "get_debug_info"
        ON_STARTED_RESPONSE_GENERATION = "on_started_response_generation"
        ON_SUCCESSFUL_RESPONSE = "on_successful_response"
        ON_FAILED_RESPONSE = "on_failed_response"
        ON_FAILED_RESPONSE_ATTEMPT = "on_failed_attempt_for_response"
        ADD_TEMPORARY_SYSTEM_INFO = "add_temporary_system_info"
        GENERATE_RESPONSE = "generate_response"
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
        GET_USER_INPUT = "get_user_input"
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
        GET_GAME_CONNECTION = "get_connection_status"
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

    class Settings:
        """События для управления настройками"""
        SAVE_SETTING = "save_setting"
        GET_SETTING = "get_setting"
        LOAD_SETTINGS = "load_settings"
        GET_SETTINGS = "get_settings"
        GET_APP_VARS = "get_app_vars"

    class VoiceModel:
        """События для управления локальными голосовыми моделями"""
        GET_MODEL_DATA = "get_voice_model_data"
        GET_INSTALLED_MODELS = "get_installed_models"
        GET_DEPENDENCIES_STATUS = "get_dependencies_status"
        GET_DEFAULT_DESCRIPTION = "get_default_description"
        GET_MODEL_DESCRIPTION = "get_model_description"
        GET_SETTING_DESCRIPTION = "get_setting_description"
        GET_SECTION_VALUES = "get_section_values"
        CHECK_GPU_RTX30_40 = "check_gpu_rtx30_40"
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

    class Prompt:
        """Сборка промптов для LLM"""
        BUILD_PROMPT = "build_prompt"

    class History:
        """Работа с историей диалога"""
        PREPARE_FOR_PROMPT = "prepare_history_for_prompt"
        SAVE_AFTER_RESPONSE = "save_history_after_response"

    class Install:
        """Унифицированные события для менеджера установок"""
        RUN_WITH_UI = "run_install_with_ui"
        RUN_HEADLESS = "run_install_headless"

        TASK_STARTED = "install_task_started"
        TASK_PROGRESS = "install_task_progress"
        TASK_LOG = "install_task_log"
        TASK_FINISHED = "install_task_finished"
        TASK_FAILED = "install_task_failed"