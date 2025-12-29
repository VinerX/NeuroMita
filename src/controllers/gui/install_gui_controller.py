import threading
from typing import Optional

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController


class InstallGuiController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Install.RUN_WITH_UI, self._on_run_with_ui, weak=False)
        self.event_bus.subscribe(Events.Install.RUN_HEADLESS, self._on_run_headless, weak=False)

    def _get_backend(self):
        backend = getattr(self.main_controller, "install_controller", None)
        if backend is not None:
            return backend
        try:
            from controllers.install_controller import InstallController
            backend = InstallController()
            self.main_controller.install_controller = backend
            return backend
        except Exception:
            return None

    def _close_window_threadsafe(self, win: object) -> None:
        if not win:
            return
        try:
            from PyQt6.QtCore import QMetaObject, Qt
            QMetaObject.invokeMethod(win, "close", Qt.ConnectionType.QueuedConnection)
        except Exception:
            try:
                win.close()
            except Exception:
                pass

    def _create_install_window(self, title: str, initial_status: str):
        if not self.view or not hasattr(self.view, "create_installation_window_signal"):
            return None, (lambda *_: None), (lambda *_: None), (lambda *_: None)

        holder = {"ready_event": threading.Event()}

        try:
            self.view.create_installation_window_signal.emit(title, initial_status, holder)
        except Exception as e:
            logger.error(f"Failed to create install window: {e}", exc_info=True)
            return None, (lambda *_: None), (lambda *_: None), (lambda *_: None)

        try:
            holder["ready_event"].wait(5.0)
        except Exception:
            pass

        win = holder.get("window")
        cbs = holder.get("callbacks")

        if cbs and isinstance(cbs, (list, tuple)) and len(cbs) == 3:
            progress_cb, status_cb, log_cb = cbs
        else:
            progress_cb = getattr(win, "update_progress", lambda *_: None) if win else (lambda *_: None)
            status_cb = getattr(win, "update_status", lambda *_: None) if win else (lambda *_: None)
            log_cb = getattr(win, "update_log", lambda *_: None) if win else (lambda *_: None)

        return win, progress_cb, status_cb, log_cb

    def _on_run_with_ui(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        kind = data.get("kind")
        if kind != "asr":
            logger.error(f"InstallGuiController: unsupported kind='{kind}'")
            return

        engine = data.get("engine")
        if not engine:
            return

        engine_settings = data.get("engine_settings") or {}
        title = data.get("title") or f"Installing {engine}"
        initial_status = data.get("initial_status") or "Preparing..."

        backend = self._get_backend()
        if backend is None:
            logger.error("InstallController backend not available")
            return

        win, progress_cb, status_cb, log_cb = self._create_install_window(title, initial_status)

        def worker():
            try:
                from controllers.install_controller import InstallCallbacks
                # Запускаем установку
                ok = backend.install_asr_engine(
                    engine,
                    engine_settings=engine_settings,
                    callbacks=InstallCallbacks(progress=progress_cb, status=status_cb, log=log_cb),
                    timeout_sec=float(data.get("timeout_sec", 3600.0))
                )
                
                if ok:
                    status_cb("Done")
                    # Закрываем окно только при успешном завершении
                    self._close_window_threadsafe(win)
                else:
                    status_cb("Failed")
                    log_cb("Installation failed (see logs above).")
                    # Окно НЕ закрываем, чтобы пользователь видел ошибку

            except Exception as e:
                logger.error(f"Install worker failed: {e}", exc_info=True)
                try:
                    status_cb("Failed")
                    log_cb(f"Critical error: {str(e)}")
                except Exception:
                    pass
                # При исключении окно тоже НЕ закрываем

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_headless(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        kind = data.get("kind")
        if kind != "asr":
            return

        engine = data.get("engine")
        if not engine:
            return

        backend = self._get_backend()
        if backend is None:
            return

        def worker():
            try:
                ok = backend.install_asr_engine(
                    engine,
                    engine_settings=data.get("engine_settings") or {},
                    callbacks=None,
                    timeout_sec=float(data.get("timeout_sec", 3600.0))
                )
                if not ok:
                    logger.error(f"Headless install failed for {engine}")
            except Exception as e:
                logger.error(f"Headless install exception for {engine}: {e}", exc_info=True)

        threading.Thread(target=worker, daemon=True).start()