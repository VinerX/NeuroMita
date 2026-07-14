import threading
import time
from collections import deque
from typing import Any

from main_logger import logger
from core.events import Events, Event
from core.install_log import classify_install_log
from core.services import ServiceRegistration, services
from .base_controller import BaseController

from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC, InstallCallbacks
from core.task_supervisor import task_supervisor
from services.contracts import (
    InstallAdmission,
    InstallQueueAdministrationService,
    InstallQueueService,
)


class InstallGuiController(
    BaseController,
    InstallQueueService,
    InstallQueueAdministrationService,
):
    """Исполняет задачи установки строго по одной за раз (очередь).

    Раньше каждая задача стартовала в своём демон-потоке, поэтому два клика
    «установить» запускали параллельные pip/uv в одну папку Lib — гонка за файлы
    и битые пакеты без RECORD. Теперь все задачи проходят через единый воркер:
    FIFO-очередь, дедуп по task_id, видимость состояния через QUEUE_CHANGED и
    отмена ещё не начатых задач через CANCEL_QUEUED.
    """

    def __init__(self, main_controller: Any, view: Any) -> None:
        self._queue_cond = threading.Condition()
        self._pending: deque[dict[str, Any]] = deque()
        self._running: dict[str, Any] | None = None
        self._worker_thread: threading.Thread | None = None
        self._worker_stop_event = threading.Event()
        self._last_enqueue_error = ""
        self._accepting_jobs = True
        self._queue_service_registration: ServiceRegistration | None = None
        self._queue_admin_registration: ServiceRegistration | None = None
        super().__init__(main_controller, view)
        self._queue_service_registration = services().register_owned(
            InstallQueueService,
            self,
            replace=True,
        )
        self._queue_admin_registration = services().register_owned(
            InstallQueueAdministrationService,
            self,
            replace=True,
        )
        _ = self._ensure_worker()

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Install.RUN_WITH_UI, self._on_run_with_ui, weak=False)
        self.event_bus.subscribe(Events.Install.RUN_HEADLESS, self._on_run_headless, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_LOG, self._on_install_task_log, weak=False)
        self.event_bus.subscribe(Events.Install.CANCEL_QUEUED, self._on_cancel_queued, weak=False)
        self.event_bus.subscribe(Events.Install.CANCEL_RUNNING, self._on_cancel_running, weak=False)

    # ------------------------------------------------------------------
    # Очередь
    # ------------------------------------------------------------------
    def _ensure_worker(self) -> bool:
        with self._queue_cond:
            worker = self._worker_thread
            if worker is not None and worker.is_alive():
                return True
            if self._worker_stop_event.is_set():
                self._last_enqueue_error = "Install queue is shutting down"
                return False
            try:
                worker = task_supervisor().start_thread(
                    self,
                    "install-queue",
                    self._worker_loop,
                    cancel_event=self._worker_stop_event,
                )
            except Exception as exc:
                self._worker_thread = None
                self._last_enqueue_error = f"Failed to start install queue: {exc}"
                logger.error(self._last_enqueue_error, exc_info=True)
                return False
            self._worker_thread = worker
            self._last_enqueue_error = ""
            return True

    def _admit_job(self, job: dict[str, Any]) -> InstallAdmission:
        """Atomically hand a job to the serialized install queue."""
        task_id = str(job.get("task_id") or "")
        if not self._ensure_worker():
            return InstallAdmission(
                accepted=False,
                task_id=task_id,
                error=self._last_enqueue_error or "Install queue is unavailable",
            )

        with self._queue_cond:
            if not self._accepting_jobs:
                return InstallAdmission(
                    accepted=False,
                    task_id=task_id,
                    error="Install queue is paused for AI environment maintenance",
                )
            active_ids = {str((self._running or {}).get("task_id") or "")}
            active_ids.update(str(j.get("task_id") or "") for j in self._pending)
            if task_id and task_id in active_ids:
                self._last_enqueue_error = ""
                return InstallAdmission(
                    accepted=True,
                    task_id=task_id,
                    duplicate=True,
                )
            job.setdefault("cancel_event", threading.Event())
            self._pending.append(job)
            self._queue_cond.notify()
            self._last_enqueue_error = ""
        self._emit_queue_changed()
        return InstallAdmission(accepted=True, task_id=task_id)

    def _enqueue(self, job: dict[str, Any]) -> bool:
        """Legacy bool adapter used by older tests/callers."""
        admission = self._admit_job(job)
        return bool(admission.accepted and not admission.duplicate)

    def _on_cancel_queued(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        task_id = str(data.get("task_id") or "")
        if not task_id:
            return
        removed = False
        with self._queue_cond:
            # Отменить можно только ещё не начатую задачу (running не трогаем).
            for j in list(self._pending):
                if str(j.get("task_id") or "") == task_id:
                    self._pending.remove(j)
                    removed = True
                    break
        if removed:
            self._emit_queue_changed()

    def _on_cancel_running(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        task_id = str(data.get("task_id") or "")
        if not task_id:
            return
        with self._queue_cond:
            running = self._running
            if running is None or str(running.get("task_id") or "") != task_id:
                return
            cancel_event = running.get("cancel_event")
            if not isinstance(cancel_event, threading.Event):
                return
            cancel_event.set()
            running["cancelling"] = True
        callbacks = running.get("callbacks")
        if callbacks:
            try:
                callbacks[1]("Cancelling...")
                callbacks[2]("Cancellation requested. Waiting for the current step to stop...")
            except Exception:
                pass
        self._emit_queue_changed()

    def _queue_snapshot(self) -> dict[str, Any]:
        with self._queue_cond:
            running = None
            if self._running is not None:
                running = {
                    "task_id": self._running.get("task_id"),
                    "title": self._running.get("title"),
                    "cancelling": bool(self._running.get("cancelling")),
                }
            pending = [
                {"task_id": j.get("task_id"), "title": j.get("title")}
                for j in self._pending
            ]
        return {"running": running, "pending": pending}

    def _emit_queue_changed(self) -> None:
        try:
            self.event_bus.emit(Events.Install.QUEUE_CHANGED, self._queue_snapshot())
        except Exception:
            pass

    @staticmethod
    def _normalize_callbacks(callbacks):
        if not isinstance(callbacks, (tuple, list)) or len(callbacks) not in (3, 4):
            return None
        normalized = [cb if callable(cb) else (lambda *_: None) for cb in callbacks]
        if len(normalized) == 3:
            normalized.append(lambda *_: None)
        return tuple(normalized)

    # Compatibility for older tests/callers. New code uses four callbacks:
    # progress, status, parsed log, exact raw subprocess stream.
    _normalize_callback_triplet = _normalize_callbacks

    def _worker_loop(self) -> None:
        logger.info("Install queue worker started")
        while not self._worker_stop_event.is_set():
            with self._queue_cond:
                while not self._pending and not self._worker_stop_event.is_set():
                    self._queue_cond.wait(timeout=0.5)
                if self._worker_stop_event.is_set():
                    break
                job = self._pending.popleft()
                self._running = job
            logger.info(
                f"Install queue starting task "
                f"'{str(job.get('task_id') or 'task')}' "
                f"({str(job.get('title') or '')})"
            )
            self._emit_queue_changed()
            try:
                self._run_job(job)
            except Exception as e:
                logger.error(f"Install worker failed: {e}", exc_info=True)
                self._report_start_failure(
                    job,
                    f"Installation worker failed before the task could start: {e}",
                )
            finally:
                with self._queue_cond:
                    self._running = None
                    self._queue_cond.notify_all()
                self._emit_queue_changed()
        logger.info("Install queue worker stopped")

    def quiesce(self, *, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout))
        with self._queue_cond:
            self._accepting_jobs = False
            for job in self._pending:
                cancel_event = job.get("cancel_event")
                if isinstance(cancel_event, threading.Event):
                    cancel_event.set()
            self._pending.clear()
            if self._running is not None:
                cancel_event = self._running.get("cancel_event")
                if isinstance(cancel_event, threading.Event):
                    cancel_event.set()
                    self._running["cancelling"] = True
            self._queue_cond.notify_all()
            while self._running is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue_cond.wait(timeout=min(0.25, remaining))
        self._emit_queue_changed()
        return True

    def resume(self) -> None:
        with self._queue_cond:
            self._accepting_jobs = True
            self._queue_cond.notify_all()

    def close(self) -> None:
        self._worker_stop_event.set()
        with self._queue_cond:
            self._queue_cond.notify_all()
        registration = self._queue_service_registration
        self._queue_service_registration = None
        if registration is not None:
            try:
                registration.close()
            except Exception:
                logger.exception("Failed to unregister install queue service")
        admin_registration = self._queue_admin_registration
        self._queue_admin_registration = None
        if admin_registration is not None:
            try:
                admin_registration.close()
            except Exception:
                logger.exception("Failed to unregister install queue administration service")
        try:
            self.event_bus.unsubscribe_owner(self)
        except Exception:
            pass
        super().close()

    def _run_job(self, job: dict[str, Any]) -> None:
        backend = self._get_backend()
        if backend is None:
            self._report_start_failure(
                job,
                "Install backend is unavailable or failed to initialize",
            )
            return

        headless = bool(job.get("headless"))
        task_id = str(job.get("task_id") or "task")

        win = job.get("win")
        cbs = job.get("callbacks")

        # Для штатного UI-пути окно создаём в момент СТАРТА задачи (а не при
        # постановке в очередь), чтобы окна ожидающих задач не накладывались.
        if not headless and win is None and cbs is None:
            win, progress_cb, status_cb, log_cb, raw_log_cb = self._create_install_window(
                job.get("title") or f"Installing {task_id}",
                job.get("initial_status") or "Preparing...",
                job.get("install_style_variant") or "default",
            )
            cbs = (progress_cb, status_cb, log_cb, raw_log_cb)
            job["win"] = win

        task_title = str(job.get("title") or task_id)
        last_status = ""

        if headless:
            callbacks = None
        else:
            progress_cb = cbs[0] if cbs else (lambda *_: None)

            def status_cb(message):
                nonlocal last_status
                last_status = "" if message is None else str(message)
                (cbs[1] if cbs else (lambda *_: None))(message)

            log_cb = cbs[2] if cbs else (lambda *_: None)
            raw_log_cb = cbs[3] if cbs and len(cbs) > 3 else (lambda *_: None)
            callbacks = InstallCallbacks(
                progress=progress_cb,
                status=status_cb,
                log=log_cb,
                raw_log=raw_log_cb,
            )

        ok = False
        try:
            ok = backend.run_task(
                task_id=task_id,
                runner=job.get("runner"),
                meta=job.get("meta"),
                callbacks=callbacks,
                timeout_sec=float(job.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC)),
                cancel_event=job.get("cancel_event"),
            )
        except Exception as e:
            logger.error(f"Install worker failed: {e}", exc_info=True)
            if not headless and cbs:
                try:
                    cbs[1]("Failed")
                    cbs[2](f"Critical error: {str(e)}")
                except Exception:
                    pass
            ok = False

        if headless:
            if not ok:
                logger.error(f"Headless install failed for task_id={task_id}")
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": "Installation failed",
                    "message": f"Task '{task_title}' failed.",
                })
            return

        # Окно закрываем только если его не делит ещё одна задача из очереди:
        # AI Hub переиспользует одно окно для всех задач, и оно должно жить до
        # конца всей пачки.
        with self._queue_cond:
            shared = win is not None and any(j.get("win") is win for j in self._pending)

        status_cb = cbs[1] if cbs else (lambda *_: None)
        log_cb = cbs[2] if cbs else (lambda *_: None)
        if ok:
            try:
                status_cb("Done")
            except Exception:
                pass
            if not shared:
                self._finish_install_window(win, True)
        else:
            try:
                status_cb("Failed")
                log_cb(f"Installation failed for '{task_title}'. See the error lines above.")
            except Exception:
                pass
            if not shared:
                # Оставляем окно открытым, чтобы пользователь прочитал логи.
                self._finish_install_window(win, False)
            details = f" Last status: {last_status}." if last_status else ""
            self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                "title": "Installation failed",
                "message": f"Task '{task_title}' failed.{details} See install window logs.",
            })

    def _report_start_failure(self, job: dict[str, Any], message: str) -> None:
        task_id = str(job.get("task_id") or "task")
        raw_meta = job.get("meta")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        component_id = str(meta.get("component_id") or "")
        error = str(message or "Installation task failed to start")
        logger.error(f"Install task '{task_id}' failed to start: {error}")

        callbacks = job.get("callbacks")
        if not bool(job.get("headless")) and callbacks:
            try:
                callbacks[1]("Failed")
                callbacks[2](error)
            except Exception:
                logger.exception(
                    f"Failed to report startup error for install task '{task_id}'"
                )

        self.event_bus.emit(
            Events.Install.TASK_FAILED,
            {
                "task_id": task_id,
                "component_id": component_id,
                "meta": meta,
                "error": error,
            },
        )

    # ------------------------------------------------------------------
    # backend / окно
    # ------------------------------------------------------------------
    def _get_backend(self):
        backend = self._service_or_none("install_controller")
        if backend is not None:
            return backend
        if not self._backend_enabled():
            return None
        try:
            return self.main_controller.ensure_feature("install", timeout=20.0)
        except Exception as exc:
            logger.error(f"Install backend is unavailable: {exc}")
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

    def _create_install_window(self, title: str, initial_status: str, style_variant: str = "default"):
        if not self.view or not hasattr(self.view, "create_installation_window_signal"):
            return None, (lambda *_: None), (lambda *_: None), (lambda *_: None), (lambda *_: None)

        holder = {
            "ready_event": threading.Event(),
            "style_variant": str(style_variant or "default"),
        }

        try:
            self.view.create_installation_window_signal.emit(title, initial_status, holder)
        except Exception as e:
            logger.error(f"Failed to create install window: {e}", exc_info=True)
            return None, (lambda *_: None), (lambda *_: None), (lambda *_: None), (lambda *_: None)

        try:
            holder["ready_event"].wait(5.0)
        except Exception:
            pass

        win = holder.get("window")
        cbs = holder.get("callbacks")

        normalized = self._normalize_callbacks(cbs)
        if normalized is not None:
            progress_cb, status_cb, log_cb, raw_log_cb = normalized
        else:
            progress_cb = getattr(win, "update_progress", lambda *_: None) if win else (lambda *_: None)
            status_cb = getattr(win, "update_status", lambda *_: None) if win else (lambda *_: None)
            log_cb = getattr(win, "update_log", lambda *_: None) if win else (lambda *_: None)
            raw_log_cb = getattr(win, "update_raw_log", lambda *_: None) if win else (lambda *_: None)

        return win, progress_cb, status_cb, log_cb, raw_log_cb

    def _on_install_task_log(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}

        msg = data.get("message")
        if msg is None:
            msg = data.get("log")
        if msg is None:
            msg = data.get("text")
        msg = "" if msg is None else str(msg)

        level = classify_install_log(msg, data.get("level"))
        if level == "error":
            logger.error(f"[INSTALL] {msg}")
        elif level == "warning":
            logger.warning(f"[INSTALL] {msg}")

    # ------------------------------------------------------------------
    # точки входа (постановка в очередь)
    # ------------------------------------------------------------------
    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        with_ui: bool,
    ) -> InstallAdmission:
        data = payload if isinstance(payload, dict) else {}
        runner = data.get("runner")
        if not callable(runner):
            task_id = str(data.get("task_id") or "")
            return InstallAdmission(
                accepted=False,
                task_id=task_id,
                error="Install queue payload has no callable runner",
            )

        kind = data.get("kind") or (data.get("meta") or {}).get("kind") or "install"
        item_id = data.get("item_id") or data.get("engine") or (data.get("meta") or {}).get("item_id") or "task"
        task_id = data.get("task_id") or f"{kind}:{item_id}"
        title = data.get("title") or f"Installing {item_id}"
        initial_status = data.get("initial_status") or "Preparing..."
        meta = data.get("meta") or {"kind": kind, "item_id": item_id}

        win = None
        cbs = None
        if with_ui:
            # Кастомное окно от встроенного установщика (AI Hub). Если его нет —
            # окно создастся лениво в момент старта задачи (см. _run_job).
            custom_window = data.get("install_window")
            custom_callbacks = data.get("install_callbacks")
            if custom_window is not None:
                if custom_callbacks is None and hasattr(custom_window, "get_threadsafe_callbacks"):
                    custom_callbacks = custom_window.get_threadsafe_callbacks()
                normalized_callbacks = self._normalize_callbacks(custom_callbacks)
                if normalized_callbacks is not None:
                    win = custom_window
                    cbs = normalized_callbacks
                else:
                    logger.warning(
                        "InstallGuiController: invalid install_callbacks for custom install window, "
                        "will create a default window"
                    )

        job = {
            "task_id": str(task_id),
            "runner": runner,
            "meta": meta,
            "title": title,
            "initial_status": initial_status,
            "timeout_sec": float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC)),
            "win": win,
            "callbacks": cbs,
            "install_style_variant": str(data.get("install_style_variant") or "default"),
            "headless": not with_ui,
        }
        admission = self._admit_job(job)
        if admission.accepted:
            if admission.duplicate:
                logger.info(
                    f"Install task '{task_id}' already queued/running; "
                    "reusing the active task."
                )
                if win is not None:
                    try:
                        win.show()
                        win.raise_()
                        win.activateWindow()
                    except Exception:
                        pass
            return admission

        logger.error(
            f"Install task '{task_id}' was not queued: {admission.error}"
        )
        self.event_bus.emit(
            Events.Install.TASK_FAILED,
            {
                "task_id": str(task_id),
                "component_id": str(meta.get("component_id") or ""),
                "meta": meta,
                "error": admission.error,
            },
        )
        return admission

    def _on_run_with_ui(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        self.enqueue(data, with_ui=True)

    def _on_run_headless(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        self.enqueue(data, with_ui=False)
