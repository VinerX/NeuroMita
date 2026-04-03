import multiprocessing as mp
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Optional, Dict, Any

from main_logger import logger
from core.events import get_event_bus, Events, Event


class _Worker:
    def __init__(self, ctx: mp.context.BaseContext, service_name: str):
        self.service = str(service_name)
        self.ctx = ctx

        self.cmd_q = ctx.Queue()
        self.res_q = ctx.Queue()
        self.log_q = ctx.Queue()

        self.proc: Optional[mp.Process] = None
        self.ready = threading.Event()
        self.stopping = threading.Event()

        self.pending: Dict[str, Future] = {}
        self.pending_lock = threading.RLock()

        self.res_thread: Optional[threading.Thread] = None
        self.log_thread: Optional[threading.Thread] = None

    def start(self):
        from handlers.ai_engine.worker_process import run_worker_process

        self.stopping.clear()
        self.ready.clear()

        self.proc = self.ctx.Process(
            target=run_worker_process,
            args=(self.service, self.cmd_q, self.res_q, self.log_q),
            daemon=True,
        )
        self.proc.start()

        self.res_thread = threading.Thread(target=self._result_loop, daemon=True)
        self.log_thread = threading.Thread(target=self._log_loop, daemon=True)
        self.res_thread.start()
        self.log_thread.start()

    def call(self, method: str, payload: Optional[dict] = None) -> Future:
        if self.stopping.is_set():
            f = Future()
            f.set_exception(RuntimeError(f"Worker '{self.service}' is stopping"))
            return f

        req_id = str(uuid.uuid4())
        fut = Future()

        with self.pending_lock:
            self.pending[req_id] = fut

        try:
            self.cmd_q.put({"req_id": req_id, "method": str(method), "payload": payload or {}})
        except Exception as e:
            with self.pending_lock:
                self.pending.pop(req_id, None)
            fut.set_exception(e)

        return fut

    def stop(self, timeout: float = 5.0):
        if self.stopping.is_set():
            return
        self.stopping.set()

        try:
            self.cmd_q.put({"req_id": "shutdown", "method": "shutdown", "payload": {}})
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
                    fut.set_exception(RuntimeError(f"Worker '{self.service}' shutdown"))
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
                self.ready.set()
                continue

            if mtype == "event":
                ev = str(msg.get("event") or "")
                data = msg.get("data")
                eb.emit(Events.AI.ENGINE_EVENT, {"service": self.service, "event": ev, "data": data})
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
                    logger.error(f"[AI:{self.service}] {text}")
                elif level == "warning":
                    logger.warning(f"[AI:{self.service}] {text}")
                elif level == "success":
                    logger.success(f"[AI:{self.service}] {text}")
                else:
                    logger.info(f"[AI:{self.service}] {text}")
            except Exception:
                pass


class AIEngineController:
    """
    AI Hub в GUI-процессе:
      - управляет несколькими AI worker процессами (tts/asr/...)
      - умеет перезапускать отдельный сервис (важно для Fish compile конфликтов)
      - проксирует вызовы: call(service, method, payload)
      - транслирует async события из worker -> Events.AI.ENGINE_EVENT
    """

    def __init__(self):
        self.event_bus = get_event_bus()
        self.event_bus.subscribe(Events.AI.GET_ENGINE, self._on_get_engine, weak=False)
        self.event_bus.subscribe(Events.AI.RESTART_SERVICE, self._on_restart_service, weak=False)

        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()

        self._workers: dict[str, _Worker] = {
            "tts": _Worker(self._ctx, "tts"),
            "asr": _Worker(self._ctx, "asr"),
        }

        # стартуем оба, но тяжёлые импорты в сервисах делаются лениво (в handle/start_live/init_model)
        for w in self._workers.values():
            w.start()

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

            self.event_bus.emit(Events.AI.SERVICE_RESTARTED, {
                "service": service,
                "ok": ok,
                "error": err,
            })

        threading.Thread(target=worker, daemon=True).start()
        return True

    def call(self, service: str, method: str, payload: Optional[dict] = None) -> Future:
        s = str(service or "").strip().lower()
        m = str(method or "").strip()
        if not s or not m:
            f = Future()
            f.set_exception(ValueError("Missing service/method"))
            return f

        w = self._workers.get(s)
        if not w:
            f = Future()
            f.set_exception(RuntimeError(f"Unknown service: {s}"))
            return f

        return w.call(m, payload or {})

    def wait_ready(self, service: str, timeout: float = 3.0) -> bool:
        w = self._workers.get(str(service or "").strip().lower())
        if not w:
            return False
        return bool(w.ready.wait(timeout=float(timeout or 0.0)))

    def restart_service(self, service: str, timeout: float = 5.0) -> bool:
        s = str(service or "").strip().lower()
        with self._lock:
            w = self._workers.get(s)
            if not w:
                return False
            try:
                w.stop(timeout=timeout)
            except Exception:
                pass
            self._workers[s] = _Worker(self._ctx, s)
            self._workers[s].start()
            return True

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            ws = list(self._workers.values())
        for w in ws:
            try:
                w.stop(timeout=timeout)
            except Exception:
                pass