from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController


class WindowManagerController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.SHOW_WINDOW, self._on_show_window, weak=False)
        self.event_bus.subscribe(Events.GUI.CLOSE_WINDOW, self._on_close_window, weak=False)
        self.event_bus.subscribe(Events.GUI.CLOSE_ALL_WINDOWS, self._on_close_all_windows, weak=False)

    def _on_show_window(self, event: Event):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            logger.error("WindowManagerController: window_manager не найден в view.")
            return

        data = event.data if isinstance(event.data, dict) else {}
        window_id = data.get("window_id")
        payload = data.get("payload", {})

        if not window_id:
            logger.error("WindowManagerController: SHOW_WINDOW без window_id.")
            return

        if payload is None or not isinstance(payload, dict):
            payload = {}

        self.view.window_manager.show_dialog(window_id, payload)

    def _on_close_window(self, event: Event):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return

        data = event.data if isinstance(event.data, dict) else {}
        window_id = data.get("window_id")
        destroy = bool(data.get("destroy", False))

        if not window_id:
            return

        self.view.window_manager.close_dialog(window_id, destroy=destroy)

    def _on_close_all_windows(self, event: Event):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return

        data = event.data if isinstance(event.data, dict) else {}
        destroy = bool(data.get("destroy", False))

        self.view.window_manager.close_all(destroy=destroy)