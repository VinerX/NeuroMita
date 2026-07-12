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
        self.selection = {
            "tts": SimpleNamespace(logical_id="tts-voice", revision_id="rev")
        }
        self.promoted = None
        self.promoted_selection = None
        self.promotion_cleanup = None
        self.excluded = None
        self.preferred = None
        self.fail_promotion = False
        self.restored = None
        self.cleanup_calls = 0

    def active_for(self, *, category: str, item_id: str):
        if category == "tts" and item_id == "voice-a":
            return self.record
        return SimpleNamespace(
            logical_id=f"{category}-{item_id}",
            revision_id="rev",
            category=category,
            item_id=item_id,
        )

    def runtime_composition(
        self,
        *,
        selection=None,
        exclude_logical_ids=(),
        preferred_core_layer_ids=(),
    ):
        self.excluded = tuple(exclude_logical_ids)
        self.preferred = tuple(preferred_core_layer_ids)
        selected = dict(self.selection if selection is None else selection)
        selected_tts = selected.get("tts")
        selected_tts_id = getattr(selected_tts, "logical_id", selected_tts)
        paths = self.paths if selected_tts_id == "tts-voice" else ()
        return SimpleNamespace(
            paths=paths,
            core_layer_ids=self.preferred,
            records=(),
            probe_modules=self.probe_modules if paths else (),
        )

    def runtime_selection(self):
        return dict(self.selection)

    def selection_with(self, slot: str, record):
        selected = dict(self.selection)
        if record is None:
            selected.pop(slot, None)
        else:
            selected[slot] = SimpleNamespace(
                logical_id=record.logical_id,
                revision_id=record.revision_id,
            )
        return selected

    def is_runtime_selected(
        self,
        logical_id: str,
        *,
        revision_id: str | None = None,
        slot: str | None = None,
    ) -> bool:
        def matches(value) -> bool:
            return bool(
                getattr(value, "logical_id", value) == logical_id
                and (
                    not revision_id
                    or getattr(value, "revision_id", "") == revision_id
                )
            )

        if slot is not None:
            return matches(self.selection.get(slot))
        return any(matches(value) for value in self.selection.values())

    def registry_snapshot(self):
        return {"snapshot": True}

    def restore_registry(self, snapshot) -> None:
        self.restored = snapshot

    def cleanup_unreferenced_core_layers(self) -> None:
        self.cleanup_calls += 1

    def promote_runtime_selection(self, selection, composition, *, cleanup: bool = True) -> None:
        if self.fail_promotion:
            raise RuntimeError("registry write failed")
        self.selection = dict(selection)
        self.promoted_selection = dict(selection)
        self.promoted = composition
        self.promotion_cleanup = cleanup


class _Worker:
    created: list["_Worker"] = []
    candidate_ready = True
    ready_sequence: list[bool] = []
    validation_result = True
    lifecycle: list[tuple[str, "_Worker"]] = []

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
        self.last_error = ""
        self.started = False
        self.stopped = False
        self._ready = bool(self.candidate_ready)
        self.calls: list[tuple[str, str, dict]] = []
        self.proc = _Proc()
        self.started_at = 0.0
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True
        self.started_at = time.monotonic()
        self._ready = (
            bool(self.__class__.ready_sequence.pop(0))
            if self.__class__.ready_sequence
            else bool(self.candidate_ready)
        )
        self.__class__.lifecycle.append(("start", self))
        if not self._ready:
            self.proc.alive = False

    def supports(self, service: str) -> bool:
        return service in self.service_names

    def wait_ready(self, service: str, timeout: float) -> bool:
        return self.started and service in self.service_names and self._ready

    def stop(self, timeout: float) -> None:
        self.stopped = True
        self.proc.alive = False
        self.__class__.lifecycle.append(("stop", self))

    def call(self, method, payload=None, *, service=None, timeout=None):
        from concurrent.futures import Future

        self.calls.append((str(service), str(method), dict(payload or {})))
        future = Future()
        future.set_result(self.validation_result)
        return future


def _controller(current: _Worker, registry: _EnvironmentRegistry) -> AIEngineController:
    controller = AIEngineController.__new__(AIEngineController)
    controller.mode = "shared"
    controller._environments = registry
    controller._lock = threading.RLock()
    controller._runtime_switch_lock = threading.RLock()
    controller._recovery_lock = threading.RLock()
    controller._shutting_down = threading.Event()
    controller._restart_attempts = {}
    controller._runtime_validations = {}
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
    _Worker.lifecycle.clear()
    _Worker.candidate_ready = False
    _Worker.ready_sequence = [False, True]

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.activate_environment("tts", "voice-a", category="tts", timeout=1.0)

    assert result is False
    replacement = controller._workers["shared"]
    assert current.stopped is True
    assert replacement is not current
    assert replacement.python_paths == current.python_paths
    assert registry.promoted is None


def test_successful_candidate_switches_all_services_atomically() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/new-overlay", "X:/new-backend"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.lifecycle.clear()
    _Worker.ready_sequence.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.activate_environment("tts", "voice-a", category="tts", timeout=1.0)

    assert result is True
    replacement = controller._workers["shared"]
    assert replacement is not current
    assert replacement.python_paths == registry.paths
    assert current.stopped is True
    assert _Worker.lifecycle.index(("stop", current)) < _Worker.lifecycle.index(("start", replacement))
    assert registry.promoted is not None
    assert set(controller._service_to_worker) == {"tts", "asr", "rag", "beats"}


def test_model_initialization_failure_preserves_current_shared_worker() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/new-overlay", "X:/new-backend"))
    controller = _controller(current, registry)
    _Worker.created.clear()
    _Worker.lifecycle.clear()
    _Worker.ready_sequence.clear()
    _Worker.candidate_ready = True
    _Worker.validation_result = False

    try:
        with patch("controllers.ai_engine_controller._Worker", _Worker):
            result = controller.activate_environment(
                "tts",
                "voice-a",
                category="tts",
                timeout=1.0,
                validation_method="init_model",
                validation_payload={"model_id": "voice-a"},
                validation_timeout=1.0,
            )
    finally:
        _Worker.validation_result = True

    assert result is False
    replacement = controller._workers["shared"]
    assert replacement is not current
    assert replacement.python_paths == current.python_paths
    assert current.stopped is True
    assert {
        slot: (value.logical_id, value.revision_id)
        for slot, value in registry.selection.items()
    } == {"tts": ("tts-voice", "rev")}
    assert registry.promoted is None


def test_expanding_shared_runtime_reinitializes_existing_services_before_swap() -> None:
    current = _current_worker(("X:/old-overlay", "X:/old-backend"))
    registry = _EnvironmentRegistry(("X:/combined-overlays", "X:/new-backend"))
    controller = _controller(current, registry)
    controller._runtime_validations = {
        "tts": ("tts", "init_model", {"model_id": "voice-a"}, 1.0),
    }
    _Worker.created.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.activate_environment(
            "asr",
            "whisper",
            category="asr",
            timeout=1.0,
            validation_method="start_live",
            validation_payload={"engine_id": "whisper"},
            validation_timeout=1.0,
        )

    assert result is True
    replacement = controller._workers["shared"]
    assert replacement.calls == [
        ("tts", "init_model", {"model_id": "voice-a"}),
        ("asr", "start_live", {"engine_id": "whisper"}),
    ]
    assert current.stopped is True
    assert controller._runtime_validations.keys() == {"tts", "asr"}


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
    assert registry.promoted_selection == {}
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
    _Worker.lifecycle.clear()
    _Worker.ready_sequence.clear()
    _Worker.candidate_ready = True

    with patch("controllers.ai_engine_controller._Worker", _Worker):
        result = controller.refresh_runtime(timeout=1.0)

    assert result is False
    replacement = controller._workers["shared"]
    assert replacement is not current
    assert replacement.python_paths == current.python_paths
    assert current.stopped is True
    assert len(_Worker.created) == 2
    assert _Worker.created[0].stopped is True
    assert registry.restored == {"snapshot": True}


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


def test_rag_runtime_uses_independent_slots_in_one_shared_worker() -> None:
    current = _current_worker(("X:/shared",))
    registry = _EnvironmentRegistry(("X:/shared",))
    controller = _controller(current, registry)
    controller._runtime_validations = {
        "tts": ("tts", "init_model", {"model_id": "voice-a"}, 1.0),
    }

    embeddings_ok = controller.activate_environment(
        "rag",
        "embeddings",
        category="rag",
        runtime_slot="rag:embeddings",
        timeout=1.0,
        validation_method="warmup_embeddings",
        validation_payload={"model_name": "embed-model"},
        validation_timeout=1.0,
    )
    reranker_ok = controller.activate_environment(
        "rag",
        "reranker",
        category="rag",
        runtime_slot="rag:reranker",
        timeout=1.0,
        validation_method="warmup_reranker",
        validation_payload={"model_name": "reranker-model"},
        validation_timeout=1.0,
    )

    assert embeddings_ok is True
    assert reranker_ok is True
    assert {
        slot: (value.logical_id, value.revision_id)
        for slot, value in registry.selection.items()
    } == {
        "tts": ("tts-voice", "rev"),
        "rag:embeddings": ("rag-embeddings", "rev"),
        "rag:reranker": ("rag-reranker", "rev"),
    }
    assert controller._runtime_validations.keys() == {
        "tts",
        "rag:embeddings",
        "rag:reranker",
    }
    assert current.calls[-3:] == [
        ("tts", "init_model", {"model_id": "voice-a"}),
        ("rag", "warmup_embeddings", {"model_name": "embed-model"}),
        ("rag", "warmup_reranker", {"model_name": "reranker-model"}),
    ]


def test_candidate_bootstrap_uses_dedicated_timeout_floor() -> None:
    from controllers.ai_engine_controller import _bootstrap_timeout

    with patch.dict(
        "os.environ",
        {"NEUROMITA_AI_BOOTSTRAP_TIMEOUT": "123"},
        clear=False,
    ):
        assert _bootstrap_timeout(1.0) == 123.0
        assert _bootstrap_timeout(240.0) == 240.0
