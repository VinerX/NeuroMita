from PyQt6.QtCore import QCoreApplication, QThread, QTimer
from main_logger import logger
from core.events import get_event_bus
from core.services import use
from core.task_supervisor import task_supervisor
from controllers.gui.qt_dispatch import dispatch_to_qt
from services.contracts import GuiInteractionService, SettingsService

from .gui.status_controller import StatusController
from .gui.chat_controller import ChatController
from .gui.system_controller import SystemController
from .gui.dialog_controller import DialogController
from .gui.settings_controller import SettingsController
from .gui.model_event_controller import ModelEventController
from .gui.view_event_controller import ViewEventController
from .gui.window_manager_controller import WindowManagerController
from .gui.protocol_pipeline_gui_controller import ProtocolPipelineGuiController

from .gui.settings_sidebar_controller import SettingsSidebarController


class GuiController(GuiInteractionService):
    def __init__(self, main_controller, view):
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            message = "GuiController must be constructed on the Qt GUI thread"
            logger.critical(message)
            raise RuntimeError(message)

        self.main_controller = main_controller
        self.view = view
        self.event_bus = get_event_bus()
        self._gui_thread = app.thread()
        self._closed = False

        self.voice_language_var = None
        self.local_voice_combobox = None
        self.debug_window = None
        self.mic_combobox = None
        self.chat_window = None
        self.token_count_label = None
        self.user_entry = None
        self.attachment_label = None
        self.attach_button = None
        self.send_screen_button = None
        self.ffmpeg_install_popup = None
        self.game_connected_checkbox_var = False

        logger.info(f"GuiController инициализирован с view типа: {type(self.view)}")

        self.status_controller = StatusController(main_controller, view)
        self.chat_controller = ChatController(main_controller, view)
        self.system_controller = SystemController(main_controller, view)

        self.settings_sidebar_controller = SettingsSidebarController(main_controller, view)

        self.voiceover_controller = None
        self.audio_model_controller = None
        self.voice_model_gui_controller = None
        self.microphone_settings_controller = None
        self.asr_events_controller = None
        self.asr_glossary_controller = None
        self.install_gui_controller = None
        self._optional_gui_features: dict[str, tuple[object, ...]] = {}
        self._settings_service = use(SettingsService)
        self._settings_subscription = self._settings_service.subscribe(
            self._on_setting_changed,
            keys=("USE_VOICEOVER", "VOICEOVER_METHOD", "MIC_ACTIVE"),
        )

        self.dialog_controller = DialogController(main_controller, view)
        self.settings_controller = SettingsController(main_controller, view)
        self.model_event_controller = ModelEventController(main_controller, view)
        self.view_event_controller = ViewEventController(main_controller, view)
        self.window_manager_controller = WindowManagerController(main_controller, view)

        self.protocol_pipeline_gui_controller = ProtocolPipelineGuiController(main_controller, view)

        self._connect_view_signals()
        logger.info("GuiController подписался на события")

        if bool(getattr(self.main_controller, "backend_enabled", True)):
            settings = getattr(self.main_controller, "settings", None)
            voice_enabled = bool(settings and settings.get("USE_VOICEOVER", False))
            mic_enabled = bool(settings and settings.get("MIC_ACTIVE", False))
            if voice_enabled or mic_enabled:
                QTimer.singleShot(100, self.system_controller.check_and_install_ffmpeg)

            if voice_enabled:
                QTimer.singleShot(0, lambda: self.ensure_optional_gui("voice"))
            if mic_enabled:
                QTimer.singleShot(0, lambda: self.ensure_optional_gui("speech"))


    def native_window_id(self) -> int | None:
        if self.view is not None and hasattr(self.view, "winId"):
            return int(self.view.winId())
        return None

    def confirm(self, kind: str, payload: dict) -> bool:
        window_manager = getattr(self.view, "window_manager", None)
        if window_manager is None:
            return False
        normalized = str(kind or "").strip().lower()
        if normalized == "vc_redist":
            result = window_manager.show_dialog_blocking("vc_redist_dialog", dict(payload or {}))
            return str(result.get("choice", "close")).lower() in {"install", "yes", "ok", "continue"}
        if normalized == "triton":
            result = window_manager.show_dialog_blocking(
                "triton_deps_dialog", {"dependencies_status": dict(payload or {})}
            )
            return str(result.get("choice", "skip")).lower() in {"install", "yes", "ok", "continue"}
        return False

    def _dispatch_ui(self, callback) -> None:
        if self._closed or not callable(callback):
            return
        signal = getattr(self.view, "run_ui_task_signal", None)
        if signal is not None:
            try:
                signal.emit(callback)
                return
            except RuntimeError:
                pass
        if not dispatch_to_qt(callback):
            logger.debug(
                "Dropped GuiController callback because the Qt dispatcher is unavailable"
            )

    def _on_setting_changed(self, change) -> None:
        key = str(getattr(change, "key", ""))
        value = getattr(change, "value", None)
        if key == "USE_VOICEOVER" and bool(value):
            self._dispatch_ui(lambda: self._activate_optional_gui("voice", needs_ffmpeg=True))
        elif key == "MIC_ACTIVE" and bool(value):
            self._dispatch_ui(lambda: self._activate_optional_gui("speech", needs_ffmpeg=True))
        elif key == "VOICEOVER_METHOD" and bool(
            self._settings_service.get("USE_VOICEOVER", False)
        ):
            self._dispatch_ui(lambda: self._activate_optional_gui("voice", needs_ffmpeg=True))

    def _activate_optional_gui(self, name: str, *, needs_ffmpeg: bool = False):
        created = self.ensure_optional_gui(name)
        if needs_ffmpeg:
            QTimer.singleShot(0, self.system_controller.check_and_install_ffmpeg)
        return created

    def ensure_optional_gui(self, name: str):
        if self._closed:
            raise RuntimeError("GUI controller is closed")
        if QThread.currentThread() != self._gui_thread:
            message = (
                f"Optional GUI feature '{name}' was requested outside the Qt GUI thread"
            )
            logger.critical(message)
            raise RuntimeError(message)

        normalized = str(name or "").strip().lower()
        existing = self._optional_gui_features.get(normalized)
        if existing is not None:
            return existing

        if normalized == "voice":
            from .gui.audio_model_controller import AudioModelController
            from .gui.voice_model_controller import VoiceModelGuiController
            from .gui.voiceover_controller import VoiceoverGuiController

            self.voiceover_controller = VoiceoverGuiController(self.main_controller, self.view)
            self.audio_model_controller = AudioModelController(self.main_controller, self.view)
            self.voice_model_gui_controller = VoiceModelGuiController(self.main_controller, self.view)
            created = (
                self.voiceover_controller,
                self.audio_model_controller,
                self.voice_model_gui_controller,
            )

            settings = getattr(self.main_controller, "settings", None)
            autoload = bool(settings and settings.get("LOCAL_VOICE_LOAD_LAST", False))
            local_method = str(
                settings.get("VOICEOVER_METHOD", "Local") if settings else "Local"
            ).strip().lower() == "local"
            if autoload and local_method:
                QTimer.singleShot(0, self.voiceover_controller.autoload_last_model_on_startup)

        elif normalized == "speech":
            from .gui.asr_events_controller import AsrEventsController
            from .gui.asr_glossary_controller import AsrGlossaryGuiController
            from .gui.microphone_settings_controller import MicrophoneSettingsController

            self.microphone_settings_controller = MicrophoneSettingsController(
                self.main_controller, self.view
            )
            self.asr_events_controller = AsrEventsController(self.main_controller, self.view)
            self.asr_glossary_controller = AsrGlossaryGuiController(
                self.main_controller, self.view
            )
            created = (
                self.microphone_settings_controller,
                self.asr_events_controller,
                self.asr_glossary_controller,
            )

        elif normalized == "install":
            from .gui.install_gui_controller import InstallGuiController

            self.install_gui_controller = InstallGuiController(
                self.main_controller, self.view
            )
            created = (self.install_gui_controller,)
        else:
            raise KeyError(f"Unknown optional GUI feature: {name}")

        self._optional_gui_features[normalized] = created
        logger.info(f"Optional GUI feature ready: {normalized}")
        return created

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscription = getattr(self, "_settings_subscription", None)
        self._settings_subscription = None
        if subscription is not None:
            try:
                subscription.close()
            except Exception:
                logger.exception("Failed to close GUI settings subscription")

        controllers: list[object] = []
        for group in self._optional_gui_features.values():
            controllers.extend(group)
        controllers.extend(
            controller
            for controller in (
                self.status_controller,
                self.chat_controller,
                self.system_controller,
                self.settings_sidebar_controller,
                self.dialog_controller,
                self.settings_controller,
                self.model_event_controller,
                self.view_event_controller,
                self.window_manager_controller,
                self.protocol_pipeline_gui_controller,
            )
            if controller is not None
        )

        seen: set[int] = set()
        for controller in reversed(controllers):
            if id(controller) in seen:
                continue
            seen.add(id(controller))
            close = getattr(controller, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception:
                logger.exception(
                    "Failed to close GUI controller %s",
                    type(controller).__name__,
                )

        self._optional_gui_features.clear()
        try:
            self.event_bus.unsubscribe_owner(self)
        except Exception:
            logger.exception("Failed to detach GuiController from EventBus")
        task_supervisor().cancel_owner(self, timeout=1.0)

    def _connect_view_signals(self):
        if self.view:
            self.view.clear_user_input_signal = getattr(self.view, "clear_user_input_signal", None)
            self.view.update_chat_font_size_signal = getattr(self.view, "update_chat_font_size_signal", None)
            self.view.switch_voiceover_settings_signal = getattr(self.view, "switch_voiceover_settings_signal", None)
            self.view.load_chat_history_signal = getattr(self.view, "load_chat_history_signal", None)
            self.view.check_triton_dependencies_signal = getattr(self.view, "check_triton_dependencies_signal", None)
            self.view.show_info_message_signal = getattr(self.view, "show_info_message_signal", None)
            self.view.show_error_message_signal = getattr(self.view, "show_error_message_signal", None)
            self.view.update_model_loading_status_signal = getattr(self.view, "update_model_loading_status_signal", None)
            self.view.finish_model_loading_signal = getattr(self.view, "finish_model_loading_signal", None)
            self.view.cancel_model_loading_signal = getattr(self.view, "cancel_model_loading_signal", None)

    def update_status_colors(self):
        self.status_controller.update_status_colors()

    def clear_user_input(self):
        self.chat_controller.clear_user_input()

    def show_mita_thinking(self, character_name):
        self.status_controller.show_mita_thinking(character_name)

    def show_mita_error(self, error_message):
        self.status_controller.show_mita_error(error_message)

    def hide_mita_status(self):
        self.status_controller.hide_mita_status()

    def show_mita_error_pulse(self):
        self.status_controller.show_mita_error_pulse()

    def get_user_input(self):
        return self.chat_controller.get_user_input()

    def check_and_install_ffmpeg(self):
        self.system_controller.check_and_install_ffmpeg()

    def stream_callback_handler(self, chunk: str):
        self.chat_controller.stream_callback_handler(chunk)

    def prepare_stream(self):
        self.chat_controller.prepare_stream()

    def finish_stream(self):
        self.chat_controller.finish_stream()

    def update_chat(self, role, response, is_initial, emotion):
        self.chat_controller.update_chat(role, response, is_initial, emotion)

    def update_status(self):
        self.status_controller.update_status()

    def update_debug(self):
        self.system_controller.update_debug()

    def update_token_count(self):
        self.chat_controller.update_token_count()

    def cleanup(self):
        subscription = getattr(self, "_settings_subscription", None)
        if subscription is not None:
            subscription.close()
            self._settings_subscription = None

        owned_controllers = (
            self.status_controller,
            self.chat_controller,
            self.system_controller,
            self.settings_sidebar_controller,
            self.dialog_controller,
            self.settings_controller,
            self.model_event_controller,
            self.view_event_controller,
            self.window_manager_controller,
            self.protocol_pipeline_gui_controller,
            self.voiceover_controller,
            self.audio_model_controller,
            self.voice_model_gui_controller,
            self.microphone_settings_controller,
            self.asr_events_controller,
            self.asr_glossary_controller,
            self.install_gui_controller,
        )
        for controller in owned_controllers:
            close = getattr(controller, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        audio_model_controller = self.audio_model_controller
        if audio_model_controller is not None and hasattr(
            audio_model_controller, "_voice_model_controller"
        ):
            audio_model_controller._voice_model_controller = None
        self._optional_gui_features.clear()
