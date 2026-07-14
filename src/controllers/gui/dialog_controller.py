from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from core.events import Events, Event
from .base_controller import BaseController

class DialogController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.SHOW_INFO_MESSAGE, self._on_show_info_message, weak=False)
        self.event_bus.subscribe(Events.GUI.SHOW_ERROR_MESSAGE, self._on_show_error_message, weak=False)
        self.event_bus.subscribe(Events.Telegram.PROMPT_FOR_TG_CODE, self._on_prompt_for_tg_code, weak=False)
        self.event_bus.subscribe(Events.Telegram.PROMPT_FOR_TG_PASSWORD, self._on_prompt_for_tg_password, weak=False)
        self.event_bus.subscribe(Events.GUI.SHOW_EULA_DIALOG, self._on_show_eula_dialog, weak=False)
        self.event_bus.subscribe(Events.GUI.SHOW_GUIDE, self._on_show_guide, weak=False)
        
    def _on_show_info_message(self, event: Event):
        title = event.data.get('title', 'Информация')
        message = event.data.get('message', '')
        if self.view and hasattr(self.view, 'show_info_message_signal') and self.view.show_info_message_signal:
            self.view.show_info_message_signal.emit({'title': title, 'message': message})
        elif self.view:
            QTimer.singleShot(0, lambda: QMessageBox.information(self.view, title, message))

    def _on_show_error_message(self, event: Event):
        title = event.data.get('title', 'Ошибка')
        message = event.data.get('message', '')
        if self.view and hasattr(self.view, 'show_error_message_signal') and self.view.show_error_message_signal:
            self.view.show_error_message_signal.emit({'title': title, 'message': message})
        elif self.view:
            QTimer.singleShot(0, lambda: QMessageBox.critical(self.view, title, message))
            
    def _on_prompt_for_tg_code(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        self.view.show_tg_code_dialog_signal.emit({
            "request_id": str(data.get("request_id") or ""),
            "error": data.get("error", ""),
        })

    def _on_prompt_for_tg_password(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        self.view.show_tg_password_dialog_signal.emit({
            "request_id": str(data.get("request_id") or ""),
            "error": data.get("error", ""),
        })

    def _on_show_eula_dialog(self, event: Event):
        if self.view and hasattr(self.view, '_show_eula_dialog'):
            QTimer.singleShot(0, self.view._show_eula_dialog)
            
    def _on_show_guide(self, event: Event):
        if self.view and hasattr(self.view, '_show_guide'):
            QTimer.singleShot(0, self.view._show_guide)