from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
import uuid
from queue import Full
from concurrent.futures import Future
from typing import Dict, Optional, Sequence

from core.events import Event, Events, get_event_bus
from services.contracts import AIEngineService
from core.runtime_environments import runtime_environments
from main_logger import logger


_VALID_MODES = frozenset(("auto", "shared", "split"))
_SHARED_WORKER = "shared"
_DEFAULT_SERVICES = ("tts", "asr", "rag", "beats")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


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


class _Worker:
    def __init__(
        self,
        ctx: mp.context.BaseContext,
        worker_name: str,
        service_names: Sequence[str],
        *,
        python_paths: Sequence[str] = (),
    ):
        self.worker_name = str(worker_name or "").strip().lower()
        self.service_names = tuple(str(s or "").strip().lower() for s in (service_names or ()) if str(s or "").strip())
        self.primary_service = self.service_names[0] if self.service_names else self.worker_name
        self.python_paths = tuple(
            os.path.abspath(str(path))
            for path in (python_paths or ())
            if str(path).strip()
        )
        self.ctx = ctx

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

        self.pending: Dict[str, Future] = {}
        self.pending_lock = threading.RLock()

        self.res_thread: Optional[threading.Thread] = None
        self.log_thread: Optional[threading.Thread] = None
        self.watch_thread: Optional[threading.Thread] = None

    def supports(self, service: str) -> bool:
        return str(service or "").strip().lower() in self.ready_by_service

    def start(self):
        from handlers.ai_engine.worker_process import run_worker_process

        self.stopping.clear()
        self.expected_exit.clear()
        self.ready.clear()
        for ev in self.ready_by_service.values():
            ev.clear()

        self.proc = self.ctx.Process(
            target=run_worker_process,
            args=(
                self.worker_name,
                self.cmd_q,
                self.res_q,
                self.log_q,
                self.service_names,
                self.python_paths,
            ),
            daemon=True,
        )
        self.proc.start()

        self.res_thread = threading.Thread(
            target=self._result_loop, name=f"ai-result-{self.worker_name}", daemon=True
        )
        self.log_thread = threading.Thread(
            target=self._log_loop, name=f"ai-log-{self.worker_name}", daemon=True
        )
        self.watch_thread = threading.Thread(
            target=self._watch_process, name=f"ai-watch-{self.worker_name}", daemon=True
        )
        self.res_thread.start()
        self.log_thread.start()
        self.watch_thread.start()

    def call(self, method: str, payload: Optional[dict] = None, *, service: Optional[str] = None) -> Future:
        target_service = str(service or self.primary_service).strip().lower()
        if target_service not in self.ready_by_service:
            f = Future()
            f.set_exception(RuntimeError(f"Worker '{self.worker_name}' does not handle service '{target_service}'"))
            return f

        if self.stopping.is_set():
            f = Future()
            f.set_exception(RuntimeError(f"Worker '{self.worker_name}' is stopping"))
            return f

        proc = self.proc
        if proc is None or not proc.is_alive():
            f = Future()
            exit_code = getattr(proc, "exitcode", None) if proc is not None else None
            f.set_exception(
                RuntimeError(f"Worker '{self.worker_name}' is not alive (exitcode={exit_code})")
            )
            return f

        req_id = str(uuid.uuid4())
        fut = Future()

        with self.pending_lock:
            self.pending[req_id] = fut

        try:
            self.cmd_q.put(
                {
                    "req_id": req_id,
                    "service": target_service,
                    "method": str(method),
                    "payload": payload or {},
                },
                timeout=1.0,
            )
        except Full:
            e = RuntimeError(f"Worker '{self.worker_name}' command queue is full")
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.set_exception(e)
        except Exception as e:
            with self.pending_lock:
                self.pending.pop(req_id, None)
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

        try:
            self.cmd_q.put(
                {
                    "req_id": req_id,
                    "control": "restart_service",
                    "service": target_service,
                    "payload": {},
                },
                timeout=1.0,
            )
        except Full:
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.set_exception(RuntimeError(f"Worker '{self.worker_name}' command queue is full"))
            return False
        except Exception as e:
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.set_exception(e)
            return False

        try:
            ok = bool(fut.result(timeout=max(1.0, float(timeout or 0.0)) + 1.0))
        except Exception:
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.cancel()
            return False

        if not ok:
            return False

        return bool(ev.wait(timeout=max(1.0, float(timeout or 0.0))))

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
        for queue_obj in (self.res_q, self.log_q):
            try:
                queue_obj.put(None, timeout=1.0)
            except Exception:
                pass

    def stop(self, timeout: float = 5.0):
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
        while not self.stopping.is_set():
            try:
                msg = self.res_q.get()
            except Exception:
                if self.stopping.is_set():
                    break
                time.sleep(0.05)
                continue

            if msg is None:
                break
            if not isinstance(msg, dict):
                continue

            mtype = msg.get("type")
            if mtype == "ready":
                service = str(msg.get("service") or "").strip().lower()
                ev = self.ready_by_service.get(service)
                if ev is not None:
                    ev.set()
                self.ready.set()
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

                with self.pending_lock:
                    fut = self.pending.pop(str(req_id), None)

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
        while not self.stopping.is_set():
            try:
                msg = self.log_q.get()
            except Exception:
                if self.stopping.is_set():
                    break
                time.sleep(0.05)
                continue

            if msg is None:
                break
            if not isinstance(msg, dict):
                continue

            level = str(msg.get("level") or "info").lower()
            text = str(msg.get("message") or "")

            try:
                if level == "error":
                    logger.error(f"[AI:{self.worker_name}] {text}")
                elif level == "warning":
                    logger.warning(f"[AI:{self.worker_name}] {text}")
                elif level == "success":
                    logger.success(f"[AI:{self.worker_name}] {text}")
                else:
                    logger.info(f"[AI:{self.worker_name}] {text}")
            except Exception:
                pass


class AIEngineController(AIEngineService):
    """
    AI Hub в GUI-процессе:
      - управляет topology AI worker'ов (shared/split)
      - умеет перезапускать отдельный сервис
      - проксирует вызовы: call(service, method, payload)
      - транслирует async события из worker -> Events.AI.ENGINE_EVENT

    Режим задаётся через NEUROMITA_AI_ENGINE_MODE=auto|shared|split.
    auto:
      - AMD    -> split
      - other  -> shared
    """

    def __init__(self):
        self.event_bus = get_event_bus()
        self.event_bus.subscribe(Events.AI.GET_ENGINE, self._on_get_engine, weak=False)
        self.event_bus.subscribe(Events.AI.RESTART_SERVICE, self._on_restart_service, weak=False)

        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()
        self._environments = runtime_environments()

        self.mode = self._resolve_mode()
        self._workers: dict[str, _Worker] = {}
        self._service_to_worker: dict[str, str] = {}
        self._init_workers()

        logger.info(f"AIEngineController topology mode: {self.mode}")

    def _resolve_mode(self) -> str:
        raw = str(os.environ.get("NEUROMITA_AI_ENGINE_MODE", "auto") or "auto").strip().lower()
        if raw not in _VALID_MODES:
            logger.warning(
                f"Unknown NEUROMITA_AI_ENGINE_MODE='{raw}', falling back to auto "
                f"(valid: {', '.join(sorted(_VALID_MODES))})"
            )
            raw = "auto"

        if raw == "auto":
            gpu_vendor = _detect_gpu_vendor()
            gpu_label = _detect_gpu_label()
            resolved = "split" if gpu_vendor == "AMD" else "shared"
            logger.info(
                f"AIEngineController auto mode resolved to '{resolved}' "
                f"(gpu={gpu_label}, gpu_vendor={gpu_vendor})"
            )
            return resolved

        return raw

    def _init_workers(self) -> None:
        if self.mode == "shared":
            shared = _Worker(self._ctx, _SHARED_WORKER, _DEFAULT_SERVICES)
            self._workers = {_SHARED_WORKER: shared}
            self._service_to_worker = {service: _SHARED_WORKER for service in _DEFAULT_SERVICES}
        else:
            self._workers = {
                service: _Worker(self._ctx, service, (service,))
                for service in _DEFAULT_SERVICES
            }
            self._service_to_worker = {service: service for service in _DEFAULT_SERVICES}

        for w in self._workers.values():
            w.start()

    def _worker_for_service(self, service: str) -> Optional[_Worker]:
        s = str(service or "").strip().lower()
        worker_name = self._service_to_worker.get(s)
        if not worker_name:
            return None
        return self._workers.get(worker_name)

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
                },
            )

        threading.Thread(target=worker, daemon=True).start()
        return True

    def call(self, service: str, method: str, payload: Optional[dict] = None) -> Future:
        s = str(service or "").strip().lower()
        m = str(method or "").strip()
        if not s or not m:
            f = Future()
            f.set_exception(ValueError("Missing service/method"))
            return f

        w = self._worker_for_service(s)
        if not w:
            f = Future()
            f.set_exception(RuntimeError(f"Unknown service: {s}"))
            return f

        return w.call(m, payload or {}, service=s)

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

            try:
                w.stop(timeout=timeout)
            except Exception:
                pass

            nw = _Worker(self._ctx, s, (s,), python_paths=w.python_paths)
            self._workers[s] = nw
            self._service_to_worker[s] = s
            nw.start()
            return nw.wait_ready(s, timeout=max(1.0, float(timeout or 0.0)))

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

            try:
                w.stop(timeout=timeout)
            except Exception:
                pass

            nw = _Worker(
                self._ctx,
                worker_name,
                service_names,
                python_paths=w.python_paths,
            )
            self._workers[worker_name] = nw
            for service_name in service_names:
                self._service_to_worker[service_name] = worker_name
            nw.start()

            ready_timeout = max(1.0, float(timeout or 0.0))
            return all(nw.wait_ready(service_name, timeout=ready_timeout) for service_name in service_names)

    @staticmethod
    def _environment_category_for_service(service: str) -> str:
        mapping = {
            "tts": "tts",
            "asr": "asr",
            "rag": "rag",
            "beats": "beats",
        }
        return mapping.get(str(service or "").strip().lower(), str(service or "").strip().lower())

    def activate_environment(
        self,
        service: str,
        item_id: str,
        *,
        category: str | None = None,
        timeout: float = 12.0,
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
            logger.error(
                f"Managed environment is not installed for service={service_name} item={model_id}"
            )
            return False
        python_paths = self._environments.runtime_paths(record)

        with self._lock:
            current = self._worker_for_service(service_name)
            if current is None:
                return False
            if tuple(current.python_paths) == tuple(python_paths) and current.proc is not None and current.proc.is_alive():
                return current.wait_ready(service_name, timeout=max(1.0, float(timeout)))

            worker_name = self._service_to_worker.get(service_name) or service_name
            services = tuple(current.service_names)

            if len(services) > 1:
                remaining = tuple(name for name in services if name != service_name)
                try:
                    current.stop(timeout=timeout)
                except Exception:
                    pass
                self._workers.pop(worker_name, None)

                if remaining:
                    shared_replacement = _Worker(
                        self._ctx,
                        worker_name,
                        remaining,
                        python_paths=(),
                    )
                    self._workers[worker_name] = shared_replacement
                    for name in remaining:
                        self._service_to_worker[name] = worker_name
                    shared_replacement.start()

                dedicated_name = f"{service_name}-environment"
                dedicated = _Worker(
                    self._ctx,
                    dedicated_name,
                    (service_name,),
                    python_paths=python_paths,
                )
                self._workers[dedicated_name] = dedicated
                self._service_to_worker[service_name] = dedicated_name
                dedicated.start()
                target = dedicated
            else:
                try:
                    current.stop(timeout=timeout)
                except Exception:
                    pass
                replacement = _Worker(
                    self._ctx,
                    worker_name,
                    (service_name,),
                    python_paths=python_paths,
                )
                self._workers[worker_name] = replacement
                self._service_to_worker[service_name] = worker_name
                replacement.start()
                target = replacement

        ready = target.wait_ready(service_name, timeout=max(1.0, float(timeout)))
        if ready:
            logger.info(
                f"Activated managed environment for service={service_name} item={model_id}: "
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
            return True
        environment_paths = tuple(self._environments.runtime_paths(record))

        with self._lock:
            current = self._worker_for_service(service_name)
            if current is None or tuple(current.python_paths) != environment_paths:
                return True

            worker_name = self._service_to_worker.get(service_name) or service_name
            if len(current.service_names) != 1:
                raise RuntimeError(
                    f"Managed environment worker for '{service_name}' unexpectedly owns "
                    f"multiple services: {current.service_names}"
                )

            current.stop(timeout=timeout)
            replacement = _Worker(
                self._ctx,
                worker_name,
                (service_name,),
                python_paths=(),
            )
            self._workers[worker_name] = replacement
            self._service_to_worker[service_name] = worker_name
            replacement.start()

        ready = replacement.wait_ready(service_name, timeout=max(1.0, float(timeout)))
        if ready:
            logger.info(
                f"Deactivated managed environment for service={service_name} item={model_id}"
            )
        return ready

    def prepare_shutdown(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.expected_exit.set()

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            ws = list(self._workers.values())
        for w in ws:
            try:
                w.stop(timeout=timeout)
            except Exception:
                pass
