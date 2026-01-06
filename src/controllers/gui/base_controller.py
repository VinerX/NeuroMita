from __future__ import annotations

from PyQt6.QtCore import QTimer
from core.events import get_event_bus


class BaseController:
    def __init__(self, main_controller, view):
        self.main_controller = main_controller
        self.view = view
        self.event_bus = get_event_bus()
        self.subscribe_to_events()

    def subscribe_to_events(self):
        pass

    def _ui(self, fn):
        if not callable(fn):
            return

        v = self.view
        sig = getattr(v, "run_ui_task_signal", None) if v is not None else None
        if sig is not None:
            try:
                sig.emit(fn)
                return
            except Exception:
                pass

        # fallback (если вдруг сигнала нет)
        try:
            QTimer.singleShot(0, fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass