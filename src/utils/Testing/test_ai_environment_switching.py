from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from controllers.ai_engine_controller import AIEngineController


class _Proc:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


class _EnvironmentRegistry:
    def __init__(
        self,
        paths: tuple[str, ...],
        probe_modules: tuple[str, ...] = (),
    ) -> None:
        self.record = SimpleNamespace(
            logical_id="tts-voice",
            revision_id="rev",
            category="tts",
            item_id="voice-a",
        )
        self.paths = paths
        self.probe_modules = probe_modules
        self.promoted = None
        self.promotion_cleanup = None
        self.excluded = None
        self.preferred = None
        self.fail_promotion = False
        self.restored = None
        self.cleanup_calls = 0

    def active_for(self, *, category: str, item_id: str):
        assert category == "tts"
        assert item_id == "voice-a"
        return self.record

    def runtime_composition(
        self,
        *,
        exclude_logical_ids=(),
        preferred_core_layer_ids=(),
    ):
        self.excluded = tuple(exclude_logical_ids)
        self.preferred = tuple(preferred_core_layer_ids)
        paths = () if self.excluded else self.paths
        return SimpleNamespace(
            paths=paths,
            core_layer_ids=self.preferred,
            records=(),
            probe_modules=() if self.excluded else self.probe_modules,
        )

    def registry_snapshot(self):
        return {"snapshot": True}

    def restore_registry(self, snapshot) -> None:
        self.restored = snapshot

    def cleanup_unreferenced_core_layers(self) -> None:
        self.cleanup_calls += 1

    def promote_runtime_composition(self, composition, *, cleanup: bool = True) -> None:
        if self.fail_promotion:
            raise RuntimeError("registry write failed")
        self.promoted = composition
        self.promotion_cleanup = cleanup


class _Worker:
    created: list["_Worker"] = []
    candidate_ready = True

    def __init__(
        self,
        _ctx,
        worker_name,
        service_names,
        *,
        python_paths=(),
        probe_modules=(),
        on_crash=None,
    ) -> None:
        self.worker_name = worker_name
        self.service_names = tuple(service_names)
        self.primary_service = self.service_names[0]
        self.python_paths = tuple(python_paths)
        self.probe_modules = tuple(probe_modules)
        self.on_crash = on_crash
        self.started = False
        self.stopped = False
        self.proc = _Proc()
        self.started_at = 0.0
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True
        self.started_at = time.monotonic()

    def wait_ready(self, service: str, timeout: float) -> bool:
        return self.started and service in self.service_names and self.candidate_ready

    def stop(self, timeout: float) -> None:
        self.stopped = True
        self.proc.alive = False


def _controller(current: _Worker, registry: _EnvironmentRegistry) -> AIEngineController:
    controller = AIEngineController.__new__(AIEngineController)
    controller.mode = "shared"
    controller._environments = registry
    controller._lock = threading.RLock()
    controller._runtime_switch_lock = threading.RLock()
    controller._recovery_lock = threading.RLock()
    controller._shutting_down = threading.Event()
    controller._restart_attempts = {}
    controller._ctx = object()
    controller._workers = {"shared": current}
    controller._service_to_worker = {
        "tts": "shared",
        "asr": "shared",
        "rag": "shared",
        "beats": "shared",
    }
    return controller


def _current_worker(
    paths: tuple[str, ...],
    probe_modules: tuple[str, ...] = (),
) -> _Worker:
    worker = _Worker(
        object(),
        "shared",
        ("tts", "asr", "rag", "beats"),
        python_paths=paths,
        probe_modules=probe_modules,
    )
    worker.started = True
    worker.started_at = time.monotonic()
    return worker


def test_failed_candidate_preserves_current_shared_worker() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/new-overlay", "X:/new-backend"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = False

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.activate_environment("tts", "voice-a", category="tts", timeout=1.0)

    assert result is False
    assert current.stopped is False
    assert controller._workers["shared"] is current
    assert registry.promoted is None


def test_successful_candidate_switches_all_services_atomically() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/new-overlay", "X:/new-backend"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.activate_environment("tts", "voice-a", category="tts", timeout=1.0)

    assert result is True
    replacement = controller._workers["shared"]
    assert replacement is not current
    assert replacement.python_paths == registry.paths
    assert current.stopped is True
    assert registry.promoted is not None
    assert set(controller._service_to_worker) == {"tts", "asr", "rag", "beats"}


def test_deactivate_builds_candidate_without_removed_environment() -> None:
    current = _current_worker(("X:/overlay", "X:/backend"))
    registry = _EnvironmentRegistry(("X:/overlay", "X:/backend"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.deactivate_environment(
            "tts",
            "voice-a",
            category="tts",
            timeout=1.0,
        )

    assert result is True
    assert registry.excluded == ("tts-voice",)
    assert registry.promoted is None
    replacement = controller._workers["shared"]
    assert replacement.python_paths == ()
    assert current.stopped is True


def test_crashed_shared_worker_recovers_with_same_runtime_contract() -> None:
    crashed = _current_worker(("X:/overlay", "X:/cuda-backend"))
    crashed.proc.alive = False
    registry = _EnvironmentRegistry(crashed.python_paths)
    controller = _controller(crashed, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker), patch.dict(
        "os.environ",
        {
            "NEUROMITA_AI_RESTART_LIMIT": "1",
            "NEUROMITA_AI_RESTART_BACKOFF": "0.1",
        },
        clear=False,
    ):
        controller._recover_worker(crashed, exit_code=1)

    replacement = controller._workers["shared"]
    assert replacement is not crashed
    assert replacement.python_paths == crashed.python_paths
    assert replacement.probe_modules == crashed.probe_modules
    assert replacement.service_names == crashed.service_names
    assert replacement.on_crash == controller._on_worker_crash


def test_refresh_runtime_forwards_authoritative_backend_layers() -> None:
    current = _current_worker(("X:/overlay", "X:/new-backend"))
    registry = _EnvironmentRegistry(current.python_paths)
    controller = _controller(current, registry)

    result = controller.refresh_runtime(
        timeout=1.0,
        preferred_core_layer_ids=("torch-2.7.2-cuda",),
    )

    assert result is True
    assert registry.preferred == ("torch-2.7.2-cuda",)
    assert registry.promoted is not None


def test_registry_promotion_failure_preserves_current_worker() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/new-overlay", "X:/new-backend"))
    registry.fail_promotion = True
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.refresh_runtime(timeout=1.0)

    assert result is False
    assert controller._workers["shared"] is current
    assert current.stopped is False
    assert len(_Worker.created) == 1
    assert _Worker.created[0].stopped is True


def test_changed_probe_contract_restarts_worker_even_when_paths_match() -> None:
    paths = ("X:/overlay", "X:/backend")
    current = _current_worker(paths, ("torch",))
    registry = _EnvironmentRegistry(paths, ("torch", "f5_tts"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.refresh_runtime(timeout=1.0)

    assert result is True
    replacement = controller._workers["shared"]
    assert replacement is not current
    assert replacement.probe_modules == ("torch", "f5_tts")
    assert current.stopped is True


def test_repeated_fast_crashes_open_restart_circuit() -> None:
    first = _current_worker(("X:/overlay", "X:/cuda-backend"))
    first.proc.alive = False
    registry = _EnvironmentRegistry(first.python_paths)
    controller = _controller(first, registry)
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker), patch.dict(
        "os.environ",
        {
            "NEUROMITA_AI_RESTART_LIMIT": "2",
            "NEUROMITA_AI_RESTART_BACKOFF": "0.1",
            "NEUROMITA_AI_RESTART_RESET_AFTER": "60",
        },
        clear=False,
    ):
        controller._recover_worker(first, exit_code=1)
        second = controller._workers["shared"]
        second.proc.alive = False
        controller._recover_worker(second, exit_code=1)
        third = controller._workers["shared"]
        third.proc.alive = False
        created_before_circuit = len(_Worker.created)
        controller._recover_worker(third, exit_code=1)

    assert controller._workers["shared"] is third
    assert controller._restart_attempts["shared"] == 2
    assert len(_Worker.created) == created_before_circuit
