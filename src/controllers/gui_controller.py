import time
from PyQt6.QtCore import QTimer
from main_logger import logger
from core.events import get_event_bus

from .gui.status_controller import StatusController
from .gui.chat_controller import ChatController
from .gui.system_controller import SystemController
from .gui.audio_model_controller import AudioModelController
from .gui.dialog_controller import DialogController
from .gui.settings_controller import SettingsController
from .gui.microphone_settings_controller import MicrophoneSettingsController
from .gui.model_event_controller import ModelEventController
from .gui.view_event_controller import ViewEventController
from .gui.voice_model_controller import VoiceModelGuiController
from .gui.window_manager_controller import WindowManagerController
from .gui.asr_events_controller import AsrEventsController
from .gui.asr_glossary_controller import AsrGlossaryGuiController
from .gui.install_gui_controller import InstallGuiController
from .gui.protocol_pipeline_gui_controller import ProtocolPipelineGuiController

from .gui.settings_sidebar_controller import SettingsSidebarController
from .gui.voiceover_controller import VoiceoverGuiController


class GuiController:
    def __init__(self, main_controller, view):
        self.main_controller = main_controller
        self.view = view
        self.event_bus = get_event_bus()

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
        self.voiceover_controller = VoiceoverGuiController(main_controller, view)

        self.audio_model_controller = AudioModelController(main_controller, view)
        self.dialog_controller = DialogController(main_controller, view)
        self.settings_controller = SettingsController(main_controller, view)
        self.microphone_settings_controller = MicrophoneSettingsController(main_controller, view)
        self.model_event_controller = ModelEventController(main_controller, view)
        self.view_event_controller = ViewEventController(main_controller, view)
        self.voice_model_gui_controller = VoiceModelGuiController(main_controller, view)

        self.asr_events_controller = AsrEventsController(main_controller, view)
        self.asr_glossary_controller = AsrGlossaryGuiController(main_controller, view)
        self.install_gui_controller = InstallGuiController(main_controller, view)
        self.window_manager_controller = WindowManagerController(main_controller, view)

        self.protocol_pipeline_gui_controller = ProtocolPipelineGuiController(main_controller, view)

        self._connect_view_signals()
        logger.info("GuiController подписался на события")

        QTimer.singleShot(100, self.system_controller.check_and_install_ffmpeg)

        QTimer.singleShot(500, self.voiceover_controller.autoload_last_model_on_startup)

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
        if hasattr(self.audio_model_controller, "_voice_model_controller"):
            self.audio_model_controller._voice_model_controller = None