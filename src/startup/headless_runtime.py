from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any

from startup.startup_profiler import startup_trace


@dataclass(frozen=True)
class HeadlessOptions:
    run_seconds: float = 0.0
    status_interval: float = 60.0


class HeadlessRuntimeHost:
    def __init__(self, runtime: Any, options: HeadlessOptions | None = None):
        self.runtime = runtime
        self.logger = runtime.logger
        self.options = options or HeadlessOptions()
        self.controller = None
        self._stop_event = threading.Event()
        self._previous_signal_handlers: dict[int, Any] = {}

    def request_stop(self, reason: str = "requested") -> None:
        if not self._stop_event.is_set():
            self.logger.info(f"Headless shutdown requested: {reason}")
            controller = self.controller
            ai_engine = getattr(controller, "ai_engine_controller", None)
            prepare_shutdown = getattr(ai_engine, "prepare_shutdown", None)
            if callable(prepare_shutdown):
                try:
                    prepare_shutdown()
                except Exception:
                    pass
        self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def handle_signal(signum, _frame):
            try:
                name = signal.Signals(signum).name
            except Exception:
                name = str(signum)
            self.request_stop(name)

        for signum in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if signum is None:
                continue
            try:
                self._previous_signal_handlers[int(signum)] = signal.getsignal(signum)
                signal.signal(signum, handle_signal)
            except Exception:
                pass

    def _restore_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signum, handler in self._previous_signal_handlers.items():
            try:
                signal.signal(signum, handler)
            except Exception:
                pass
        self._previous_signal_handlers.clear()

    def snapshot(self) -> dict[str, Any]:
        controller = self.controller
        server_controller = getattr(controller, "server_controller", None)
        server = getattr(server_controller, "server", None)
        ai_engine = getattr(controller, "ai_engine_controller", None)

        workers: dict[str, Any] = {}
        for name, worker in dict(getattr(ai_engine, "_workers", {}) or {}).items():
            process = getattr(worker, "proc", None)
            workers[str(name)] = {
                "alive": bool(process is not None and process.is_alive()),
                "exitcode": getattr(process, "exitcode", None),
                "ready_services": sorted(
                    service
                    for service, ready_event in dict(getattr(worker, "ready_by_service", {}) or {}).items()
                    if ready_event.is_set()
                ),
            }

        connections = getattr(server, "active_connections", {}) if server is not None else {}
        return {
            "pid": os.getpid(),
            "server_running": bool(
                getattr(server_controller, "running", False)
                and getattr(server, "running", False)
            ),
            "host": getattr(server, "host", None),
            "port": getattr(server, "port", None),
            "connections": len(connections) if isinstance(connections, dict) else 0,
            "ai_mode": getattr(ai_engine, "mode", None),
            "workers": workers,
        }

    def _log_snapshot(self, prefix: str = "Headless status") -> None:
        state = self.snapshot()
        self.logger.info(
            f"{prefix}: pid={state['pid']}, server={state['server_running']}, "
            f"listen={state['host']}:{state['port']}, connections={state['connections']}, "
            f"ai_mode={state['ai_mode']}, workers={state['workers']}"
        )

    def run(self) -> int:
        from controllers.main_controller import MainController

        self._install_signal_handlers()
        try:
            self.controller = MainController(None, startup_mode="headless")
            server_controller = getattr(self.controller, "server_controller", None)
            if server_controller is None or not bool(getattr(server_controller, "running", False)):
                startup_error = getattr(getattr(server_controller, "server", None), "startup_error", None)
                raise RuntimeError(f"Headless server failed to start: {startup_error or 'unknown error'}")

            self._log_snapshot("Headless runtime ready")
            startup_trace.mark("headless.ready", **self.snapshot())
            startup_trace.write()
            interval = max(0.0, float(self.options.status_interval or 0.0))
            run_seconds = max(0.0, float(self.options.run_seconds or 0.0))
            started_at = time.monotonic()
            next_status_at = started_at + interval if interval > 0 else float("inf")

            while not self._stop_event.wait(0.25):
                now = time.monotonic()
                if run_seconds > 0 and now - started_at >= run_seconds:
                    self.request_stop("run duration elapsed")
                    continue
                if now >= next_status_at:
                    self._log_snapshot()
                    next_status_at = now + interval

            return 0
        except KeyboardInterrupt:
            self.request_stop("keyboard interrupt")
            return 0
        except Exception as exc:
            self.logger.error(f"Headless runtime failed: {exc}", exc_info=True)
            return 1
        finally:
            controller = self.controller
            if controller is not None:
                try:
                    controller.close_app()
                except Exception as exc:
                    self.logger.error(f"Headless shutdown failed: {exc}", exc_info=True)
            startup_trace.mark("headless.stopped")
            startup_trace.write()
            self._restore_signal_handlers()
