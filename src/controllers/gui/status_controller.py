import time

from core.events import Event, Events
from main_logger import logger

from .base_controller import BaseController


class StatusController(BaseController):
    def __init__(self, main_controller, view):
        super().__init__(main_controller, view)
        self._last_detailed_error_text = ""
        self._last_detailed_error_ts = 0.0

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.UPDATE_STATUS_COLORS, self._on_update_status_colors, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_STATUS, self._on_update_status, weak=False)
        self.event_bus.subscribe(Events.Model.ON_STARTED_RESPONSE_GENERATION, self._on_started_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_COMPRESSION_STARTED, self._on_compression_started, weak=False)
        self.event_bus.subscribe(Events.Model.ON_COMPRESSION_FINISHED, self._on_compression_finished, weak=False)
        self.event_bus.subscribe(Events.Model.ON_SUCCESSFUL_RESPONSE, self._on_successful_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_FAILED_RESPONSE_ATTEMPT, self._on_failed_response_attempt, weak=False)
        self.event_bus.subscribe(Events.Model.ON_FAILED_RESPONSE, self._on_failed_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_TOOL_EXECUTING, self._on_tool_executing, weak=False)
        self.event_bus.subscribe(Events.GUI.SHOW_MITA_VOICING, self._on_show_voicing, weak=False)
        self.event_bus.subscribe(Events.GUI.HIDE_MITA_VOICING, self._on_hide_voicing, weak=False)

    def update_status_colors(self):
        logger.debug("StatusController: update_status_colors")
        if self.view:
            self.view.update_status_signal.emit()
        else:
            logger.error("StatusController: view not found")

    def show_mita_thinking(self, payload):
        logger.debug(f"[DEBUG] StatusController: show thinking for {payload}")
        logger.info(f"StatusController: show_mita_thinking for {payload}")
        if self.view:
            self.view.show_thinking_signal.emit(payload)
        else:
            logger.error("StatusController: view not found")

    def show_mita_error(self, error_message):
        logger.debug(f"[DEBUG] StatusController: show error: {error_message}")
        logger.info(f"StatusController: show_mita_error: {error_message}")
        if self.view:
            self.view.show_error_signal.emit(error_message)
        else:
            logger.error("StatusController: view not found")

    def _on_show_voicing(self, event: Event):
        if self.view and getattr(self.view, "show_voicing_signal", None):
            payload = event.data if event and isinstance(getattr(event, "data", None), dict) else None
            self.view.show_voicing_signal.emit(payload)

    def _on_hide_voicing(self, _event: Event):
        if self.view and getattr(self.view, "hide_voicing_signal", None):
            self.view.hide_voicing_signal.emit()

    def hide_mita_status(self):
        logger.debug("[DEBUG] StatusController: hide status")
        logger.info("StatusController: hide_mita_status")
        if self.view:
            self.view.hide_status_signal.emit()
        else:
            logger.error("StatusController: view not found while hiding status")

    def show_mita_error_pulse(self):
        logger.info("StatusController: show_mita_error_pulse")
        if self.view:
            self.view.pulse_error_signal.emit()
        else:
            logger.error("StatusController: view not found")

    def update_status(self):
        logger.debug("StatusController: update_status")
        if self.view:
            self.view.update_status_signal.emit()
        else:
            logger.error("StatusController: view not found")

    def _on_update_status_colors(self, event: Event):
        logger.debug("StatusController: UPDATE_STATUS_COLORS")
        self.update_status_colors()

    def _on_update_status(self, event: Event):
        logger.debug("StatusController: UPDATE_STATUS")
        self.update_status()

    def _on_started_response(self, event: Event):
        logger.info("StatusController: ON_STARTED_RESPONSE_GENERATION")
        character_name = None
        if event and isinstance(getattr(event, "data", None), dict):
            character_name = event.data.get("character_name")

        if not character_name:
            character_name = "Мита"

        self.show_mita_thinking(character_name)

    def _on_compression_started(self, event: Event):
        logger.info("StatusController: ON_COMPRESSION_STARTED")
        self.show_mita_thinking({
            "state": "compression",
            "text": "Сжатие истории...",
            "icon_names": ["fa6s.box-archive", "fa5s.archive", "fa5s.compress-alt"],
        })

    def _on_successful_response(self, event: Event):
        logger.info("StatusController: ON_SUCCESSFUL_RESPONSE")
        self.hide_mita_status()

    def _on_compression_finished(self, event: Event):
        logger.info("StatusController: ON_COMPRESSION_FINISHED")
        # Гасим только статус сжатия (view сам проверит текущее состояние),
        # чтобы не сбить реальный «думает» активного чата.
        if self.view and getattr(self.view, "hide_compression_signal", None):
            self.view.hide_compression_signal.emit()

    def _on_failed_response_attempt(self, event: Event):
        logger.info("StatusController: ON_FAILED_RESPONSE_ATTEMPT")
        self.show_mita_error_pulse()

    def _on_tool_executing(self, event: Event):
        logger.info("StatusController: ON_TOOL_EXECUTING")
        tool_name = ""
        if event and isinstance(getattr(event, "data", None), dict):
            tool_name = event.data.get("tool_name", "")
        display = f"Tool: {tool_name}" if tool_name else "Tool"
        self.show_mita_thinking(display)

    def _on_failed_response(self, event: Event):
        logger.warning(f"StatusController: ON_FAILED_RESPONSE data={event.data}")
        data = event.data if event and isinstance(getattr(event, "data", None), dict) else {}
        provider_error = data.get("provider_error")
        provider_message = provider_error.get("message") if isinstance(provider_error, dict) else ""
        error_message = provider_message or data.get("error", "Неизвестная ошибка")

        if error_message and self._is_generic_generation_error(error_message):
            if self._last_detailed_error_text and (time.time() - self._last_detailed_error_ts) < 2.0:
                logger.info("StatusController: suppress generic generation error after detailed provider error")
                return
        elif error_message:
            self._last_detailed_error_text = error_message
            self._last_detailed_error_ts = time.time()

        self.show_mita_error(error_message)

    @staticmethod
    def _is_generic_generation_error(error_message: str) -> bool:
        low = str(error_message or "").strip().lower()
        generic_markers = (
            "text generation failed",
            "failed to get a response",
            "не удалось получить ответ",
            "неизвестная ошибка",
        )
        return any(marker in low for marker in generic_markers)
