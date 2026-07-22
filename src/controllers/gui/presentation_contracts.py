from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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
    CHAT_RETRY_LAST = "chat_retry_last"
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
    INSTALL_CATALOG_CHANGED = "install_catalog_changed"
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
