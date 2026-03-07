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

    def stream_callback_handler(self, chunk: str, role: str = "assistant"):
        logger.debug(f"ChatController: stream_callback_handler [{role}]: {chunk[:50]}...")
        if self.view:
            self.view.append_stream_chunk_signal.emit({"chunk": chunk, "role": role})
        else:
            logger.error("ChatController: view не найден!")

    def prepare_stream(self, data: dict = None):
        logger.info(f"ChatController: prepare_stream, data={data}")
        if self.view:
            self.view.prepare_stream_signal.emit(data if data is not None else {})
        else:
            logger.error("ChatController: view не найден!")

    def finish_stream(self):
        logger.info("ChatController: finish_stream")
        if self.view:
            self.view.finish_stream_signal.emit()
        else:
            logger.error("ChatController: view не найден!")

    def update_chat(self, role, response, is_initial, emotion, speaker_label: str = ""):
        if not self.view:
            logger.error("ChatController: view не найден!")
            return

        payload = response
        if speaker_label:
            if isinstance(payload, list):
                payload = [{"type": "meta", "speaker": speaker_label}] + payload
            else:
                payload = [{"type": "meta", "speaker": speaker_label}, {"type": "text", "text": str(payload)}]

        self.view.update_chat_signal.emit(role, payload, is_initial, emotion)

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
        data = event.data or {}
        role = data.get('role', '')
        response = data.get('response', '')
        is_initial = data.get('is_initial', False)
        emotion = data.get('emotion', '')

        speaker_name = str(data.get("speaker_name") or data.get("character_name") or "")
        target = str(data.get("target") or "")

        speaker_label = speaker_name
        if role == "assistant" and speaker_name and target and target != "Player":
            speaker_label = f"{speaker_name} → {target}"

        self.update_chat(role, response, is_initial, emotion, speaker_label=speaker_label)

    def _on_prepare_stream_ui(self, event: Event):
        data = event.data or {}
        role = data.get("role", "assistant")
        if self.view is not None:
            self.view._stream_speaker_name = str(data.get("speaker_name") or data.get("character_name") or "")
        self.prepare_stream(data)

    def _on_append_stream_chunk_ui(self, event: Event):
        data = event.data or {}
        chunk = data.get('chunk', '')
        role = data.get('role', 'assistant')
        self.stream_callback_handler(chunk, role)

    def _on_finish_stream_ui(self, event: Event):
        self.finish_stream()
        if self.view is not None and hasattr(self.view, "_stream_speaker_name"):
            self.view._stream_speaker_name = ""

    def _on_update_token_count(self, event: Event):
        self.update_token_count()

    def _on_update_token_count_ui(self, event: Event):
        self.update_token_count()

    def _on_insert_text_to_input(self, event: Event):
        text = (event.data or {}).get('text', '')
        if not self.view:
            return

        if hasattr(self.view, "insert_user_input_signal"):
            self.view.insert_user_input_signal.emit(text)
        elif self.view.user_entry:
            QTimer.singleShot(0, lambda: self.view.user_entry.insertPlainText(text + " "))

    def _on_check_user_entry_exists(self, event: Event):
        return bool(self.view and self.view.user_entry)