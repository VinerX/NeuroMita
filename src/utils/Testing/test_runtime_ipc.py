from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from controllers.ai_engine_controller import AIEngineController
from core.runtime_ipc import IPCMethodNotAllowed, IPCRegistry, ipc_allowed
from core.settings_registry import SettingsRegistry
from services.runtime_ipc_service import (
    RUNTIME_IPC_ENABLED_KEY,
    RUNTIME_IPC_PORT_KEY,
    DefaultRuntimeIPCService,
)


class _Settings:
    def __init__(self, values: dict | None = None) -> None:
        self.registry = SettingsRegistry(values or {})

    def get(self, key, default=None):
        return self.registry.get(key, default)

    def subscribe(self, callback, *, keys=None, replay=False):
        return self.registry.subscribe(callback, keys=keys, replay=replay)

    def update(self, key, value) -> None:
        self.registry.set(key, value, source="test")

    def close(self) -> None:
        self.registry.close()


class _Commands:
    @ipc_allowed("test.echo", description="Echo a value.")
    def echo(self, value):
        return {"value": value}

    def hidden(self):
        return "hidden"


def _request(port: int, payload: dict) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        source = client.makefile("rb")
        return json.loads(source.readline().decode("utf-8"))


def test_registry_exposes_only_decorated_methods():
    registry = IPCRegistry()
    assert registry.register_object(_Commands()) == ("test.echo",)
    assert registry.invoke("test.echo", {"value": 7}) == {"value": 7}
    with pytest.raises(IPCMethodNotAllowed):
        registry.invoke("hidden")


def test_json_server_invokes_allowlisted_method_and_rejects_unknown_method():
    settings = _Settings()
    registry = IPCRegistry()
    service = DefaultRuntimeIPCService(
        settings,
        default_port=0,
        registry=registry,
    )
    try:
        assert service.register_object(_Commands()) == ("test.echo",)
        assert service.start(port=0)
        port = service.status()["port"]
        accepted = _request(port, {"id": 1, "method": "test.echo", "params": {"value": "ok"}})
        rejected = _request(port, {"id": 2, "method": "test.hidden"})

        assert accepted == {"id": 1, "ok": True, "result": {"value": "ok"}}
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "method_not_allowed"
    finally:
        service.close()
        settings.close()


def test_json_server_invokes_ai_restart_service_on_registered_controller():
    calls = []

    class Worker:
        def restart_service(self, service, timeout=0):
            calls.append((service, timeout))
            return True

    controller = AIEngineController.__new__(AIEngineController)
    controller._lock = threading.RLock()
    controller.mode = "shared"
    controller._service_to_worker = {"tts": "shared"}
    controller._workers = {"shared": Worker()}

    settings = _Settings()
    service = DefaultRuntimeIPCService(settings, default_port=0)
    try:
        assert service.register_object(controller) == ("ai.restart_service",)
        assert service.start(port=0)
        port = service.status()["port"]
        methods = _request(port, {"id": 1, "method": "ipc.methods"})
        response = _request(
            port,
            {"id": 2, "method": "ai.restart_service", "params": {"service": "tts", "timeout": 0.1}},
        )

        assert any(item["name"] == "ai.restart_service" for item in methods["result"])
        assert response == {"id": 2, "ok": True, "result": True}
        assert calls == [("tts", 0.1)]
    finally:
        service.close()
        settings.close()


def test_setting_starts_and_stops_server_without_restart():
    settings = _Settings({
        RUNTIME_IPC_ENABLED_KEY: False,
        RUNTIME_IPC_PORT_KEY: 0,
    })
    service = DefaultRuntimeIPCService(settings, default_port=0)
    try:
        assert service.status()["running"] is False
        settings.update(RUNTIME_IPC_ENABLED_KEY, True)
        deadline = time.monotonic() + 2.0
        while not service.status()["running"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.status()["running"] is True

        settings.update(RUNTIME_IPC_ENABLED_KEY, False)
        deadline = time.monotonic() + 2.0
        while service.status()["running"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.status()["running"] is False
    finally:
        service.close()
        settings.close()
