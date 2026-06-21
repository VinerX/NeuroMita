import threading
from typing import Optional

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

from core.install_types import InstallCallbacks


class InstallGuiController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Install.RUN_WITH_UI, self._on_run_with_ui, weak=False)
        self.event_bus.subscribe(Events.Install.RUN_HEADLESS, self._on_run_headless, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_LOG, self._on_install_task_log, weak=False)

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

    def _finish_install_window(self, win: object, close_now: bool) -> None:
        """Mark the install window as finished (so it can be really closed) and
        optionally close it now. Routed through a GUI-thread signal because this
        runs on the install worker thread."""
        if not win:
            return
        view = getattr(self, "view", None)
        sig = getattr(view, "finalize_installation_window_signal", None) if view else None
        if sig is not None:
            try:
                sig.emit(win, bool(close_now))
                return
            except Exception:
                pass
        try:
            if hasattr(win, "finalize"):
                win.finalize()
            if close_now:
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

    def _on_install_task_log(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}

        msg = data.get("message")
        if msg is None:
            msg = data.get("log")
        if msg is None:
            msg = data.get("text")
        msg = "" if msg is None else str(msg)

        level = str(data.get("level") or "").strip().lower()
        low = msg.lower()

        if level in ("error", "exception", "critical") or any(k in low for k in ("error", "ошибка", "failed", "exception", "traceback")):
            logger.error(f"[INSTALL] {msg}")
        elif level in ("warn", "warning") or any(k in low for k in ("warning", "предупреж")):
            logger.warning(f"[INSTALL] {msg}")

    def _on_run_with_ui(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}

        runner = data.get("runner")
        if not callable(runner):
            logger.error("InstallGuiController: missing callable 'runner' in Events.Install.RUN_WITH_UI payload")
            return

        kind = data.get("kind") or (data.get("meta") or {}).get("kind") or "install"
        item_id = data.get("item_id") or data.get("engine") or (data.get("meta") or {}).get("item_id") or "task"
        task_id = data.get("task_id") or f"{kind}:{item_id}"

        title = data.get("title") or f"Installing {item_id}"
        initial_status = data.get("initial_status") or "Preparing..."

        meta = data.get("meta") or {"kind": kind, "item_id": item_id}

        backend = self._get_backend()
        if backend is None:
            logger.error("InstallController backend not available")
            return

        custom_window = data.get("install_window")
        custom_callbacks = data.get("install_callbacks")
        if custom_window is not None:
            if custom_callbacks is None and hasattr(custom_window, "get_threadsafe_callbacks"):
                custom_callbacks = custom_window.get_threadsafe_callbacks()
            if isinstance(custom_callbacks, (tuple, list)) and len(custom_callbacks) == 3:
                win = custom_window
                progress_cb, status_cb, log_cb = custom_callbacks
            else:
                logger.warning(
                    "InstallGuiController: invalid install_callbacks for custom install window, falling back to default UI"
                )
                win, progress_cb, status_cb, log_cb = self._create_install_window(title, initial_status)
        else:
            win, progress_cb, status_cb, log_cb = self._create_install_window(title, initial_status)

        def worker():
            try:
                ok = backend.run_task(
                    task_id=str(task_id),
                    runner=runner,
                    meta=meta,
                    callbacks=InstallCallbacks(progress=progress_cb, status=status_cb, log=log_cb),
                    timeout_sec=float(data.get("timeout_sec", 3600.0)),
                )

                if ok:
                    status_cb("Done")
                    self._finish_install_window(win, True)
                else:
                    status_cb("Failed")
                    log_cb("Installation failed (see logs above).")
                    # Keep the window open so the user can read the logs, but
                    # finalize it so closing it actually closes (and clears the
                    # sidebar "Install logs" button).
                    self._finish_install_window(win, False)
                    self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                        "title": "Installation failed",
                        "message": f"Task '{task_id}' failed. See install window logs."
                    })

            except Exception as e:
                logger.error(f"Install worker failed: {e}", exc_info=True)
                try:
                    status_cb("Failed")
                    log_cb(f"Critical error: {str(e)}")
                except Exception:
                    pass
                self._finish_install_window(win, False)
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": "Installation error",
                    "message": f"Task '{task_id}' failed with exception:\n{e}"
                })

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_headless(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}

        runner = data.get("runner")
        if not callable(runner):
            logger.error("InstallGuiController: missing callable 'runner' in Events.Install.RUN_HEADLESS payload")
            return

        kind = data.get("kind") or (data.get("meta") or {}).get("kind") or "install"
        item_id = data.get("item_id") or data.get("engine") or (data.get("meta") or {}).get("item_id") or "task"
        task_id = data.get("task_id") or f"{kind}:{item_id}"
        meta = data.get("meta") or {"kind": kind, "item_id": item_id}

        backend = self._get_backend()
        if backend is None:
            return

        def worker():
            try:
                ok = backend.run_task(
                    task_id=str(task_id),
                    runner=runner,
                    meta=meta,
                    callbacks=None,
                    timeout_sec=float(data.get("timeout_sec", 3600.0)),
                )
                if not ok:
                    logger.error(f"Headless install failed for task_id={task_id}")
                    self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                        "title": "Installation failed",
                        "message": f"Headless task '{task_id}' failed."
                    })
            except Exception as e:
                logger.error(f"Headless install exception for task_id={task_id}: {e}", exc_info=True)
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": "Installation error",
                    "message": f"Headless task '{task_id}' failed with exception:\n{e}"
                })

        threading.Thread(target=worker, daemon=True).start()
