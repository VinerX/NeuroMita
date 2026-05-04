from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Dict, Optional, Sequence

from core.events import Event, Events, get_event_bus
from main_logger import logger


_VALID_MODES = frozenset(("auto", "shared", "split"))
_SHARED_WORKER = "shared"
_DEFAULT_SERVICES = ("tts", "asr", "rag")


def _detect_gpu_vendor() -> str:
    try:
        from utils.gpu_utils import check_gpu_provider

        return str(check_gpu_provider() or "CPU").strip().upper()
    except Exception:
        return "CPU"


class _Worker:
    def __init__(self, ctx: mp.context.BaseContext, worker_name: str, service_names: Sequence[str]):
        self.worker_name = str(worker_name or "").strip().lower()
        self.service_names = tuple(str(s or "").strip().lower() for s in (service_names or ()) if str(s or "").strip())
        self.primary_service = self.service_names[0] if self.service_names else self.worker_name
        self.ctx = ctx

        self.cmd_q = ctx.Queue()
        self.res_q = ctx.Queue()
        self.log_q = ctx.Queue()

        self.proc: Optional[mp.Process] = None
        self.ready = threading.Event()
        self.ready_by_service: dict[str, threading.Event] = {
            service: threading.Event() for service in self.service_names
        }
        self.stopping = threading.Event()

        self.pending: Dict[str, Future] = {}
        self.pending_lock = threading.RLock()

        self.res_thread: Optional[threading.Thread] = None
        self.log_thread: Optional[threading.Thread] = None

    def supports(self, service: str) -> bool:
        return str(service or "").strip().lower() in self.ready_by_service

    def start(self):
        from handlers.ai_engine.worker_process import run_worker_process

        self.stopping.clear()
        self.ready.clear()
        for ev in self.ready_by_service.values():
            ev.clear()

        self.proc = self.ctx.Process(
            target=run_worker_process,
            args=(self.worker_name, self.cmd_q, self.res_q, self.log_q),
            daemon=True,
        )
        self.proc.start()

        self.res_thread = threading.Thread(target=self._result_loop, daemon=True)
        self.log_thread = threading.Thread(target=self._log_loop, daemon=True)
        self.res_thread.start()
        self.log_thread.start()

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
                }
            )
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
                }
            )
        except Exception as e:
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.set_exception(e)
            return False

        try:
            ok = bool(fut.result(timeout=max(1.0, float(timeout or 0.0)) + 1.0))
        except Exception:
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

    def stop(self, timeout: float = 5.0):
        if self.stopping.is_set():
            return
        self.stopping.set()

        try:
            self.cmd_q.put({"req_id": "shutdown", "control": "shutdown", "payload": {}})
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
        except Exception:
            pass

        with self.pending_lock:
            pending = list(self.pending.items())
            self.pending.clear()

        for _rid, fut in pending:
            try:
                if not fut.done():
                    fut.set_exception(RuntimeError(f"Worker '{self.worker_name}' shutdown"))
            except Exception:
                pass

    def _result_loop(self):
        eb = get_event_bus()
        while not self.stopping.is_set():
            try:
                msg = self.res_q.get()
            except Exception:
                time.sleep(0.05)
                continue

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
                time.sleep(0.05)
                continue

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


class AIEngineController:
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
            resolved = "split" if gpu_vendor == "AMD" else "shared"
            logger.info(
                f"AIEngineController auto mode resolved to '{resolved}' "
                f"(gpu_vendor={gpu_vendor})"
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

            nw = _Worker(self._ctx, s, (s,))
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

            nw = _Worker(self._ctx, worker_name, service_names)
            self._workers[worker_name] = nw
            for service_name in service_names:
                self._service_to_worker[service_name] = worker_name
            nw.start()

            ready_timeout = max(1.0, float(timeout or 0.0))
            return all(nw.wait_ready(service_name, timeout=ready_timeout) for service_name in service_names)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            ws = list(self._workers.values())
        for w in ws:
            try:
                w.stop(timeout=timeout)
            except Exception:
                pass
