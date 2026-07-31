from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
import uuid
from queue import Full
from concurrent.futures import CancelledError, Future, InvalidStateError
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from core.events import Event, Events, get_event_bus
from services.contracts import (
    AIEngineAdministrationService,
    AIEngineService,
    AIRuntimeUnavailable,
    SettingsService,
)
from core.daemon_executor import DaemonExecutor
from core.services import services
from core.runtime_environments import runtime_environments
from core.task_supervisor import task_supervisor
from main_logger import logger


_VALID_MODES = frozenset(("auto", "shared", "split"))
_SHARED_WORKER = "shared"
_DEFAULT_SERVICES = ("tts", "asr", "rag", "beats")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, float(default))


def _detect_gpu_vendor() -> str:
    try:
        from utils.gpu_utils import check_gpu_provider

        return str(check_gpu_provider() or "CPU").strip().upper()
    except Exception:
        return "CPU"


def _detect_gpu_label() -> str:
    try:
        from utils.gpu_utils import format_primary_gpu_label

        return str(format_primary_gpu_label() or "CPU").strip()
    except Exception:
        return "CPU"


def _bootstrap_timeout(requested: float | None = None) -> float:
    return max(
        10.0,
        float(requested or 0.0),
        _env_float("NEUROMITA_AI_BOOTSTRAP_TIMEOUT", 300.0, minimum=10.0),
    )


def _switch_wait_timeout() -> float:
    return _env_float("NEUROMITA_AI_SWITCH_WAIT_TIMEOUT", 60.0, minimum=0.0)


class _WorkerUnavailable(RuntimeError):
    """Воркер не может принять вызов прямо сейчас (гасится или уже мёртв).

    Отдельный тип нужен, чтобы отличить «рантайм как раз пересобирают» от
    настоящей ошибки вызова: первое можно переждать, второе — нет.
    """


class _RuntimeSwitchGate:
    """Окно, в котором рантайм недоступен для вызовов.

    Два разных по природе окна:
      * пересборка состава пакетов (`waitable=True`) — ограничено остановкой
        воркера и bootstrap'ом, его можно и нужно переждать: иначе пакет вызовов
        (например эмбеддинги памяти) теряется целиком;
      * обслуживание (`waitable=False`) — удаление AI-окружений, срок неизвестен,
        ждать нельзя, вызов обязан упасть сразу.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active = False
        self._waitable = False
        self._owner: int | None = None
        self._aborted = False

    def begin(self, *, waitable: bool) -> None:
        with self._cond:
            self._active = True
            self._waitable = bool(waitable)
            self._owner = threading.get_ident()

    def end(self) -> None:
        with self._cond:
            self._active = False
            self._waitable = False
            self._owner = None
            self._cond.notify_all()

    def is_active(self) -> bool:
        with self._cond:
            return self._active

    def reason(self) -> str:
        with self._cond:
            if not self._active:
                return ""
            return (
                "AI runtime is switching package composition"
                if self._waitable
                else "AI runtime is suspended for maintenance"
            )

    def abort_waiters(self) -> None:
        """Движок гасится: пережидать окно больше нет смысла."""
        with self._cond:
            self._aborted = True
            self._cond.notify_all()

    def can_wait_from_caller(self) -> bool:
        """Есть ли смысл пережидать окно для текущего вызывающего потока.

        Поток, который сам ведёт пересборку, ждать себя не может — иначе он
        встанет насмерть на собственном окне.
        """
        with self._cond:
            if not self._active:
                return True
            if self._aborted or not self._waitable:
                return False
            return self._owner != threading.get_ident()

    def wait_idle(self, timeout: float) -> bool:
        """Дождаться закрытия окна. False — ждать нельзя или не уложились."""
        deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
        with self._cond:
            while self._active:
                if (
                    self._aborted
                    or not self._waitable
                    or self._owner == threading.get_ident()
                ):
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._cond.wait(remaining)
            return True


class _Worker:
    def __init__(
        self,
        ctx: mp.context.BaseContext,
        worker_name: str,
        service_names: Sequence[str],
        *,
        python_paths: Sequence[str] = (),
        probe_modules: Sequence[str] = (),
        on_crash: Callable[["_Worker", int | None], None] | None = None,
    ):
        self.worker_name = str(worker_name or "").strip().lower()
        self.service_names = tuple(str(s or "").strip().lower() for s in (service_names or ()) if str(s or "").strip())
        self.primary_service = self.service_names[0] if self.service_names else self.worker_name
        self.python_paths = tuple(
            os.path.abspath(str(path))
            for path in (python_paths or ())
            if str(path).strip()
        )
        self.probe_modules = tuple(
            dict.fromkeys(
                str(module or "").strip()
                for module in (probe_modules or ())
                if str(module or "").strip()
            )
        )
        self.ctx = ctx
        self.on_crash = on_crash

        queue_capacity = _env_int("NEUROMITA_AI_COMMAND_QUEUE", 64, minimum=8)
        self.cmd_q = ctx.Queue(maxsize=queue_capacity)
        self.res_q = ctx.Queue(maxsize=queue_capacity * 2)
        self.log_q = ctx.Queue(maxsize=queue_capacity * 2)

        self.proc: Optional[mp.Process] = None
        self.ready = threading.Event()
        self.ready_by_service: dict[str, threading.Event] = {
            service: threading.Event() for service in self.service_names
        }
        self.stopping = threading.Event()
        self.expected_exit = threading.Event()
        # Замок допуска: либо запрос попадает в pending до того, как воркер
        # объявлен останавливающимся, либо получает отказ и уходит на повтор.
        self.admission_lock = threading.Lock()

        self.pending: Dict[str, Future] = {}
        self.pending_deadlines: dict[str, float] = {}
        self.pending_meta: dict[str, tuple[str, str]] = {}
        self.quarantined_services: dict[str, str] = {}
        self.recovering_services: set[str] = set()
        self.pending_lock = threading.RLock()
        self.request_timeout = _env_float("NEUROMITA_AI_REQUEST_TIMEOUT", 300.0)
        self.heartbeat_timeout = _env_float(
            "NEUROMITA_AI_HEARTBEAT_TIMEOUT",
            180.0,
            minimum=15.0,
        )
        self.heartbeat_startup_grace = _env_float(
            "NEUROMITA_AI_HEARTBEAT_STARTUP_GRACE",
            300.0,
            minimum=30.0,
        )
        self.last_heartbeat: float = 0.0
        self.hard_failure_triggered = threading.Event()

        self.res_thread: Optional[threading.Thread] = None
        self.log_thread: Optional[threading.Thread] = None
        self.watch_thread: Optional[threading.Thread] = None
        self.heartbeat_watch_thread: Optional[threading.Thread] = None
        self.deadline_thread: Optional[threading.Thread] = None
        self.started_at: float = 0.0
        self.last_error: str = ""
        self.last_status: str = ""

    def supports(self, service: str) -> bool:
        return str(service or "").strip().lower() in self.ready_by_service

    def start(self):
        from handlers.ai_engine.worker_process import run_worker_process

        with self.admission_lock:
            self.stopping.clear()
        self.expected_exit.clear()
        self.ready.clear()
        for ev in self.ready_by_service.values():
            ev.clear()
        with self.pending_lock:
            self.quarantined_services.clear()
            self.recovering_services.clear()
        self.hard_failure_triggered.clear()
        self.last_heartbeat = time.monotonic()

        self.proc = self.ctx.Process(
            target=run_worker_process,
            args=(
                self.worker_name,
                self.cmd_q,
                self.res_q,
                self.log_q,
                self.service_names,
                self.python_paths,
                self.probe_modules,
            ),
            daemon=True,
        )
        self.proc.start()
        self.started_at = time.monotonic()

        self.res_thread = task_supervisor().start_thread(
            self, f"ai-result-{self.worker_name}", self._result_loop
        )
        self.log_thread = task_supervisor().start_thread(
            self, f"ai-log-{self.worker_name}", self._log_loop
        )
        self.watch_thread = task_supervisor().start_thread(
            self, f"ai-watch-{self.worker_name}", self._watch_process
        )
        self.heartbeat_watch_thread = task_supervisor().start_thread(
            self,
            f"ai-heartbeat-watch-{self.worker_name}",
            self._heartbeat_watch_loop,
        )
        self.deadline_thread = task_supervisor().start_thread(
            self, f"ai-deadlines-{self.worker_name}", self._deadline_loop
        )

    def call(
        self,
        method: str,
        payload: Optional[dict] = None,
        *,
        service: Optional[str] = None,
        timeout: float | None = None,
    ) -> Future:
        target_service = str(service or self.primary_service).strip().lower()
        if target_service not in self.ready_by_service:
            f = Future()
            f.set_exception(RuntimeError(f"Worker '{self.worker_name}' does not handle service '{target_service}'"))
            return f

        req_id = str(uuid.uuid4())

        def cleanup_cancelled(done: Future) -> None:
            if not done.cancelled():
                return
            with self.pending_lock:
                removed = self.pending.pop(req_id, None)
                self.pending_deadlines.pop(req_id, None)
                self.pending_meta.pop(req_id, None)
            if removed is not None:
                try:
                    self.cmd_q.put_nowait({
                        "req_id": req_id,
                        "control": "cancel_request",
                        "service": target_service,
                    })
                except Exception:
                    pass

        # Проверка «жив ли воркер», регистрация в pending и отправка в очередь —
        # одна неделимая операция. Иначе stop() успевает вклиниться между
        # проверкой и регистрацией, и принятый запрос падает с ошибкой
        # выключения вместо повторной отправки новому воркеру.
        with self.admission_lock:
            if self.stopping.is_set():
                f = Future()
                f.set_exception(_WorkerUnavailable(f"Worker '{self.worker_name}' is stopping"))
                return f

            with self.pending_lock:
                quarantine_reason = self.quarantined_services.get(target_service)
            if quarantine_reason:
                f = Future()
                f.set_exception(
                    RuntimeError(
                        f"AI service '{target_service}' is quarantined after a timeout: "
                        f"{quarantine_reason}"
                    )
                )
                return f

            proc = self.proc
            if proc is None or not proc.is_alive():
                f = Future()
                exit_code = getattr(proc, "exitcode", None) if proc is not None else None
                f.set_exception(
                    _WorkerUnavailable(
                        f"Worker '{self.worker_name}' is not alive (exitcode={exit_code})"
                    )
                )
                return f

            fut = Future()
            deadline = time.monotonic() + max(0.1, float(timeout or self.request_timeout))
            with self.pending_lock:
                self.pending[req_id] = fut
                self.pending_deadlines[req_id] = deadline
                self.pending_meta[req_id] = (target_service, str(method))

            fut.add_done_callback(cleanup_cancelled)

            try:
                self.cmd_q.put_nowait(
                    {
                        "req_id": req_id,
                        "service": target_service,
                        "method": str(method),
                        "payload": payload or {},
                    }
                )
            except Full:
                e = RuntimeError(f"Worker '{self.worker_name}' command queue is full")
                self._pop_pending(req_id)
                fut.set_exception(e)
            except Exception as e:
                self._pop_pending(req_id)
                fut.set_exception(e)

        return fut

    def restart_service(self, service: str, timeout: float = 8.0) -> bool:
        target_service = str(service or "").strip().lower()
        if target_service not in self.ready_by_service:
            return False
        if self.stopping.is_set():
            return False

        ev = self.ready_by_service[target_service]
        ev.clear()

        req_id = str(uuid.uuid4())
        fut = Future()
        with self.pending_lock:
            self.pending[req_id] = fut
            self.pending_deadlines[req_id] = time.monotonic() + max(1.0, float(timeout or 0.0)) + 1.0
            self.pending_meta[req_id] = (target_service, "restart_service")

        try:
            self.cmd_q.put_nowait(
                {
                    "req_id": req_id,
                    "control": "restart_service",
                    "service": target_service,
                    "payload": {},
                }
            )
        except Full:
            self._pop_pending(req_id)
            fut.set_exception(RuntimeError(f"Worker '{self.worker_name}' command queue is full"))
            return False
        except Exception as e:
            self._pop_pending(req_id)
            fut.set_exception(e)
            return False

        try:
            ok = bool(fut.result(timeout=max(1.0, float(timeout or 0.0)) + 1.0))
        except Exception:
            self._pop_pending(req_id)
            fut.cancel()
            return False

        if not ok:
            return False
        ready = bool(ev.wait(timeout=max(1.0, float(timeout or 0.0))))
        if ready:
            with self.pending_lock:
                self.quarantined_services.pop(target_service, None)
        return ready

    def _pop_pending(self, req_id: str) -> Future | None:
        with self.pending_lock:
            future = self.pending.pop(str(req_id), None)
            getattr(self, "pending_deadlines", {}).pop(str(req_id), None)
            getattr(self, "pending_meta", {}).pop(str(req_id), None)
            return future

    def _deadline_loop(self) -> None:
        while not self.stopping.wait(0.2):
            now = time.monotonic()
            expired: list[tuple[str, Future, tuple[str, str]]] = []
            with self.pending_lock:
                deadlines = getattr(self, "pending_deadlines", {})
                metadata = getattr(self, "pending_meta", {})
                for req_id, deadline in tuple(deadlines.items()):
                    if deadline > now:
                        continue
                    future = self.pending.pop(req_id, None)
                    deadlines.pop(req_id, None)
                    meta = metadata.pop(req_id, (self.primary_service, "unknown"))
                    if future is not None:
                        expired.append((req_id, future, meta))
            if not expired:
                continue
            quarantined: dict[str, str] = {}
            for req_id, future, (service, method) in expired:
                reason = f"{service}.{method} exceeded its deadline"
                if not future.done():
                    future.set_exception(TimeoutError(
                        f"AI request timed out: {service}.{method} ({req_id})"
                    ))
                logger.error(
                    f"AI service '{service}' timed out inside worker "
                    f"'{self.worker_name}': {method}"
                )
                quarantined[service] = reason

            for service, reason in quarantined.items():
                with self.pending_lock:
                    self.quarantined_services[service] = reason
                ready_event = self.ready_by_service.get(service)
                if ready_event is not None:
                    ready_event.clear()
                try:
                    self.cmd_q.put_nowait(
                        {
                            "req_id": f"quarantine:{service}:{uuid.uuid4()}",
                            "control": "quarantine_service",
                            "service": service,
                            "payload": {"reason": reason},
                        }
                    )
                except Exception:
                    pass
                try:
                    get_event_bus().emit(
                        Events.AI.ENGINE_EVENT,
                        {
                            "service": service,
                            "event": "service_quarantined",
                            "data": {"worker": self.worker_name, "reason": reason},
                        },
                    )
                except Exception:
                    pass
                self._schedule_service_recovery(service, reason)

    def _schedule_service_recovery(self, service: str, reason: str) -> None:
        target_service = str(service or "").strip().lower()
        if not target_service or self.stopping.is_set():
            return
        with self.pending_lock:
            if target_service in self.recovering_services:
                return
            self.recovering_services.add(target_service)

        try:
            task_supervisor().start_thread(
                self,
                f"ai-timeout-recovery-{self.worker_name}-{target_service}",
                self._recover_timed_out_service,
                args=(target_service, str(reason or "request timeout")),
                replace=True,
            )
        except Exception:
            with self.pending_lock:
                self.recovering_services.discard(target_service)
            logger.exception(
                f"Failed to schedule AI service recovery: {self.worker_name}/{target_service}"
            )

    def _recover_timed_out_service(self, service: str, reason: str) -> None:
        try:
            if self.stopping.is_set():
                return

            drain_timeout = _env_float(
                "NEUROMITA_AI_SERVICE_DRAIN_TIMEOUT",
                30.0,
                minimum=1.0,
            )
            restart_timeout = drain_timeout + _env_float(
                "NEUROMITA_AI_SERVICE_RESTART_GRACE",
                5.0,
                minimum=1.0,
            )
            if self.restart_service(service, timeout=restart_timeout):
                logger.warning(
                    f"AI service '{service}' recovered in worker "
                    f"'{self.worker_name}' after timeout"
                )
                try:
                    get_event_bus().emit(
                        Events.AI.ENGINE_EVENT,
                        {
                            "service": service,
                            "event": "service_recovered",
                            "data": {"worker": self.worker_name, "reason": reason},
                        },
                    )
                except Exception:
                    pass
                return

            self._force_worker_restart(
                f"service '{service}' did not drain after timeout: {reason}"
            )
        finally:
            with self.pending_lock:
                self.recovering_services.discard(service)

    def _heartbeat_watch_loop(self) -> None:
        while not self.stopping.wait(1.0):
            proc = self.proc
            if proc is None or not proc.is_alive():
                return
            now = time.monotonic()
            if not self.ready.is_set():
                if now - self.started_at <= self.heartbeat_startup_grace:
                    continue
            if now - self.last_heartbeat <= self.heartbeat_timeout:
                continue
            self._force_worker_restart(
                f"heartbeat was silent for {now - self.last_heartbeat:.1f}s"
            )
            return

    def _force_worker_restart(self, reason: str) -> None:
        if self.stopping.is_set() or self.expected_exit.is_set():
            return
        if self.hard_failure_triggered.is_set():
            return
        self.hard_failure_triggered.set()
        self.last_error = str(reason)
        logger.error(
            f"AI worker '{self.worker_name}' is unresponsive and will be restarted: "
            f"{reason}"
        )
        try:
            get_event_bus().emit(
                Events.AI.ENGINE_EVENT,
                {
                    "service": self.primary_service,
                    "event": "worker_unresponsive",
                    "data": {"worker": self.worker_name, "reason": str(reason)},
                },
            )
        except Exception:
            pass
        proc = self.proc
        try:
            if proc is not None and proc.is_alive():
                proc.terminate()
        except Exception:
            logger.exception(f"Failed to terminate unresponsive AI worker: {self.worker_name}")

    def wait_ready(self, service: str, timeout: float = 3.0) -> bool:
        target_service = str(service or "").strip().lower()
        ev = self.ready_by_service.get(target_service)
        if ev is None:
            return False
        return bool(ev.wait(timeout=float(timeout or 0.0)))

    def _fail_pending(self, error: BaseException) -> None:
        with self.pending_lock:
            pending = list(self.pending.values())
            self.pending.clear()
            getattr(self, "pending_deadlines", {}).clear()
            getattr(self, "pending_meta", {}).clear()
        for future in pending:
            try:
                if not future.done():
                    future.set_exception(error)
            except Exception:
                pass

    def _watch_process(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            proc.join()
        except Exception:
            return
        if self.stopping.is_set() or self.expected_exit.is_set():
            return

        exit_code = getattr(proc, "exitcode", None)
        error = RuntimeError(
            f"AI worker '{self.worker_name}' terminated unexpectedly (exitcode={exit_code})"
        )
        self.ready.clear()
        for event in self.ready_by_service.values():
            event.clear()
        self._fail_pending(error)
        logger.error(str(error))
        try:
            get_event_bus().emit(
                Events.AI.ENGINE_EVENT,
                {
                    "service": self.primary_service,
                    "event": "worker_crashed",
                    "data": {"worker": self.worker_name, "exitcode": exit_code},
                },
            )
        except Exception:
            pass
        if self.on_crash is not None:
            try:
                self.on_crash(self, exit_code)
            except Exception:
                logger.exception(f"AI worker crash callback failed: {self.worker_name}")
        for queue_obj in (self.res_q, self.log_q):
            try:
                queue_obj.put(None, timeout=1.0)
            except Exception:
                pass

    def stop(self, timeout: float = 5.0):
        # Под тем же замком, что и допуск: после выхода отсюда ни один новый
        # запрос в pending уже не попадёт.
        with self.admission_lock:
            if self.stopping.is_set():
                return
            self.stopping.set()
        expected_exit = getattr(self, "expected_exit", None)
        if expected_exit is None:
            expected_exit = threading.Event()
            self.expected_exit = expected_exit
        expected_exit.set()

        try:
            self.cmd_q.put(
                {"req_id": "shutdown", "control": "shutdown", "payload": {}},
                timeout=0.2,
            )
        except Exception:
            pass

        start = time.time()
        while self.proc is not None and self.proc.is_alive() and (time.time() - start) < float(timeout or 0.0):
            time.sleep(0.05)

        try:
            if self.proc is not None and self.proc.is_alive():
                self.proc.terminate()
        except Exception:
            pass

        try:
            if self.proc is not None:
                self.proc.join(timeout=1.0)
                if self.proc.is_alive():
                    kill = getattr(self.proc, "kill", None)
                    if callable(kill):
                        kill()
                        self.proc.join(timeout=1.0)
        except Exception:
            pass

        for queue_obj in (self.res_q, self.log_q):
            try:
                queue_obj.put_nowait(None)
            except Exception:
                pass

        for thread in (
            getattr(self, "res_thread", None),
            getattr(self, "log_thread", None),
            getattr(self, "watch_thread", None),
            getattr(self, "heartbeat_watch_thread", None),
            getattr(self, "deadline_thread", None),
        ):
            try:
                if (
                    thread is not None
                    and thread is not threading.current_thread()
                    and thread.is_alive()
                ):
                    thread.join(timeout=1.0)
            except Exception:
                pass

        for queue_obj in (self.cmd_q, self.res_q, self.log_q):
            try:
                queue_obj.close()
            except Exception:
                pass
            try:
                queue_obj.cancel_join_thread()
            except Exception:
                pass

        self._fail_pending(RuntimeError(f"Worker '{self.worker_name}' shutdown"))

    def _result_loop(self):
        eb = get_event_bus()
        while True:
            try:
                msg = self.res_q.get()
            except Exception:
                proc = self.proc
                if self.stopping.is_set() and (proc is None or not proc.is_alive()):
                    break
                time.sleep(0.05)
                continue

            if msg is None:
                break
            if not isinstance(msg, dict):
                continue

            mtype = msg.get("type")
            if mtype == "heartbeat":
                self.last_heartbeat = time.monotonic()
                continue

            if mtype == "ready":
                service = str(msg.get("service") or "").strip().lower()
                ev = self.ready_by_service.get(service)
                if ev is not None:
                    ev.set()
                self.ready.set()
                self.last_heartbeat = time.monotonic()
                continue

            if mtype == "event":
                service = str(msg.get("service") or self.primary_service).strip().lower()
                ev = str(msg.get("event") or "")
                data = msg.get("data")
                eb.emit(Events.AI.ENGINE_EVENT, {"service": service, "event": ev, "data": data})
                continue

            if mtype == "response":
                req_id = msg.get("req_id")
                ok = bool(msg.get("ok", False))
                result = msg.get("result")
                err = msg.get("error")

                fut = self._pop_pending(str(req_id))

                if fut is None:
                    continue

                try:
                    if ok:
                        fut.set_result(result)
                    else:
                        fut.set_exception(RuntimeError(str(err or "Engine error")))
                except Exception:
                    pass

    def _log_loop(self):
        while True:
            try:
                msg = self.log_q.get()
            except Exception:
                proc = self.proc
                if self.stopping.is_set() and (proc is None or not proc.is_alive()):
                    break
                time.sleep(0.05)
                continue

            if msg is None:
                break
            if not isinstance(msg, dict):
                continue

            level = str(msg.get("level") or "info").lower()
            text = str(msg.get("message") or "")
            detail = str(msg.get("detail") or "").strip()
            self.last_status = text
            if level == "error":
                self.last_error = text

            try:
                if level == "error":
                    logger.error(f"[AI:{self.worker_name}] {text}")
                elif level == "warning":
                    logger.warning(f"[AI:{self.worker_name}] {text}")
                elif level == "success":
                    logger.success(f"[AI:{self.worker_name}] {text}")
                else:
                    logger.info(f"[AI:{self.worker_name}] {text}")
                if detail:
                    logger.debug(
                        f"[AI:{self.worker_name}] diagnostic traceback for {text}:\n{detail}"
                    )
            except Exception:
                pass


class AIEngineController(AIEngineService, AIEngineAdministrationService):
    """
    AI Hub в GUI-процессе:
      - управляет topology AI worker'ов (shared/split)
      - умеет перезапускать отдельный сервис
      - проксирует вызовы: call(service, method, payload)
      - транслирует async события из worker -> Events.AI.ENGINE_EVENT

    Режим задаётся через NEUROMITA_AI_ENGINE_MODE=auto|shared|split.
    The persisted default is shared. Split is an explicit isolation mode and
    therefore never selected merely from the detected GPU vendor.
    """

    def __init__(self):
        self.event_bus = get_event_bus()
        self.event_bus.subscribe(Events.AI.RESTART_SERVICE, self._on_restart_service, weak=False)

        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()
        self._runtime_switch_lock = threading.RLock()
        self._runtime_switching = _RuntimeSwitchGate()
        # Поколение состава воркеров. Растёт на каждом открытии/закрытии окна
        # пересборки: по нему вызов, взявший воркера до пересборки, понимает, что
        # его отказ — не ошибка сервиса, а смена рантайма, и его нужно повторить.
        self._runtime_epoch = 0
        # Вызовы, пришедшие в окно пересборки: ждут его закрытия в отдельном
        # потоке, чтобы `call` оставался неблокирующим.
        self._switch_dispatcher: DaemonExecutor | None = None
        self._deferred_calls: set[Future] = set()
        self._recovery_lock = threading.RLock()
        self._shutting_down = threading.Event()
        self._restart_attempts: dict[str, int] = {}
        self._runtime_validations: dict[
            str,
            tuple[str, str, dict[str, Any], float],
        ] = {}
        self._environments = runtime_environments()

        self.mode = self._resolve_mode()
        self._workers: dict[str, _Worker] = {}
        self._service_to_worker: dict[str, str] = {}
        self._init_workers()

        logger.info(f"AIEngineController topology mode: {self.mode}")

    def _resolve_mode(self) -> str:
        env_value = os.environ.get("NEUROMITA_AI_ENGINE_MODE")
        settings = services().get_optional(SettingsService)
        configured = settings.get("AI_ENGINE_MODE", "shared") if settings is not None else "shared"
        raw = str(env_value if env_value is not None else configured or "shared").strip().lower()
        if raw not in _VALID_MODES:
            logger.warning(
                f"Unknown NEUROMITA_AI_ENGINE_MODE='{raw}', falling back to auto "
                f"(valid: {', '.join(sorted(_VALID_MODES))})"
            )
            raw = "auto"

        if raw == "auto":
            return "shared"

        return raw

    def _composition_for_service(
        self,
        service: str,
        *,
        selection: dict[str, Any] | None = None,
    ):
        service_name = str(service or "").strip().lower()
        category = self._environment_category_for_service(service_name)
        selected_records = getattr(self._environments, "selected_records", None)
        if callable(selected_records):
            records = tuple(
                record
                for record in selected_records(selection=selection)
                if str(getattr(record, "category", "") or "").strip().lower()
                == category
            )
            return self._environments.runtime_composition(records=records)
        return self._environments.runtime_composition(selection=selection)

    def _init_workers(self) -> None:
        if self.mode == "shared":
            try:
                composition = self._environments.runtime_composition()
                python_paths = composition.paths
                probe_modules = composition.probe_modules
            except Exception as exc:
                logger.error(f"Failed to compose installed AI runtime: {exc}")
                python_paths = ()
                probe_modules = ()
            shared = _Worker(
                self._ctx,
                _SHARED_WORKER,
                _DEFAULT_SERVICES,
                python_paths=python_paths,
                probe_modules=probe_modules,
                on_crash=self._on_worker_crash,
            )
            self._workers = {_SHARED_WORKER: shared}
            self._service_to_worker = {service: _SHARED_WORKER for service in _DEFAULT_SERVICES}
        else:
            self._workers = {}
            for service in _DEFAULT_SERVICES:
                try:
                    composition = self._composition_for_service(service)
                    python_paths = composition.paths
                    probe_modules = composition.probe_modules
                except Exception as exc:
                    logger.error(
                        f"Failed to compose isolated runtime for '{service}': {exc}"
                    )
                    python_paths = ()
                    probe_modules = ()
                self._workers[service] = _Worker(
                    self._ctx,
                    service,
                    (service,),
                    python_paths=python_paths,
                    probe_modules=probe_modules,
                    on_crash=self._on_worker_crash,
                )
            self._service_to_worker = {service: service for service in _DEFAULT_SERVICES}

        for w in self._workers.values():
            w.start()

    def _worker_for_service(self, service: str) -> Optional[_Worker]:
        s = str(service or "").strip().lower()
        worker_name = self._service_to_worker.get(s)
        if not worker_name:
            return None
        return self._workers.get(worker_name)

    # ── допуск вызовов и окно пересборки ──────────────────────────────────
    def _begin_switch(self, *, waitable: bool) -> None:
        """Открыть окно пересборки. Строго под _lock — тем же, под которым
        вызовы берут воркера: иначе вызов успевает пройти проверку окна и уже
        после неё получить воркера, которого прямо сейчас останавливают."""
        with self._lock:
            self._runtime_switching.begin(waitable=waitable)
            self._runtime_epoch += 1

    def _end_switch(self) -> None:
        with self._lock:
            self._runtime_switching.end()
            self._runtime_epoch += 1

    def _admit_call(self, service: str) -> tuple[Optional[_Worker], bool, int]:
        """Атомарный допуск: (воркер, окно_активно, поколение) под одним замком."""
        with self._lock:
            if self._runtime_switching.is_active():
                return None, True, self._runtime_epoch
            return self._worker_for_service(service), False, self._runtime_epoch

    def _runtime_epoch_now(self) -> int:
        with self._lock:
            return self._runtime_epoch

    @staticmethod
    def _wait_all_ready(worker: _Worker, timeout: float) -> bool:
        deadline = time.monotonic() + max(1.0, float(timeout or 0.0))
        while True:
            if all(
                worker.wait_ready(service_name, timeout=0.0)
                for service_name in worker.service_names
            ):
                return True

            proc = worker.proc
            if proc is None or not proc.is_alive():
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.1, remaining))

    def _validation_sequence(
        self,
        validations: dict[
            str,
            tuple[str, str, dict[str, Any], float],
        ] | None = None,
    ) -> tuple[tuple[str, str, dict[str, Any], float], ...]:
        source = validations if validations is not None else self._runtime_validations
        service_order = {name: index for index, name in enumerate(_DEFAULT_SERVICES)}
        ordered_slots = sorted(
            source,
            key=lambda slot: (
                service_order.get(source[slot][0], len(service_order)),
                slot,
            ),
        )
        return tuple(
            (
                source[slot][0],
                source[slot][1],
                dict(source[slot][2]),
                float(source[slot][3]),
            )
            for slot in ordered_slots
        )

    def _validate_worker_runtime(
        self,
        worker: _Worker,
        *,
        ready_timeout: float,
        validations: Sequence[tuple[str, str, dict[str, Any], float]] = (),
    ) -> bool:
        if not self._wait_all_ready(worker, ready_timeout):
            detail = worker.last_error or getattr(worker, "last_status", "") or (
                f"exitcode={getattr(worker.proc, 'exitcode', None)}"
            )
            logger.error(f"Candidate AI runtime did not become ready: {detail}")
            return False

        for service_name, method, payload, method_timeout in validations:
            if not worker.supports(service_name):
                continue
            try:
                future = worker.call(
                    method,
                    payload,
                    service=service_name,
                    timeout=method_timeout,
                )
                result = future.result(timeout=max(1.0, method_timeout) + 1.0)
                if not bool(result):
                    raise RuntimeError(
                        f"{service_name}.{method} returned a negative result"
                    )
            except Exception as exc:
                detail = str(exc)
                logger.error(
                    f"Candidate AI runtime validation failed for "
                    f"{service_name}.{method}: {detail}"
                )
                return False
        return True

    def _switch_to_composition(
        self,
        composition,
        *,
        timeout: float,
        selection: dict[str, Any] | None = None,
        validations: Sequence[tuple[str, str, dict[str, Any], float]] = (),
        reuse_validations: Sequence[tuple[str, str, dict[str, Any], float]] = (),
        promote: bool = True,
    ) -> bool:
        target_paths = tuple(composition.paths)
        target_probes = tuple(getattr(composition, "probe_modules", ()) or ())
        operation_timeout = max(1.0, float(timeout or 0.0))
        bootstrap_timeout = _bootstrap_timeout(operation_timeout)

        def same_contract(
            worker: _Worker | None,
            paths: tuple[str, ...] = target_paths,
            probes: tuple[str, ...] = target_probes,
        ) -> bool:
            return bool(
                worker is not None
                and tuple(worker.python_paths) == tuple(paths)
                and tuple(worker.probe_modules) == tuple(probes)
                and worker.proc is not None
                and worker.proc.is_alive()
            )

        def registry_snapshot():
            if not promote:
                return None
            snapshot = getattr(self._environments, "registry_snapshot", None)
            return snapshot() if callable(snapshot) else None

        def promote_registry(*, cleanup: bool) -> bool:
            if not promote:
                return True
            try:
                runtime_selection = (
                    dict(selection)
                    if selection is not None
                    else dict(self._environments.runtime_selection())
                )
                self._environments.promote_runtime_selection(
                    runtime_selection,
                    composition,
                    cleanup=cleanup,
                )
                return True
            except Exception as exc:
                logger.error(f"Failed to promote shared AI runtime contract: {exc}")
                return False

        def restore_registry(snapshot) -> None:
            if snapshot is None:
                return
            restore = getattr(self._environments, "restore_registry", None)
            if not callable(restore):
                return
            try:
                restore(snapshot)
            except Exception as exc:
                logger.error(f"Failed to restore AI runtime registry: {exc}")

        def cleanup_superseded_runtime_artifacts() -> None:
            if not promote:
                return

            cleanup_revisions = getattr(
                self._environments,
                "cleanup_superseded_revisions",
                None,
            )
            if callable(cleanup_revisions):
                for record in tuple(getattr(composition, "records", ()) or ()):
                    logical_id = str(getattr(record, "logical_id", "") or "").strip()
                    if not logical_id:
                        continue
                    try:
                        cleanup_revisions(logical_id)
                    except Exception as exc:
                        logger.warning(
                            f"Failed to clean superseded revision for '{logical_id}': {exc}"
                        )

            cleanup_layers = getattr(
                self._environments,
                "cleanup_unreferenced_core_layers",
                None,
            )
            if callable(cleanup_layers):
                try:
                    cleanup_layers()
                except Exception as exc:
                    logger.warning(
                        f"Failed to clean superseded AI backend layers: {exc}"
                    )

        with self._runtime_switch_lock:
            if self.mode == "shared":
                with self._lock:
                    current = self._workers.get(_SHARED_WORKER)
                if same_contract(current):
                    assert current is not None
                    # Процесс тот же самый — состояние всех ранее активированных
                    # сервисов в нём живо. Переигрывать их валидации незачем:
                    # для ASR это выгрузка живого цикла и повторная загрузка
                    # модели на каждый чужой activate_environment (например на
                    # каждую озвучку). Выполняем только то, что запросил сам
                    # вызов.
                    if not self._validate_worker_runtime(
                        current,
                        ready_timeout=bootstrap_timeout,
                        validations=reuse_validations,
                    ):
                        return False
                    return promote_registry(cleanup=True)

                previous = current
                previous_paths = tuple(getattr(previous, "python_paths", ()) or ())
                previous_probes = tuple(getattr(previous, "probe_modules", ()) or ())
                previous_services = tuple(
                    getattr(previous, "service_names", ()) or _DEFAULT_SERVICES
                )
                previous_validations = self._validation_sequence()

                def restore_previous_worker() -> bool:
                    if previous is None:
                        return False

                    rollback = _Worker(
                        self._ctx,
                        _SHARED_WORKER,
                        previous_services,
                        python_paths=previous_paths,
                        probe_modules=previous_probes,
                    )
                    rollback.start()
                    if not self._wait_all_ready(rollback, bootstrap_timeout):
                        detail = rollback.last_error or getattr(rollback, "last_status", "") or (
                            f"exitcode={getattr(rollback.proc, 'exitcode', None)}"
                        )
                        logger.error(
                            f"Failed to restore previous shared AI runtime: {detail}"
                        )
                        rollback.stop(timeout=1.0)
                        self._notify_models_lost(
                            previous_services,
                            f"previous AI runtime could not be restored: {detail}",
                        )
                        return False

                    if previous_validations and not self._validate_worker_runtime(
                        rollback,
                        ready_timeout=bootstrap_timeout,
                        validations=previous_validations,
                    ):
                        logger.error(
                            "Previous shared AI runtime was restored, but one or more "
                            "service models could not be reinitialized"
                        )
                        self._notify_models_lost(
                            (item[0] for item in previous_validations),
                            "runtime rollback could not reinitialize service models",
                        )

                    rollback.on_crash = self._on_worker_crash
                    with self._lock:
                        self._workers[_SHARED_WORKER] = rollback
                        self._service_to_worker = {
                            service: _SHARED_WORKER for service in _DEFAULT_SERVICES
                        }
                    return True

                self._begin_switch(waitable=True)
                candidate: _Worker | None = None
                try:
                    if previous is not None:
                        try:
                            previous.stop(timeout=operation_timeout)
                        except Exception as exc:
                            logger.warning(
                                f"Failed to stop current shared AI worker before switch: {exc}"
                            )

                    candidate = _Worker(
                        self._ctx,
                        _SHARED_WORKER,
                        _DEFAULT_SERVICES,
                        python_paths=target_paths,
                        probe_modules=target_probes,
                    )
                    candidate.start()
                    if not self._validate_worker_runtime(
                        candidate,
                        ready_timeout=bootstrap_timeout,
                        validations=validations,
                    ):
                        candidate.stop(timeout=1.0)
                        candidate = None
                        restore_previous_worker()
                        return False

                    snapshot = registry_snapshot()
                    if not promote_registry(cleanup=False):
                        restore_registry(snapshot)
                        candidate.stop(timeout=1.0)
                        candidate = None
                        restore_previous_worker()
                        return False

                    try:
                        with self._lock:
                            candidate.on_crash = self._on_worker_crash
                            self._workers[_SHARED_WORKER] = candidate
                            self._service_to_worker = {
                                service: _SHARED_WORKER for service in _DEFAULT_SERVICES
                            }
                    except Exception:
                        restore_registry(snapshot)
                        candidate.stop(timeout=1.0)
                        candidate = None
                        restore_previous_worker()
                        logger.exception("Failed to publish candidate shared AI worker")
                        return False

                    self._restart_attempts.pop(_SHARED_WORKER, None)
                    cleanup_superseded_runtime_artifacts()
                    return True
                finally:
                    self._end_switch()

            candidates: dict[str, _Worker] = {}
            with self._lock:
                current_workers = dict(self._workers)
            try:
                for service_name in _DEFAULT_SERVICES:
                    isolated = self._composition_for_service(
                        service_name,
                        selection=dict(selection) if selection is not None else None,
                    )
                    service_paths = tuple(isolated.paths)
                    service_probes = tuple(
                        getattr(isolated, "probe_modules", ()) or ()
                    )
                    current = current_workers.get(service_name)
                    if same_contract(current, service_paths, service_probes):
                        assert current is not None
                        candidates[service_name] = current
                        continue
                    candidate = _Worker(
                        self._ctx,
                        service_name,
                        (service_name,),
                        python_paths=service_paths,
                        probe_modules=service_probes,
                    )
                    candidate.start()
                    if not self._wait_all_ready(candidate, bootstrap_timeout):
                        detail = candidate.last_error or getattr(candidate, "last_status", "") or (
                            f"exitcode={getattr(candidate.proc, 'exitcode', None)}"
                        )
                        logger.error(
                            f"Candidate AI worker '{service_name}' did not become ready: {detail}"
                        )
                        candidate.stop(timeout=1.0)
                        return False
                    candidates[service_name] = candidate

                for validation in validations:
                    service_name = validation[0]
                    candidate = candidates.get(service_name)
                    if candidate is None or not self._validate_worker_runtime(
                        candidate,
                        ready_timeout=bootstrap_timeout,
                        validations=(validation,),
                    ):
                        return False

                snapshot = registry_snapshot()
                if not promote_registry(cleanup=False):
                    return False

                try:
                    with self._lock:
                        previous_workers = dict(self._workers)
                        for service_name, candidate in candidates.items():
                            candidate.on_crash = self._on_worker_crash
                            self._workers[service_name] = candidate
                            self._service_to_worker[service_name] = service_name
                except Exception:
                    restore_registry(snapshot)
                    logger.exception("Failed to publish candidate split AI workers")
                    return False

                for service_name, previous in previous_workers.items():
                    replacement = candidates.get(service_name)
                    if previous is not replacement:
                        try:
                            previous.stop(timeout=operation_timeout)
                        except Exception as exc:
                            logger.warning(
                                f"Failed to stop superseded AI worker '{service_name}': {exc}"
                            )
                self._restart_attempts.clear()
                cleanup_superseded_runtime_artifacts()
                return True
            finally:
                for service_name, candidate in candidates.items():
                    if (
                        candidate is not current_workers.get(service_name)
                        and self._workers.get(service_name) is not candidate
                    ):
                        candidate.stop(timeout=1.0)

    def refresh_runtime(
        self,
        timeout: float = 20.0,
        preferred_core_layer_ids: Sequence[str] = (),
    ) -> bool:
        try:
            composition = self._environments.runtime_composition(
                preferred_core_layer_ids=preferred_core_layer_ids,
            )
        except Exception as exc:
            logger.error(f"AI runtime composition rejected: {exc}")
            return False
        return self._switch_to_composition(
            composition,
            timeout=timeout,
            validations=self._validation_sequence(),
        )

    def _on_worker_crash(self, worker: _Worker, exit_code: int | None) -> None:
        if self._shutting_down.is_set():
            return
        task_supervisor().start_thread(
            self,
            f"ai-recover-{worker.worker_name}",
            self._recover_worker,
            args=(worker, exit_code),
            replace=True,
        )

    def _recover_worker(self, crashed: _Worker, exit_code: int | None) -> None:
        max_attempts = _env_int("NEUROMITA_AI_RESTART_LIMIT", 3, minimum=1)
        base_delay = max(
            0.1,
            float(os.environ.get("NEUROMITA_AI_RESTART_BACKOFF", "0.5") or 0.5),
        )
        reset_after = max(
            1.0,
            float(
                os.environ.get("NEUROMITA_AI_RESTART_RESET_AFTER", "60")
                or 60.0
            ),
        )

        with self._recovery_lock:
            with self._lock:
                worker_key = next(
                    (key for key, value in self._workers.items() if value is crashed),
                    None,
                )
            if worker_key is None or self._shutting_down.is_set():
                return

            lifetime = max(0.0, time.monotonic() - float(crashed.started_at or 0.0))
            previous_attempts = (
                0
                if lifetime >= reset_after
                else int(self._restart_attempts.get(worker_key, 0) or 0)
            )
            remaining_attempts = max(0, max_attempts - previous_attempts)

            for local_attempt in range(1, remaining_attempts + 1):
                attempt = previous_attempts + local_attempt
                if self._shutting_down.wait(base_delay * (2 ** (local_attempt - 1))):
                    return
                with self._lock:
                    if self._workers.get(worker_key) is not crashed:
                        return

                candidate = _Worker(
                    self._ctx,
                    worker_key,
                    crashed.service_names,
                    python_paths=crashed.python_paths,
                    probe_modules=crashed.probe_modules,
                )
                candidate.start()
                validations = tuple(
                    item
                    for item in self._validation_sequence()
                    if item[0] in candidate.service_names
                )
                if self._validate_worker_runtime(
                    candidate,
                    ready_timeout=_bootstrap_timeout(20.0),
                    validations=validations,
                ):
                    with self._lock:
                        if self._workers.get(worker_key) is not crashed:
                            candidate.stop(timeout=1.0)
                            return
                        candidate.on_crash = self._on_worker_crash
                        self._workers[worker_key] = candidate
                        for service_name in candidate.service_names:
                            self._service_to_worker[service_name] = worker_key
                    self._restart_attempts[worker_key] = attempt
                    logger.info(
                        f"AI worker '{worker_key}' recovered after crash "
                        f"(exitcode={exit_code}, attempt={attempt})"
                    )
                    return
                candidate.stop(timeout=1.0)
                self._restart_attempts[worker_key] = attempt

            attempts = int(self._restart_attempts.get(worker_key, previous_attempts) or 0)
            logger.error(
                f"AI worker '{worker_key}' restart circuit opened after "
                f"{attempts} attempts"
            )
            self._notify_models_lost(
                crashed.service_names,
                f"AI worker '{worker_key}' did not recover after {attempts} attempts",
            )
            try:
                self.event_bus.emit(
                    Events.AI.ENGINE_EVENT,
                    {
                        "service": crashed.primary_service,
                        "event": "worker_restart_exhausted",
                        "data": {
                            "worker": worker_key,
                            "exitcode": exit_code,
                            "attempts": attempts,
                        },
                    },
                )
            except Exception:
                pass

    def _notify_models_lost(self, service_names: Iterable[str], reason: str) -> None:
        """Процесс движка сменился, а повтор init_model не прошёл: модели этих
        сервисов больше не загружены. Без уведомления GUI продолжает считать их
        инициализированными по своему кешу и рисует «готово» на пустом месте."""
        for service_name in dict.fromkeys(
            str(name or "").strip().lower() for name in service_names
        ):
            if not service_name:
                continue
            try:
                self.event_bus.emit(
                    Events.AI.SERVICE_RESTARTED,
                    {
                        "service": service_name,
                        "ok": False,
                        "error": reason,
                        "requested": False,
                    },
                )
            except Exception:
                logger.exception(
                    f"Failed to notify GUI about lost models of service '{service_name}'"
                )

    def _on_get_engine(self, _event: Event):
        return self

    def get_engine(self) -> Optional["AIEngineController"]:
        return self

    def _on_restart_service(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        service = str(data.get("service") or "").strip().lower()
        timeout = float(data.get("timeout", 8.0) or 8.0)

        if not service:
            return False

        def worker():
            ok = False
            err = None
            try:
                ok = bool(self.restart_service(service, timeout=timeout))
            except Exception as e:
                ok = False
                err = str(e)

            self.event_bus.emit(
                Events.AI.SERVICE_RESTARTED,
                {
                    "service": service,
                    "ok": ok,
                    "error": err,
                    "requested": True,
                },
            )

        task_supervisor().start_thread(
            self,
            f"ai-restart-{service}",
            worker,
            replace=True,
        )
        return True

    def call(
        self,
        service: str,
        method: str,
        payload: Optional[dict] = None,
        *,
        timeout: float | None = None,
    ) -> Future:
        s = str(service or "").strip().lower()
        m = str(method or "").strip()
        if not s or not m:
            f = Future()
            f.set_exception(ValueError("Missing service/method"))
            return f

        # Проверка окна и выбор воркера — одним атомарным шагом: раньше между
        # ними успевала пройти пересборка, и вызов уходил в воркера, который уже
        # останавливают (или не находил ни одного и падал «Unknown service»).
        w, switching, epoch = self._admit_call(s)
        if switching:
            # Пересборку состава пакетов пережидаем: окно короткое (стоп воркера
            # + bootstrap), а мгновенный отказ терял целые пакеты эмбеддингов и
            # заливал лог трейсбеками. Обслуживание пережидать нельзя — падаем.
            return self._defer_or_fail(s, m, payload or {}, timeout=timeout)

        if not w:
            # Воркеров нет — либо сервис действительно неизвестен, либо состав
            # как раз пересобирают. Различаем по поколению, а не по догадке.
            return self._retry_after_switch(
                s, m, payload or {}, timeout=timeout, epoch=epoch,
                fallback=RuntimeError(f"Unknown service: {s}"),
            )

        future = w.call(m, payload or {}, service=s, timeout=timeout)
        if future.done() and self._worker_gone(future):
            return self._retry_after_switch(
                s, m, payload or {}, timeout=timeout, epoch=epoch,
                fallback=future.exception(),
            )
        return future

    def _defer_or_fail(
        self,
        service: str,
        method: str,
        payload: dict,
        *,
        timeout: float | None,
    ) -> Future:
        gate = self._runtime_switching
        if not gate.can_wait_from_caller():
            f = Future()
            f.set_exception(
                AIRuntimeUnavailable(gate.reason() or "AI runtime is unavailable")
            )
            return f
        return self._call_after_switch(service, method, payload, timeout=timeout)

    def _retry_after_switch(
        self,
        service: str,
        method: str,
        payload: dict,
        *,
        timeout: float | None,
        epoch: int,
        fallback: BaseException,
    ) -> Future:
        """Отказ воркера на фоне смены рантайма — не ошибка вызова, а повод повторить.

        Если окно уже открыто или поколение сменилось (пересборка успела пройти
        целиком, пока мы шли к воркеру), вызов уходит в отложенную очередь, а не
        отдаётся вызывающему как сбой сервиса.
        """
        if self._switch_in_progress(epoch):
            return self._defer_or_fail(service, method, payload, timeout=timeout)

        f = Future()
        f.set_exception(fallback)
        return f

    def _switch_in_progress(self, epoch: int) -> bool:
        """Идёт ли пересборка сейчас — или прошла целиком с момента допуска."""
        with self._lock:
            return self._runtime_switching.is_active() or self._runtime_epoch != epoch

    def _call_after_switch(
        self,
        service: str,
        method: str,
        payload: dict,
        *,
        timeout: float | None,
    ) -> Future:
        """Вызов пришёл в окно пересборки рантайма.

        Ждать окно прямо в `call` нельзя: контракт метода — сразу вернуть Future,
        а GUI-поток (озвучка, статусы Triton) заморозился бы на всё окно. Поэтому
        ожидание уносим в отдельный поток, а бюджет ожидания остаётся у
        вызывающего: сколько ждать, он решает своим `future.result(timeout=...)`.
        """
        budget = _switch_wait_timeout()
        if timeout is not None:
            budget = min(budget, max(0.0, float(timeout)))
        deadline = time.monotonic() + budget
        outer: Future = Future()

        dispatcher = None if budget <= 0.0 else self._ensure_switch_dispatcher()
        if dispatcher is None:
            outer.set_exception(
                AIRuntimeUnavailable(
                    self._runtime_switching.reason() or "AI runtime is unavailable"
                )
            )
            return outer

        with self._lock:
            self._deferred_calls.add(outer)
        outer.add_done_callback(self._forget_deferred_call)
        dispatcher.submit(
            self._dispatch_after_switch,
            outer,
            service,
            method,
            payload,
            timeout,
            deadline,
        )
        return outer

    def _ensure_switch_dispatcher(self) -> DaemonExecutor | None:
        with self._lock:
            if self._shutting_down.is_set():
                return None
            if self._switch_dispatcher is None:
                # Один поток: все отложенные вызовы ждут одно и то же окно, а
                # отправка воркеру не блокирует — после закрытия окна очередь
                # разлетается мгновенно, в порядке поступления.
                self._switch_dispatcher = DaemonExecutor(
                    1, thread_name_prefix="ai-switch-dispatch"
                )
            return self._switch_dispatcher

    def _forget_deferred_call(self, future: Future) -> None:
        with self._lock:
            self._deferred_calls.discard(future)

    def _dispatch_after_switch(
        self,
        outer: Future,
        service: str,
        method: str,
        payload: dict,
        timeout: float | None,
        deadline: float,
    ) -> None:
        gate = self._runtime_switching
        try:
            if not outer.set_running_or_notify_cancel():
                return
        except RuntimeError:
            return  # уже завершён (например, движок гасится)

        # Пересборок может быть две подряд (пользователь щёлкает в AI Hub): одна
        # попытка после закрытия окна отдавала бы вызывающему ошибку сервиса за
        # то, что рантайм снова меняют. Пробуем, пока не кончится бюджет
        # ожидания — та же семантика повтора, что и в обычном call().
        while True:
            remaining = deadline - time.monotonic()
            if (
                self._shutting_down.is_set()
                or remaining <= 0.0
                or not gate.wait_idle(remaining)
            ):
                self._settle_deferred(
                    outer,
                    error=AIRuntimeUnavailable(
                        gate.reason() or "AI runtime is unavailable"
                    ),
                )
                return

            # Тот же атомарный допуск, что и в call(): окно только что закрылось,
            # но состав воркеров мог смениться прямо на этом шаге.
            w, switching, epoch = self._admit_call(service)
            if switching:
                continue
            if not w:
                # Воркера нет: либо сервис действительно неизвестен, либо состав
                # снова пересобирают. Различаем по поколению, а не по догадке.
                if self._switch_in_progress(epoch):
                    continue
                self._settle_deferred(
                    outer, error=RuntimeError(f"Unknown service: {service}")
                )
                return

            inner = w.call(method, payload, service=service, timeout=timeout)
            if inner.done() and self._worker_gone(inner) and self._switch_in_progress(epoch):
                # Воркера уже останавливают под новую пересборку — берём нового.
                continue
            inner.add_done_callback(
                lambda done, target=outer: self._copy_result(done, target)
            )
            return

    @staticmethod
    def _worker_gone(future: Future) -> bool:
        try:
            return isinstance(future.exception(), _WorkerUnavailable)
        except CancelledError:
            return False

    def _copy_result(self, source: Future, target: Future) -> None:
        try:
            error = source.exception()
        except CancelledError:
            error = AIRuntimeUnavailable("AI runtime call was cancelled")
        if error is not None:
            self._settle_deferred(target, error=error)
            return
        self._settle_deferred(target, result=source.result())

    @staticmethod
    def _settle_deferred(
        target: Future,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        try:
            if error is not None:
                target.set_exception(error)
            else:
                target.set_result(result)
        except InvalidStateError:
            pass

    def _abort_deferred_calls(self) -> None:
        """Гашение движка: отложенные вызовы обязаны получить ответ.

        Иначе вызывающий (в т.ч. GUI) остаётся висеть на `future.result()`.
        """
        self._runtime_switching.abort_waiters()
        with self._lock:
            pending = tuple(self._deferred_calls)
            self._deferred_calls.clear()
            dispatcher = self._switch_dispatcher
            self._switch_dispatcher = None
        for future in pending:
            self._settle_deferred(
                future, error=AIRuntimeUnavailable("AI engine is shutting down")
            )
        if dispatcher is not None:
            dispatcher.shutdown()

    def wait_ready(self, service: str, timeout: float = 3.0) -> bool:
        s = str(service or "").strip().lower()
        w = self._worker_for_service(s)
        if not w:
            return False
        return w.wait_ready(s, timeout=float(timeout or 0.0))

    def restart_service(self, service: str, timeout: float = 5.0) -> bool:
        s = str(service or "").strip().lower()
        with self._lock:
            w = self._worker_for_service(s)
            if not w:
                return False

            if self.mode == "shared":
                return bool(w.restart_service(s, timeout=timeout))

            nw = _Worker(
                self._ctx,
                s,
                (s,),
                python_paths=w.python_paths,
                probe_modules=w.probe_modules,
            )
            nw.start()
            if not nw.wait_ready(s, timeout=max(1.0, float(timeout or 0.0))):
                nw.stop(timeout=1.0)
                return False
            nw.on_crash = self._on_worker_crash
            self._workers[s] = nw
            self._service_to_worker[s] = s
            w.stop(timeout=timeout)
            return True

    def restart_worker_for_service(self, service: str, timeout: float = 8.0) -> bool:
        s = str(service or "").strip().lower()
        with self._lock:
            worker_name = self._service_to_worker.get(s)
            w = self._worker_for_service(s)
            if not worker_name or not w:
                return False

            service_names = tuple(w.service_names)
            if not service_names:
                service_names = (s,)

            nw = _Worker(
                self._ctx,
                worker_name,
                service_names,
                python_paths=w.python_paths,
                probe_modules=w.probe_modules,
            )
            nw.start()

            ready_timeout = max(1.0, float(timeout or 0.0))
            if not self._wait_all_ready(nw, ready_timeout):
                nw.stop(timeout=1.0)
                return False
            nw.on_crash = self._on_worker_crash
            self._workers[worker_name] = nw
            for service_name in service_names:
                self._service_to_worker[service_name] = worker_name
            w.stop(timeout=timeout)
            return True

    @staticmethod
    def _environment_category_for_service(service: str) -> str:
        mapping = {
            "tts": "tts",
            "asr": "asr",
            "rag": "rag",
            "beats": "beats",
        }
        return mapping.get(str(service or "").strip().lower(), str(service or "").strip().lower())

    @staticmethod
    def _runtime_slot_for(
        service: str,
        item_id: str,
        runtime_slot: str | None = None,
    ) -> str:
        explicit = str(runtime_slot or "").strip().lower()
        if explicit:
            return explicit
        normalized_service = str(service or "").strip().lower()
        normalized_item = str(item_id or "").strip().lower()
        if normalized_service == "rag" and normalized_item:
            return f"rag:{normalized_item}"
        return normalized_service

    def is_environment_active(
        self,
        service: str,
        item_id: str,
        *,
        category: str | None = None,
        runtime_slot: str | None = None,
    ) -> bool:
        service_name = str(service or "").strip().lower()
        model_id = str(item_id or "").strip()
        if not service_name or not model_id:
            return False
        record = self._environments.active_for(
            category=category or self._environment_category_for_service(service_name),
            item_id=model_id,
        )
        if record is None:
            return False
        slot = self._runtime_slot_for(service_name, model_id, runtime_slot)
        if not self._environments.is_runtime_selected(
            record.logical_id,
            revision_id=record.revision_id,
            slot=slot,
        ):
            return False
        worker = self._worker_for_service(service_name)
        return bool(
            worker is not None
            and worker.proc is not None
            and worker.proc.is_alive()
            and worker.wait_ready(service_name, timeout=0.0)
        )

    def activate_environment(
        self,
        service: str,
        item_id: str,
        *,
        category: str | None = None,
        timeout: float = 12.0,
        validation_method: str | None = None,
        validation_payload: dict[str, Any] | None = None,
        validation_timeout: float | None = None,
        runtime_slot: str | None = None,
    ) -> bool:
        service_name = str(service or "").strip().lower()
        model_id = str(item_id or "").strip()
        slot = self._runtime_slot_for(service_name, model_id, runtime_slot)
        if not service_name or not model_id:
            return False

        record = self._environments.active_for(
            category=category or self._environment_category_for_service(service_name),
            item_id=model_id,
        )
        if record is None:
            logger.error(
                f"Managed environment is not installed for service={service_name} item={model_id}"
            )
            return False

        # Слоты активируются параллельно (эмбеддинги и реранкер греются в фоне
        # одновременно), а выбор рантайма и валидации — read-modify-write. Без
        # общего замка вторая активация собрала бы композицию по устаревшему
        # снимку и выкинула слот соседа.
        with self._runtime_switch_lock:
            selection = self._environments.selection_with(slot, record)
            try:
                composition = self._environments.runtime_composition(
                    selection=selection,
                )
            except Exception as exc:
                logger.error(
                    f"Cannot compose shared runtime for service={service_name} "
                    f"item={model_id}: {exc}"
                )
                return False

            candidate_validations = dict(self._runtime_validations)
            current_selection = self._environments.runtime_selection()
            requested_validation: tuple[tuple[str, str, dict[str, Any], float], ...] = ()
            if validation_method:
                candidate_validations[slot] = (
                    service_name,
                    str(validation_method),
                    dict(validation_payload or {}),
                    max(1.0, float(validation_timeout or timeout or 0.0)),
                )
                requested_validation = (candidate_validations[slot],)
            else:
                current_ref = current_selection.get(slot)
                current_identity = (
                    getattr(current_ref, "logical_id", ""),
                    getattr(current_ref, "revision_id", ""),
                )
                if current_identity != (record.logical_id, record.revision_id):
                    candidate_validations.pop(slot, None)

            if not self._switch_to_composition(
                composition,
                timeout=timeout,
                selection=selection,
                validations=self._validation_sequence(candidate_validations),
                reuse_validations=requested_validation,
            ):
                return False
            self._runtime_validations = candidate_validations
        worker = self._worker_for_service(service_name)
        ready = bool(
            worker is not None
            and worker.wait_ready(service_name, timeout=max(1.0, float(timeout or 0.0)))
        )
        if ready:
            logger.info(
                f"Activated shared runtime for service={service_name} item={model_id}: "
                f"{record.logical_id}@{record.revision_id}"
            )
        return ready

    def deactivate_environment(
        self,
        service: str,
        item_id: str,
        *,
        category: str | None = None,
        timeout: float = 12.0,
        persist: bool = True,
        runtime_slot: str | None = None,
    ) -> bool:
        service_name = str(service or "").strip().lower()
        model_id = str(item_id or "").strip()
        slot = self._runtime_slot_for(service_name, model_id, runtime_slot)
        if not service_name or not model_id:
            return False

        record = self._environments.active_for(
            category=category or self._environment_category_for_service(service_name),
            item_id=model_id,
        )
        if record is None:
            return True

        if not self._environments.is_runtime_selected(
            record.logical_id,
            slot=slot,
        ):
            return True

        # Тот же read-modify-write, что и в activate_environment — под общим замком.
        with self._runtime_switch_lock:
            selection = self._environments.selection_with(slot, None)
            candidate_validations = dict(self._runtime_validations)
            candidate_validations.pop(slot, None)
            try:
                composition = self._environments.runtime_composition(
                    selection=selection,
                )
            except Exception as exc:
                logger.error(f"Failed to compose AI runtime without '{record.logical_id}': {exc}")
                return False

            ready = self._switch_to_composition(
                composition,
                timeout=timeout,
                selection=selection,
                validations=self._validation_sequence(candidate_validations),
                promote=persist,
            )
            if ready and persist:
                self._runtime_validations = candidate_validations
        if ready:
            logger.info(
                f"Detached environment from shared runtime: service={service_name} item={model_id}"
            )
        return ready

    def forget_environment(
        self,
        service: str,
        item_id: str,
        *,
        category: str | None = None,
        runtime_slot: str | None = None,
    ) -> None:
        del category
        service_name = str(service or "").strip().lower()
        slot = self._runtime_slot_for(service_name, item_id, runtime_slot)
        if slot:
            self._runtime_validations.pop(slot, None)

    def prepare_shutdown(self) -> None:
        self._shutting_down.set()
        self._abort_deferred_calls()
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.expected_exit.set()

    def topology_snapshot(self) -> dict[str, Any]:
        with self._lock:
            workers = {
                name: {
                    "services": list(worker.service_names),
                    "alive": bool(worker.proc is not None and worker.proc.is_alive()),
                }
                for name, worker in self._workers.items()
            }
        return {
            "mode": self.mode,
            "override": os.environ.get("NEUROMITA_AI_ENGINE_MODE"),
            "suspended": self._runtime_switching.is_active() and not workers,
            "workers": workers,
        }

    def _stop_runtime_workers(self, *, timeout: float) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers = {}
            self._service_to_worker = {}
        for worker in workers:
            worker.expected_exit.set()
        for worker in workers:
            try:
                worker.stop(timeout=timeout)
            except Exception:
                logger.exception(f"Failed to stop AI worker '{worker.worker_name}'")

    def suspend_for_maintenance(self, *, timeout: float = 15.0) -> bool:
        if self._shutting_down.is_set():
            return False
        with self._runtime_switch_lock:
            # Обслуживание не имеет срока: вызовы должны падать сразу, а не ждать.
            self._begin_switch(waitable=False)
            self._stop_runtime_workers(timeout=timeout)
            return True

    def resume_after_maintenance(self) -> bool:
        if self._shutting_down.is_set():
            return False
        with self._runtime_switch_lock:
            try:
                with self._lock:
                    already_running = bool(self._workers)
                if not already_running:
                    self._init_workers()
            finally:
                # Окно закрываем всегда: незакрытое навсегда убивает движок —
                # каждый вызов падал бы с «runtime is suspended».
                self._end_switch()
            return True

    def switch_topology(self, mode: str, *, timeout: float = 30.0) -> dict[str, Any]:
        requested = str(mode or "").strip().lower()
        if requested not in {"shared", "split"}:
            return {"ok": False, "error": f"Unsupported AI engine mode: {mode}", **self.topology_snapshot()}
        override = os.environ.get("NEUROMITA_AI_ENGINE_MODE")
        if override is not None:
            return {
                "ok": False,
                "error": "NEUROMITA_AI_ENGINE_MODE overrides the application setting",
                **self.topology_snapshot(),
            }
        if requested == self.mode:
            return {"ok": True, **self.topology_snapshot()}

        previous = self.mode
        with self._runtime_switch_lock:
            self._begin_switch(waitable=True)
            try:
                self._stop_runtime_workers(timeout=timeout)
                self.mode = requested
                self._init_workers()
            except Exception as exc:
                logger.exception(f"Failed to switch AI topology to '{requested}'")
                self.mode = previous
                self._stop_runtime_workers(timeout=timeout)
                self._init_workers()
                return {"ok": False, "error": str(exc), **self.topology_snapshot()}
            finally:
                self._end_switch()

        settings = services().get_optional(SettingsService)
        if settings is not None:
            settings.update("AI_ENGINE_MODE", requested)
        return {"ok": True, **self.topology_snapshot()}

    def shutdown(self, timeout: float = 5.0) -> None:
        self._shutting_down.set()
        self._abort_deferred_calls()
        self._stop_runtime_workers(timeout=timeout)
