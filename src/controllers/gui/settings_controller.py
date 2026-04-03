from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

class SettingsController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.SWITCH_VOICEOVER_SETTINGS, self._on_switch_voiceover_settings, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_CHAT_FONT_SIZE, self._on_update_chat_font_size, weak=False)
        self.event_bus.subscribe(Events.GUI.RELOAD_CHAT_HISTORY, self._on_reload_chat_history, weak=False)
        self.event_bus.subscribe(Events.GUI.REMOVE_LAST_CHAT_WIDGETS, self._on_remove_last_chat_widgets, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        
    def _on_switch_voiceover_settings(self, event: Event):
        if self.view and hasattr(self.view, 'switch_voiceover_settings_signal') and self.view.switch_voiceover_settings_signal:
            self.view.switch_voiceover_settings_signal.emit()
        elif self.view and hasattr(self.view, 'switch_voiceover_settings'):
            self.view.switch_voiceover_settings()

    def _on_update_chat_font_size(self, event: Event):
        font_size = event.data.get('font_size', 12)
        if self.view and hasattr(self.view, 'update_chat_font_size_signal') and self.view.update_chat_font_size_signal:
            self.view.update_chat_font_size_signal.emit(font_size)
        elif self.view and hasattr(self.view, 'update_chat_font_size'):
            self.view.update_chat_font_size(font_size)

    def _on_reload_chat_history(self, event: Event):
        if self.view and hasattr(self.view, 'load_chat_history_signal') and self.view.load_chat_history_signal:
            self.view.load_chat_history_signal.emit()
        elif self.view and hasattr(self.view, 'load_chat_history'):
            self.view.load_chat_history()

    def _on_remove_last_chat_widgets(self, event: Event):
        count = int((event.data or {}).get("count", 1))
        if self.view and hasattr(self.view, 'remove_last_chat_widgets_signal'):
            self.view.remove_last_chat_widgets_signal.emit(count)
        elif self.view and hasattr(self.view, '_on_remove_last_chat_widgets'):
            self.view._on_remove_last_chat_widgets(count)

    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')

        if key in ["USE_VOICEOVER", "VOICEOVER_METHOD", "AUDIO_BOT", "NM_CURRENT_VOICEOVER", "VOICE_LANGUAGE", "LOCAL_VOICE_LOAD_LAST"]:
            self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)

        if key == "AUDIO_BOT":
            if isinstance(value, str) and value.startswith("@CrazyMitaAIbot"):
                self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                    "title": "Информация",
                    "message": "VinerX: наши товарищи из CrazyMitaAIbot предоставляет озвучку бесплатно буквально со своих пк, будет время - загляните к ним в тг, скажите спасибо)"
                })

        elif key == "CHAT_FONT_SIZE":
            try:
                font_size = int(value)
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_FONT_SIZE, {"font_size": font_size})
                self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
                logger.info(f"Размер шрифта чата изменен на: {font_size}")
            except ValueError:
                logger.warning(f"Неверное значение для размера шрифта: {value}")
            except Exception as e:
                logger.error(f"Ошибка при изменении размера шрифта: {e}")

        elif key in ["SHOW_CHAT_TIMESTAMPS", "MAX_CHAT_HISTORY_DISPLAY", "HIDE_CHAT_TAGS",
                     "SHOW_STRUCTURED_IN_GUI", "STRUCTURED_EXPANDED_DEFAULT", "CHAT_MAX_BUBBLE_WIDTH"]:
            self.event_bus.emit(Events.GUI.RELOAD_CHAT_HISTORY)
            logger.info(f"Настройка '{key}' изменена на: {value}. История чата перезагружена.")

        elif key == "SHOW_TOKEN_INFO":
            self.event_bus.emit(Events.GUI.UPDATE_TOKEN_COUNT)