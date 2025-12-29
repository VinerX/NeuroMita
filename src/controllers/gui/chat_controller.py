from PyQt6.QtCore import QTimer
from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

class ChatController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.CLEAR_USER_INPUT_UI, self._on_clear_user_input_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.CLEAR_USER_INPUT, self._on_clear_user_input_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_CHAT_UI, self._on_update_chat_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.PREPARE_STREAM_UI, self._on_prepare_stream_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.APPEND_STREAM_CHUNK_UI, self._on_append_stream_chunk_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.FINISH_STREAM_UI, self._on_finish_stream_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_TOKEN_COUNT, self._on_update_token_count, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_TOKEN_COUNT_UI, self._on_update_token_count_ui, weak=False)
        self.event_bus.subscribe(Events.GUI.INSERT_TEXT_TO_INPUT, self._on_insert_text_to_input, weak=False)
        self.event_bus.subscribe(Events.GUI.CHECK_USER_ENTRY_EXISTS, self._on_check_user_entry_exists, weak=False)
        
    def clear_user_input(self):
        logger.debug("ChatController: clear_user_input")
        self.event_bus.emit(Events.GUI.CLEAR_USER_INPUT)
        if self.view and self.view.user_entry:
            self.view.user_entry.clear()
        else:
            logger.error("ChatController: view или user_entry не найден!")
            
    def get_user_input(self):
        if self.view and self.view.user_entry:
            result = self.view.user_entry.toPlainText().strip()
            logger.debug(f"ChatController: get_user_input возвращает: '{result}'")
            return result
        logger.warning("ChatController: view или user_entry не найден!")
        return ""
        
    def stream_callback_handler(self, chunk: str):
        logger.debug(f"ChatController: stream_callback_handler: {chunk[:50]}...")
        if self.view:
            self.view.append_stream_chunk_signal.emit(chunk)
        else:
            logger.error("ChatController: view не найден!")
            
    def prepare_stream(self):
        logger.info("ChatController: prepare_stream")
        if self.view:
            self.view.prepare_stream_signal.emit()
        else:
            logger.error("ChatController: view не найден!")
            
    def finish_stream(self):
        logger.info("ChatController: finish_stream")
        if self.view:
            self.view.finish_stream_signal.emit()
        else:
            logger.error("ChatController: view не найден!")
            
    def update_chat(self, role, response, is_initial, emotion):
        logger.info(f"ChatController: update_chat - role: {role}, response: {response[:50]}..., is_initial: {is_initial}, emotion: {emotion}")
        if self.view:
            print(f"[DEBUG] ChatController: эмитим update_chat_signal с данными role={role}, response={response[:50]}...")
            self.view.update_chat_signal.emit(role, response, is_initial, emotion)
        else:
            print("[DEBUG] ChatController: view не найден!")
            logger.error("ChatController: view не найден!")
            
    def update_token_count(self):
        logger.debug("ChatController: update_token_count")
        if self.view:
            QTimer.singleShot(0, self.view.update_token_count)
        else:
            logger.error("ChatController: view не найден!")
            
    def _on_clear_user_input_ui(self, event: Event):
        logger.debug("ChatController: получено событие CLEAR_USER_INPUT_UI")
        self.clear_user_input()
        
    def _on_update_chat_ui(self, event: Event):
        logger.info(f"ChatController: получено событие UPDATE_CHAT_UI с данными: {event.data}")
        role = event.data.get('role', '')
        response = event.data.get('response', '')
        is_initial = event.data.get('is_initial', False)
        emotion = event.data.get('emotion', '')
        self.update_chat(role, response, is_initial, emotion)
        
    def _on_prepare_stream_ui(self, event: Event):
        logger.debug("ChatController: получено событие PREPARE_STREAM_UI")
        self.prepare_stream()
        
    def _on_append_stream_chunk_ui(self, event: Event):
        chunk = event.data.get('chunk', '')
        logger.debug(f"ChatController: получено событие APPEND_STREAM_CHUNK_UI с chunk: {chunk[:30]}...")
        self.stream_callback_handler(chunk)
        
    def _on_finish_stream_ui(self, event: Event):
        logger.debug("ChatController: получено событие FINISH_STREAM_UI")
        self.finish_stream()
        
    def _on_update_token_count(self, event: Event):
        logger.debug("ChatController: получено событие UPDATE_TOKEN_COUNT")
        self.update_token_count()
        
    def _on_update_token_count_ui(self, event: Event):
        self.update_token_count()
        
    def _on_insert_text_to_input(self, event: Event):
        text = event.data.get('text', '')
        if not self.view:
            return

        if hasattr(self.view, "insert_user_input_signal"):
            self.view.insert_user_input_signal.emit(text)
        elif self.view.user_entry:
            QTimer.singleShot(0, lambda: self.view.user_entry.insertPlainText(text + " "))
            
    def _on_check_user_entry_exists(self, event: Event):
        return bool(self.view and self.view.user_entry)