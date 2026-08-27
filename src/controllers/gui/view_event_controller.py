from main_logger import logger
from core.events import Event
from .base_controller import BaseController

class ViewEventController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe("history_loaded", self._on_history_loaded_event, weak=False)
        self.event_bus.subscribe("more_history_loaded", self._on_more_history_loaded_event, weak=False)
        self.event_bus.subscribe("model_initialized", self._on_model_initialized_event, weak=False)
        self.event_bus.subscribe("model_init_cancelled", self._on_model_init_cancelled_event, weak=False)
        self.event_bus.subscribe("model_init_failed", self._on_model_init_failed_event, weak=False)
        self.event_bus.subscribe("reload_prompts_success", self._on_reload_prompts_success_event, weak=False)
        self.event_bus.subscribe("reload_prompts_failed", self._on_reload_prompts_failed_event, weak=False)
        self.event_bus.subscribe("display_loading_popup", self._on_display_loading_popup_event, weak=False)
        self.event_bus.subscribe("hide_loading_popup", self._on_hide_loading_popup_event, weak=False)
        
    def _on_history_loaded_event(self, event: Event):
        logger.debug("ViewEventController: получено ghost событие history_loaded, транслируем в view")
        if self.view:
            self.view.history_loaded_signal.emit(event.data)
    
    def _on_more_history_loaded_event(self, event: Event):
        logger.debug("ViewEventController: получено ghost событие more_history_loaded, транслируем в view")
        if self.view:
            self.view.more_history_loaded_signal.emit(event.data)
    
    def _on_model_initialized_event(self, event: Event):
        logger.debug("ViewEventController: получено событие model_initialized, транслируем в view")
        if self.view:
            self.view.model_initialized_signal.emit(event.data)
    
    def _on_model_init_cancelled_event(self, event: Event):
        logger.debug("ViewEventController: получено событие model_init_cancelled, транслируем в view")
        if self.view:
            self.view.model_init_cancelled_signal.emit(event.data)
    
    def _on_model_init_failed_event(self, event: Event):
        logger.debug("ViewEventController: получено событие model_init_failed, транслируем в view")
        if self.view:
            self.view.model_init_failed_signal.emit(event.data)
    
    def _on_reload_prompts_success_event(self, event: Event):
        logger.debug("ViewEventController: получено событие reload_prompts_success, транслируем в view")
        if self.view:
            self.view.reload_prompts_success_signal.emit()
    
    def _on_reload_prompts_failed_event(self, event: Event):
        logger.debug("ViewEventController: получено событие reload_prompts_failed, транслируем в view")
        if self.view:
            self.view.reload_prompts_failed_signal.emit(event.data)
    
    def _on_display_loading_popup_event(self, event: Event):
        logger.debug("ViewEventController: получено событие display_loading_popup, транслируем в view")
        if self.view:
            self.view.display_loading_popup_signal.emit(event.data)
    
    def _on_hide_loading_popup_event(self, event: Event):
        logger.debug("ViewEventController: получено событие hide_loading_popup, транслируем в view")
        if self.view:
            self.view.hide_loading_popup_signal.emit()