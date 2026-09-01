from __future__ import annotations

from core.events import get_event_bus
from core.services import use
from core.task_supervisor import task_supervisor
from services.contracts import SettingsService
from controllers.gui.async_runner import run_async
from controllers.gui.qt_dispatch import dispatch_to_qt
from main_logger import logger


class BaseController:
    def __init__(self, main_controller, view):
        self.main_controller = main_controller
        self.view = view
        self.event_bus = get_event_bus()
        self._settings_subscriptions = []
        self._closed = False
        self.subscribe_to_events()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def subscribe_to_events(self):
        pass

    def _backend_enabled(self) -> bool:
        return bool(getattr(self.main_controller, "backend_enabled", True))

    def _service_or_none(self, name: str):
        if not self._backend_enabled():
            return None
        return getattr(self.main_controller, name, None)


    def _save_setting(self, key: str, value) -> None:
        use(SettingsService).update(str(key), value)

    def _subscribe_settings(self, callback, *, keys=None, replay: bool = False):
        def dispatch(change):
            self._ui(lambda current=change: callback(current))

        subscription = use(SettingsService).subscribe(
            dispatch, keys=keys, replay=replay
        )
        self._settings_subscriptions.append(subscription)
        return subscription

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.event_bus.unsubscribe_owner(self)
        except Exception:
            pass
        subscriptions = self._settings_subscriptions
        self._settings_subscriptions = []
        for subscription in subscriptions:
            subscription.close()
        task_supervisor().cancel_owner(self, timeout=1.0)

    def _ui(self, fn):
        if self._closed or not callable(fn):
            return

        v = self.view
        sig = getattr(v, "run_ui_task_signal", None) if v is not None else None
        if sig is not None:
            try:
                sig.emit(fn)
                return
            except Exception:
                pass

        if not dispatch_to_qt(fn) and not self._closed:
            logger.debug(
                "Dropped GUI callback because the Qt dispatcher is unavailable"
            )

    def _run_async(self, worker, on_ok=None, on_error=None, *, name: str = "gui-controller-async"):
        return run_async(self, worker, on_ok, on_error, name=name)

