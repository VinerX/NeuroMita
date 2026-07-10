from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from controllers.ai_engine_controller import AIEngineController


class _EnvironmentRegistry:
    def __init__(self, paths: tuple[str, ...]) -> None:
        self.record = SimpleNamespace(logical_id="tts-voice", revision_id="rev")
        self.paths = paths

    def active_for(self, *, category: str, item_id: str):
        assert category == "tts"
        assert item_id == "voice-a"
        return self.record

    def runtime_paths(self, record) -> tuple[str, ...]:
        assert record is self.record
        return self.paths


class _CurrentWorker:
    def __init__(self, paths: tuple[str, ...]) -> None:
        self.python_paths = paths
        self.service_names = ("tts",)
        self.stopped = False

    def stop(self, timeout: float) -> None:
        self.stopped = True


class _ReplacementWorker:
    created: list["_ReplacementWorker"] = []

    def __init__(self, _ctx, worker_name, service_names, *, python_paths=()) -> None:
        self.worker_name = worker_name
        self.service_names = tuple(service_names)
        self.python_paths = tuple(python_paths)
        self.started = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True

    def wait_ready(self, service: str, timeout: float) -> bool:
        return self.started and service == "tts"


def test_deactivate_environment_replaces_worker_without_managed_paths() -> None:
    environment_paths = ("X:/overlay", "X:/core/torch")
    current = _CurrentWorker(environment_paths)
    controller = AIEngineController.__new__(AIEngineController)
    controller._environments = _EnvironmentRegistry(environment_paths)
    controller._lock = threading.RLock()
    controller._ctx = object()
    controller._workers = {"tts-environment": current}
    controller._service_to_worker = {"tts": "tts-environment"}
    _ReplacementWorker.created.clear()

    with patch("controllers.ai_engine_controller._Worker", _ReplacementWorker):
        result = controller.deactivate_environment(
            "tts",
            "voice-a",
            category="tts",
            timeout=1.0,
        )

    assert result is True
    assert current.stopped is True
    replacement = _ReplacementWorker.created[-1]
    assert replacement.python_paths == ()
    assert replacement.started is True
    assert controller._workers["tts-environment"] is replacement
