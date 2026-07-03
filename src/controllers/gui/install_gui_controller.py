import threading
from collections import deque
from typing import Optional

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

from core.install_types import InstallCallbacks


class InstallGuiController(BaseController):
    """Исполняет задачи установки строго по одной за раз (очередь).

    Раньше каждая задача стартовала в своём демон-потоке, поэтому два клика
    «установить» запускали параллельные pip/uv в одну папку Lib — гонка за файлы
    и битые пакеты без RECORD. Теперь все задачи проходят через единый воркер:
    FIFO-очередь, дедуп по task_id, видимость состояния через QUEUE_CHANGED и
    отмена ещё не начатых задач через CANCEL_QUEUED.
    """

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Install.RUN_WITH_UI, self._on_run_with_ui, weak=False)
        self.event_bus.subscribe(Events.Install.RUN_HEADLESS, self._on_run_headless, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_LOG, self._on_install_task_log, weak=False)
        self.event_bus.subscribe(Events.Install.CANCEL_QUEUED, self._on_cancel_queued, weak=False)

        # Очередь и её воркер.
        self._queue_cond = threading.Condition()
        self._pending: deque[dict] = deque()
        self._running: Optional[dict] = None
        self._worker_started = False

    # ------------------------------------------------------------------
    # Очередь
    # ------------------------------------------------------------------
    def _ensure_worker(self) -> None:
        with self._queue_cond:
            if self._worker_started:
                return
            self._worker_started = True
        threading.Thread(target=self._worker_loop, name="install-queue", daemon=True).start()

    def _enqueue(self, job: dict) -> bool:
        """Ставит задачу в очередь. Возвращает False, если такая задача уже
        выполняется или стоит в очереди (дедуп по task_id)."""
        task_id = str(job.get("task_id") or "")
        with self._queue_cond:
            active_ids = {str((self._running or {}).get("task_id") or "")}
            active_ids.update(str(j.get("task_id") or "") for j in self._pending)
            if task_id and task_id in active_ids:
                return False
            self._pending.append(job)
            self._queue_cond.notify()
        self._ensure_worker()
        self._emit_queue_changed()
        return True

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

    def _queue_snapshot(self) -> dict:
        with self._queue_cond:
            running = None
            if self._running is not None:
                running = {
                    "task_id": self._running.get("task_id"),
                    "title": self._running.get("title"),
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

    def _worker_loop(self) -> None:
        while True:
            with self._queue_cond:
                while not self._pending:
                    self._queue_cond.wait()
                job = self._pending.popleft()
                self._running = job
            self._emit_queue_changed()
            try:
                self._run_job(job)
            except Exception as e:
                logger.error(f"Install worker failed: {e}", exc_info=True)
            finally:
                with self._queue_cond:
                    self._running = None
                self._emit_queue_changed()

    def _run_job(self, job: dict) -> None:
        backend = self._get_backend()
        if backend is None:
            logger.error("InstallController backend not available")
            return

        headless = bool(job.get("headless"))
        task_id = str(job.get("task_id") or "task")

        win = job.get("win")
        cbs = job.get("callbacks")

        # Для штатного UI-пути окно создаём в момент СТАРТА задачи (а не при
        # постановке в очередь), чтобы окна ожидающих задач не накладывались.
        if not headless and win is None and cbs is None:
            win, progress_cb, status_cb, log_cb = self._create_install_window(
                job.get("title") or f"Installing {task_id}",
                job.get("initial_status") or "Preparing...",
            )
            cbs = (progress_cb, status_cb, log_cb)
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
            callbacks = InstallCallbacks(progress=progress_cb, status=status_cb, log=log_cb)

        ok = False
        try:
            ok = backend.run_task(
                task_id=task_id,
                runner=job.get("runner"),
                meta=job.get("meta"),
                callbacks=callbacks,
                timeout_sec=float(job.get("timeout_sec", 3600.0)),
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

        if level in ("error", "exception", "critical") or any(k in low for k in ("error", "ошибка", "failed", "traceback")):
            logger.error(f"[INSTALL] {msg}")
        elif level in ("warn", "warning") or any(k in low for k in ("warning", "предупреж")):
            logger.warning(f"[INSTALL] {msg}")

    # ------------------------------------------------------------------
    # точки входа (постановка в очередь)
    # ------------------------------------------------------------------
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

        # Кастомное окно от встроенного установщика (AI Hub). Если его нет —
        # окно создастся лениво в момент старта задачи (см. _run_job).
        win = None
        cbs = None
        custom_window = data.get("install_window")
        custom_callbacks = data.get("install_callbacks")
        if custom_window is not None:
            if custom_callbacks is None and hasattr(custom_window, "get_threadsafe_callbacks"):
                custom_callbacks = custom_window.get_threadsafe_callbacks()
            if isinstance(custom_callbacks, (tuple, list)) and len(custom_callbacks) == 3:
                win = custom_window
                cbs = tuple(custom_callbacks)
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
            "timeout_sec": float(data.get("timeout_sec", 3600.0)),
            "win": win,
            "callbacks": cbs,
            "headless": False,
        }

        if not self._enqueue(job):
            logger.info(f"Install task '{task_id}' already queued/running; ignoring duplicate.")
            # Поднять уже существующее окно, если оно есть.
            if win is not None:
                try:
                    win.show()
                    win.raise_()
                    win.activateWindow()
                except Exception:
                    pass

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

        job = {
            "task_id": str(task_id),
            "runner": runner,
            "meta": meta,
            "title": data.get("title") or f"Installing {item_id}",
            "initial_status": data.get("initial_status") or "Preparing...",
            "timeout_sec": float(data.get("timeout_sec", 3600.0)),
            "win": None,
            "callbacks": None,
            "headless": True,
        }

        if not self._enqueue(job):
            logger.info(f"Headless install task '{task_id}' already queued/running; ignoring duplicate.")
