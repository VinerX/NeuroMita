from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol


class UiTopic(StrEnum):
    AI_RESTART_SERVICE = "ai_restart_service"

    API_PRESET_DELETE = "delete_custom_preset"
    API_PRESET_DELETED = "preset_deleted"
    API_PRESET_SAVED = "preset_saved"
    API_PRESET_SAVE_ORDER = "save_presets_order"
    API_PRESET_SAVE_STATE = "save_preset_state"
    API_PRESET_SET_CURRENT = "set_current_preset_id"
    API_PRESET_TEST = "test_connection"
    API_PRESET_TEST_FAILED = "test_failed"
    API_PRESET_TEST_RESULT = "test_result"

    CHARACTER_CLEAR_ALL_HISTORIES = "character_clear_all_histories"
    CHARACTER_CLEAR_HISTORY = "character_clear_history"
    CHARACTER_CURRENT_CHANGED = "character_current_changed"
    CHARACTER_RELOAD_DATA = "character_reload_data"
    CHARACTER_SET_CURRENT = "character_set_current"

    CHAT_CLEAR_STAGED_IMAGES = "clear_staged_images"
    CHAT_DELETE_MESSAGE = "chat_delete_message"
    CHAT_DELETE_MESSAGES_FROM = "chat_delete_messages_from"
    CHAT_REGENERATE = "chat_regenerate"
    CHAT_REGENERATE_FROM = "chat_regenerate_from"
    CHAT_STAGE_IMAGE = "stage_image"

    EMBEDDING_PRESET_TEST = "embed_test_preset"
    EMBEDDING_PRESET_TEST_RESULT = "embed_test_result"

    GUI_SET_SETTINGS_ICON_INDICATOR = "set_settings_icon_indicator"
    GUI_SHOW_ERROR = "show_error_message"
    GUI_SHOW_INFO = "show_info_message"
    GUI_SHOW_WINDOW = "show_window"
    GUI_UPDATE_STATUS_COLORS = "update_status_colors"
    GUI_UPDATE_TOKEN_COUNT = "update_token_count_ui"
    GUI_VOICEOVER_MODEL_SELECTED = "voiceover_model_selected"
    GUI_VOICEOVER_REFRESH = "voiceover_refresh"

    HISTORY_COMPRESSED = "history_compressed"

    INSTALL_CANCEL_QUEUED = "install_cancel_queued"
    INSTALL_CANCEL_RUNNING = "install_cancel_running"
    INSTALL_QUEUE_CHANGED = "install_queue_changed"
    INSTALL_TASK_FAILED = "install_task_failed"
    INSTALL_TASK_FINISHED = "install_task_finished"
    INSTALL_TASK_PROGRESS = "install_task_progress"
    INSTALL_TASK_STARTED = "install_task_started"

    INSTALLABLE_INITIALIZE = "installable_initialize"
    INSTALLABLE_INSTALL = "installable_install"
    INSTALLABLE_UNINSTALL = "installable_uninstall"

    MODEL_FAILED = "on_failed_response"
    MODEL_STARTED = "on_started_response_generation"
    MODEL_SUCCESS = "on_successful_response"

    SPEECH_RESTART = "restart_speech_recognition"
    SPEECH_SET_MICROPHONE = "set_microphone"
    SPEECH_SET_RECOGNIZER_OPTION = "set_recognizer_option"

    TELEGRAM_START_SILERO = "telegram_start_silero"

    VOICE_MODEL_CLEAR_DESCRIPTION = "clear_voice_model_description"
    VOICE_MODEL_CLOSE_DIALOG = "close_voice_model_dialog"
    VOICE_MODEL_INSTALL = "install_voice_model"
    VOICE_MODEL_INSTALL_FINISHED = "voice_model_install_finished"
    VOICE_MODEL_OPEN_DOC = "open_voice_model_doc"
    VOICE_MODEL_REFRESH_PANELS = "refresh_voice_model_panels"
    VOICE_MODEL_SAVE_SETTINGS = "save_voice_model_settings"
    VOICE_MODEL_UNINSTALL = "uninstall_voice_model"
    VOICE_MODEL_UPDATE_DESCRIPTION = "update_voice_model_description"


class UiSettingsDataKey(StrEnum):
    API_PROVIDER_NAMES = "api_provider_names"
    CAMERA_LIST = "camera_list"
    CHARACTER_SETTINGS_SNAPSHOT = "character_settings_snapshot"
    EMBED_PRESET_ITEMS = "embed_preset_items"
    RAG_CE_STATUS = "rag_ce_status"
    RAG_EMBED_STATUS = "rag_embed_status"


@dataclass(frozen=True, slots=True)
class UiEvent:
    topic: UiTopic
    data: Any = None
    timestamp: float | None = None


class UiSubscription(Protocol):
    def close(self) -> None: ...


class UiEventsPort(Protocol):
    def publish(self, topic: UiTopic, data: Any = None) -> None: ...
    def subscribe(
        self,
        topic: UiTopic,
        callback: Callable[[UiEvent], None],
        *,
        weak: bool = True,
    ) -> UiSubscription: ...


class UiSettingsPort(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def save(self) -> None: ...
    def snapshot(self, keys: tuple[str, ...] | None = None) -> dict[str, Any]: ...


class UiApplicationPort(Protocol):
    @property
    def backend_ready(self) -> bool: ...

    @property
    def startup_error(self) -> str: ...

    def ensure_feature_async(self, feature: str): ...
    def ensure_optional_gui(self, feature: str) -> None: ...


class UiTaskPort(Protocol):
    def run(
        self,
        target: Any,
        worker: Callable[[], Any],
        on_ok: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        *,
        name: str = "gui-async",
    ): ...

    def dispatch(self, target: Any, callback: Callable[[], None]) -> bool: ...


class UiSettingsDataPort(Protocol):
    def get(self, key: UiSettingsDataKey | str, default: Any = None) -> Any: ...
    def request(
        self,
        target: Any,
        key: UiSettingsDataKey | str,
        worker: Callable[[], Any],
        on_ready: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        *,
        name: str | None = None,
        force: bool = False,
    ): ...
    def prefetch_section(self, gui: Any, category: str) -> None: ...
    def embed_preset_items_from_meta(self, meta: Any) -> list[tuple[str, Any]]: ...


class UiProviderOptionsPort(Protocol):
    def current(self) -> list[Any]: ...
    def load_async(self, gui: Any, setting_keys: tuple[str, ...], *, name: str): ...


class UiSettingsSectionsPort(Protocol):
    def wire_api(self, gui: Any): ...
    def wire_characters(self, gui: Any): ...
    def wire_microphone(self, gui: Any): ...
    def load_microphone(self, gui: Any) -> None: ...
    def wire_voiceover(self, gui: Any): ...
    def build_updates(self, gui: Any, parent: Any) -> None: ...


class UiRagPort(Protocol):
    def build_memory_section(self, gui: Any, parent: Any, provider_options: list[Any]) -> None: ...
    def build_rag_section(self, gui: Any, parent: Any, provider_options: list[Any]) -> None: ...
    def download_embed_model(self, gui: Any) -> None: ...
    def is_embed_model_downloaded(self) -> bool: ...
    def embed_status_text(self) -> str: ...


class UiPresentationPort(Protocol):
    events: UiEventsPort
    settings: UiSettingsPort
    app: UiApplicationPort
    tasks: UiTaskPort
    settings_data: UiSettingsDataPort
    providers: UiProviderOptionsPort
    settings_sections: UiSettingsSectionsPort
    rag: UiRagPort
    api_presets: Any
    embeddings: Any
    characters: Any
    capture: Any
    finetune: Any
    prompts: Any
    telegram: Any
    voice: Any
    installables: Any
    beats: Any
    home: Any
    sandbox: Any
    news: Any


def resolve_presentation(target: Any) -> UiPresentationPort:
    """Resolve the injected presentation boundary without importing controllers."""

    seen: set[int] = set()
    pending = [target]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        presentation = getattr(current, "presentation", None)
        if presentation is not None:
            return presentation
        for attr_name in ("gui", "view"):
            nested = getattr(current, attr_name, None)
            if nested is not None and id(nested) not in seen:
                pending.append(nested)
        try:
            parent = current.parent()
            if parent is not None and id(parent) not in seen:
                pending.append(parent)
        except Exception:
            pass
    raise RuntimeError("UI object is not attached to a presentation boundary")


def run_ui_async(
    target: Any,
    worker: Callable[[], Any],
    on_ok: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    *,
    name: str = "gui-async",
):
    return resolve_presentation(target).tasks.run(
        target,
        worker,
        on_ok,
        on_error,
        name=name,
    )


def dispatch_ui(target: Any, callback: Callable[[], None]) -> bool:
    return bool(resolve_presentation(target).tasks.dispatch(target, callback))
