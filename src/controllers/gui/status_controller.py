from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController


class StatusController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.UPDATE_STATUS_COLORS, self._on_update_status_colors, weak=False)
        self.event_bus.subscribe(Events.GUI.UPDATE_STATUS, self._on_update_status, weak=False)
        self.event_bus.subscribe(Events.Model.ON_STARTED_RESPONSE_GENERATION, self._on_started_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_SUCCESSFUL_RESPONSE, self._on_successful_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_FAILED_RESPONSE_ATTEMPT, self._on_failed_response_attempt, weak=False)
        self.event_bus.subscribe(Events.Model.ON_FAILED_RESPONSE, self._on_failed_response, weak=False)
        self.event_bus.subscribe(Events.Model.ON_TOOL_EXECUTING, self._on_tool_executing, weak=False)

    def update_status_colors(self):
        logger.debug("StatusController: update_status_colors")
        if self.view:
            self.view.update_status_signal.emit()
        else:
            logger.error("StatusController: view не найден!")

    def show_mita_thinking(self, character_name):
        logger.debug(f"[DEBUG] StatusController: показ статуса 'думает' для {character_name}")
        logger.info(f"StatusController: show_mita_thinking для {character_name}")
        if self.view:
            logger.debug(f"[DEBUG] Эмитим show_thinking_signal с {character_name}")
            self.view.show_thinking_signal.emit(character_name)
        else:
            logger.debug("[DEBUG] view не найден!")
            logger.error("StatusController: view не найден!")

    def show_mita_error(self, error_message):
        logger.debug(f"[DEBUG] StatusController: показ ошибки: {error_message}")
        logger.info(f"StatusController: show_mita_error: {error_message}")
        if self.view:
            self.view.show_error_signal.emit(error_message)
        else:
            logger.error("StatusController: view не найден!")

    def hide_mita_status(self):
        logger.debug("[DEBUG] StatusController: скрытие статуса")
        logger.info("StatusController: hide_mita_status")
        if self.view:
            logger.debug("[DEBUG] Эмитим hide_status_signal")
            self.view.hide_status_signal.emit()
        else:
            logger.debug("[DEBUG] view не найден при попытке скрыть!")
            logger.error("StatusController: view не найден при попытке скрыть!")

    def show_mita_error_pulse(self):
        logger.info("StatusController: show_mita_error_pulse")
        if self.view:
            self.view.pulse_error_signal.emit()
        else:
            logger.error("StatusController: view не найден!")

    def update_status(self):
        logger.debug("StatusController: update_status")
        if self.view:
            self.view.update_status_signal.emit()
        else:
            logger.error("StatusController: view не найден!")

    def _on_update_status_colors(self, event: Event):
        logger.debug("StatusController: получено событие UPDATE_STATUS_COLORS")
        self.update_status_colors()

    def _on_update_status(self, event: Event):
        logger.debug("StatusController: получено событие UPDATE_STATUS")
        self.update_status()

    def _on_started_response(self, event: Event):
        logger.info("StatusController: получено событие ON_STARTED_RESPONSE_GENERATION")

        character_name = None
        if event and isinstance(getattr(event, "data", None), dict):
            character_name = event.data.get("character_name")

        if not character_name:
            character_name = "Мита"

        self.show_mita_thinking(character_name)

    def _on_successful_response(self, event: Event):
        logger.info("StatusController: получено событие ON_SUCCESSFUL_RESPONSE")
        self.hide_mita_status()

    def _on_failed_response_attempt(self, event: Event):
        logger.info("StatusController: получено событие ON_FAILED_RESPONSE_ATTEMPT")
        self.show_mita_error_pulse()

    def _on_tool_executing(self, event: Event):
        logger.info("StatusController: получено событие ON_TOOL_EXECUTING")
        tool_name = ""
        if event and isinstance(getattr(event, "data", None), dict):
            tool_name = event.data.get("tool_name", "")
        display = f"🔍 {tool_name}" if tool_name else "🔍"
        self.show_mita_thinking(display)

    def _on_failed_response(self, event: Event):
        logger.warning(f"StatusController: получено событие ON_FAILED_RESPONSE с данными: {event.data}")
        error_message = event.data.get('error', 'Неизвестная ошибка') if event.data else 'Неизвестная ошибка'
        self.show_mita_error(error_message)