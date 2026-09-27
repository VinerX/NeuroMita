from __future__ import annotations

import json
import socketserver
import threading
from typing import Any, Callable

from core.error_utils import format_exception
from core.runtime_ipc import (
    IPCInvalidParams,
    IPCMethodNotAllowed,
    IPCRegistry,
    ipc_allowed,
)
from core.services import services
from main_logger import logger
from services.contracts import (
    AIEngineAdministrationService,
    HardwareInventoryService,
    RuntimeIPCService,
    SettingsService,
)


RUNTIME_IPC_ENABLED_KEY = "RUNTIME_IPC_ENABLED"
RUNTIME_IPC_PORT_KEY = "RUNTIME_IPC_PORT"
DEFAULT_RUNTIME_IPC_PORT = 47831
MAX_REQUEST_BYTES = 1024 * 1024


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class RuntimeIPCCommands:
    def __init__(
        self,
        status: Callable[[], dict[str, Any]],
        methods: Callable[[], tuple[dict[str, str], ...]],
    ) -> None:
        self._status = status
        self._methods = methods

    @ipc_allowed("ipc.ping", description="Check whether the runtime IPC server responds.")
    def ping(self) -> dict[str, Any]:
        return {"pong": True}

    @ipc_allowed("ipc.status", description="Return the runtime IPC server state.")
    def status(self) -> dict[str, Any]:
        return self._status()

    @ipc_allowed("ipc.methods", description="List explicitly allowed IPC methods.")
    def allowed_methods(self) -> tuple[dict[str, str], ...]:
        return self._methods()

    @ipc_allowed("hardware.snapshot", description="Return the current hardware inventory.")
    def hardware_snapshot(self, refresh: bool = False) -> dict[str, Any]:
        service = services().get_optional(HardwareInventoryService)
        if service is None:
            raise RuntimeError("Hardware inventory service is unavailable")
        return dict(service.snapshot(refresh=bool(refresh)) or {})

    @ipc_allowed("ai.topology", description="Return the current AI worker topology.")
    def ai_topology(self) -> dict[str, Any]:
        service = services().get_optional(AIEngineAdministrationService)
        if service is None:
            raise RuntimeError("AI engine administration service is unavailable")
        return dict(service.topology_snapshot() or {})


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _IPCRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(10.0)
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            self._write({"id": None, "ok": False, "error": {"code": "request_too_large", "message": "Request is too large"}})
            return
        request_id = None
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")
            request_id = request.get("id")
            method = str(request.get("method") or "").strip()
            if not method:
                raise ValueError("method is required")
            result = self.server.registry.invoke(method, request.get("params"))
            response = {"id": request_id, "ok": True, "result": result}
        except IPCMethodNotAllowed as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "method_not_allowed", "message": str(exc)}}
        except IPCInvalidParams as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "invalid_params", "message": str(exc)}}
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "invalid_request", "message": str(exc)}}
        except Exception as exc:
            logger.error(f"Runtime IPC method failed: {format_exception(exc)}", exc_info=True)
            response = {"id": request_id, "ok": False, "error": {"code": "runtime_error", "message": format_exception(exc)}}
        self._write(response)

    def _write(self, response: dict[str, Any]) -> None:
        try:
            payload = json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:
            payload = json.dumps({"id": response.get("id"), "ok": False, "error": {"code": "serialization_error", "message": str(exc)}}).encode("utf-8") + b"\n"
        self.wfile.write(payload)
        self.wfile.flush()


class DefaultRuntimeIPCService(RuntimeIPCService):
    def __init__(
        self,
        settings: SettingsService,
        *,
        host: str = "127.0.0.1",
        default_port: int = DEFAULT_RUNTIME_IPC_PORT,
        registry: IPCRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._host = str(host)
        self._default_port = int(default_port)
        self._registry = registry or IPCRegistry()
        self._lock = threading.RLock()
        self._server: _ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self._bound_configured_port: int | None = None
        self._last_error = ""
        self._registry.register_object(
            RuntimeIPCCommands(self.status, self._registry.methods)
        )
        self._subscription = settings.subscribe(
            self._on_setting_changed,
            keys=(RUNTIME_IPC_ENABLED_KEY, RUNTIME_IPC_PORT_KEY),
            replay=False,
        )
        self._apply_settings()

    def register_object(self, instance: Any) -> tuple[str, ...]:
        return self._registry.register_object(instance)

    def _configured_port(self) -> int:
        raw = self._settings.get(RUNTIME_IPC_PORT_KEY, self._default_port)
        try:
            port = int(raw)
        except (TypeError, ValueError):
            port = self._default_port
        if port == 0:
            return 0
        return port if 1024 <= port <= 65535 else self._default_port

    def _on_setting_changed(self, _change: Any) -> None:
        self._apply_settings()

    def _apply_settings(self) -> None:
        enabled = _as_bool(self._settings.get(RUNTIME_IPC_ENABLED_KEY, False))
        port = self._configured_port()
        current = self.status()
        if not enabled:
            self.stop()
        elif not current["running"] or current["bound_configured_port"] != port:
            self.stop()
            self.start(port=port)

    def start(self, *, port: int | None = None) -> bool:
        selected_port = self._configured_port() if port is None else int(port)
        with self._lock:
            if self._server is not None:
                return True
            try:
                server = _ThreadingTCPServer((self._host, selected_port), _IPCRequestHandler)
                server.registry = self._registry
            except OSError as exc:
                self._last_error = format_exception(exc)
                logger.error(f"Runtime IPC failed to bind {self._host}:{selected_port}: {self._last_error}")
                return False
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.1},
                name="runtime-ipc",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._bound_configured_port = selected_port
            self._last_error = ""
            thread.start()
            actual_port = int(server.server_address[1])
        logger.info(f"Runtime IPC listening on {self._host}:{actual_port}")
        return True

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._bound_configured_port = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        logger.info("Runtime IPC stopped")

    def status(self) -> dict[str, Any]:
        with self._lock:
            server = self._server
            actual_port = int(server.server_address[1]) if server is not None else None
            return {
                "running": server is not None,
                "host": self._host,
                "port": actual_port,
                "configured_port": self._configured_port(),
                "bound_configured_port": self._bound_configured_port,
                "last_error": self._last_error,
            }

    def close(self) -> None:
        subscription = self._subscription
        self._subscription = None
        close = getattr(subscription, "close", None)
        if callable(close):
            close()
        self.stop()
