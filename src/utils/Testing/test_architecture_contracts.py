from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pytest

from core.events import EventBus
from core.executors import Pools
from core.services import (
    ServiceAlreadyRegistered,
    ServiceNotRegistered,
    ServiceRegistry,
    services,
)
from core.settings_registry import SettingsRegistry
from services.runtime_features import FeatureSpec, FeatureState, RuntimeFeatureManager


class _Contract(ABC):
    @abstractmethod
    def value(self) -> str: ...


class _Implementation(_Contract):
    def __init__(self, value: str = "ok") -> None:
        self._value = value
        self.stopped = threading.Event()

    def value(self) -> str:
        return self._value

    def shutdown(self) -> None:
        self.stopped.set()


class _WrongImplementation:
    pass


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_event_bus_is_notification_only() -> None:
    bus = EventBus()
    try:
        legacy_name = "emit" + "_and_wait"
        assert not hasattr(bus, legacy_name)
        assert bus.emit("missing", sync=True) is None
    finally:
        bus.shutdown()


def test_removed_sync_event_pool_is_not_declared() -> None:
    legacy_pool = "EVENT_BUS" + "_SYNC"
    assert not hasattr(Pools, legacy_pool)


def test_production_tree_has_no_legacy_sync_event_rpc_symbol() -> None:
    root = Path(__file__).resolve().parents[2]
    forbidden = ("emit" + "_and_wait").encode()
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if any(
            part == "__pycache__" or part.startswith(".")
            for part in path.relative_to(root).parts
        ):
            continue
        if forbidden in path.read_bytes():
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_service_registry_rejects_wrong_implementation() -> None:
    registry = ServiceRegistry()
    with pytest.raises(TypeError):
        registry.register(_Contract, _WrongImplementation())


def test_service_registry_has_single_owner_by_default() -> None:
    registry = ServiceRegistry()
    first = _Implementation("first")
    registry.register(_Contract, first)

    with pytest.raises(ServiceAlreadyRegistered):
        registry.register(_Contract, _Implementation("second"))

    assert registry.get(_Contract) is first


def test_service_registry_replace_is_explicit() -> None:
    registry = ServiceRegistry()
    registry.register(_Contract, _Implementation("first"))
    second = registry.register(_Contract, _Implementation("second"), replace=True)

    assert registry.get(_Contract) is second
    assert registry.get(_Contract).value() == "second"


def test_service_registry_missing_service_is_not_silently_defaulted() -> None:
    registry = ServiceRegistry()
    with pytest.raises(ServiceNotRegistered):
        registry.get(_Contract)
    assert registry.get_optional(_Contract) is None
    assert registry.get_optional(_Contract, "fallback") == "fallback"


def test_service_registry_wait_unblocks_on_registration() -> None:
    registry = ServiceRegistry()
    result: list[_Contract] = []
    finished = threading.Event()

    def waiter() -> None:
        result.append(registry.wait(_Contract, timeout=1.0))
        finished.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.03)
    impl = registry.register(_Contract, _Implementation())

    assert finished.wait(1.0)
    thread.join(timeout=1.0)
    assert result == [impl]


def test_service_registry_wait_has_bounded_timeout() -> None:
    registry = ServiceRegistry()
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        registry.wait(_Contract, timeout=0.03)
    assert time.monotonic() - started < 0.5


def test_service_registry_unregister_removes_contract() -> None:
    registry = ServiceRegistry()
    registry.register(_Contract, _Implementation())
    registry.unregister(_Contract)
    assert not registry.is_registered(_Contract)


def test_runtime_feature_registers_and_unregisters_provided_service() -> None:
    settings = SettingsRegistry({"ENABLED": True})
    manager = RuntimeFeatureManager(settings, max_workers=1)
    services().unregister(_Contract)
    manager.register(
        FeatureSpec(
            name="contract-feature",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=_Implementation,
            provided_services=(_Contract,),
        )
    )
    try:
        instance = manager.ensure("contract-feature", timeout=1.0)
        assert services().get(_Contract) is instance

        settings.set("ENABLED", False)
        _wait_until(lambda: manager.state("contract-feature") is FeatureState.DISABLED)
        assert services().get_optional(_Contract) is None
        assert instance.stopped.is_set()
    finally:
        manager.shutdown()
        services().unregister(_Contract)


def test_runtime_feature_failed_factory_is_observable() -> None:
    settings = SettingsRegistry({"ENABLED": True})
    manager = RuntimeFeatureManager(settings, max_workers=1)

    def broken_factory():
        raise RuntimeError("feature exploded")

    manager.register(
        FeatureSpec(
            name="broken",
            enabled=lambda values: values.get("ENABLED", False),
            factory=broken_factory,
        )
    )
    try:
        with pytest.raises(RuntimeError, match="feature exploded"):
            manager.ensure("broken", timeout=1.0)
        assert manager.state("broken") is FeatureState.FAILED
        snapshot = manager.snapshot()["broken"]
        assert snapshot["state"] == FeatureState.FAILED.value
        assert "feature exploded" in snapshot["error"]
    finally:
        manager.shutdown()


def test_runtime_feature_disabled_during_load_never_becomes_ready() -> None:
    settings = SettingsRegistry({"ENABLED": True})
    entered = threading.Event()
    release = threading.Event()
    resource = _Implementation()
    manager = RuntimeFeatureManager(settings, max_workers=1)

    def factory():
        entered.set()
        release.wait(1.0)
        return resource

    manager.register(
        FeatureSpec(
            name="slow",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=factory,
        )
    )
    try:
        future = manager.ensure_async("slow")
        assert entered.wait(1.0)
        settings.set("ENABLED", False)
        release.set()
        assert future.result(timeout=1.0) is None
        _wait_until(lambda: manager.state("slow") is FeatureState.DISABLED)
        assert resource.stopped.is_set()
        assert manager.get("slow") is None
    finally:
        release.set()
        manager.shutdown()


@pytest.mark.parametrize("enabled", [False, 0, "", None])
def test_disabled_feature_never_calls_factory(enabled) -> None:
    settings = SettingsRegistry({"ENABLED": enabled})
    calls: list[str] = []
    manager = RuntimeFeatureManager(settings, max_workers=1)
    manager.register(
        FeatureSpec(
            name="disabled",
            enabled=lambda values: bool(values.get("ENABLED")),
            factory=lambda: calls.append("called") or _Implementation(),
        )
    )
    try:
        assert manager.start_enabled() == {}
        assert manager.state("disabled") is FeatureState.DISABLED
        assert calls == []
    finally:
        manager.shutdown()


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("controllers.api_presets_controller", "ApiPresetsController"),
        ("controllers.embedding_presets_controller", "EmbeddingPresetsController"),
        ("controllers.model_controller", "ModelController"),
        ("controllers.capture_controller", "CaptureController"),
        ("controllers.local_voice_controller", "LocalVoiceController"),
        ("controllers.voice_model_controller", "VoiceModelController"),
        ("controllers.install_controller", "InstallController"),
        ("controllers.protocols_controller", "ProtocolsController"),
    ],
)
def test_service_controller_is_concrete(module_name: str, class_name: str) -> None:
    import importlib

    cls = getattr(importlib.import_module(module_name), class_name)
    assert cls.__abstractmethods__ == frozenset()


def test_owned_service_handle_cannot_remove_newer_replacement() -> None:
    registry = ServiceRegistry()
    first = _Implementation("first")
    second = _Implementation("second")

    old_handle = registry.register_owned(_Contract, first)
    new_handle = registry.register_owned(_Contract, second, replace=True)

    assert old_handle.close() is False
    assert registry.get(_Contract) is second
    assert new_handle.close() is True
    assert not registry.is_registered(_Contract)


def test_runtime_feature_disable_enable_during_load_keeps_request() -> None:
    settings = SettingsRegistry({"ENABLED": True})
    entered = threading.Event()
    release = threading.Event()
    resource = _Implementation()
    calls: list[int] = []
    manager = RuntimeFeatureManager(settings, max_workers=1)

    def factory():
        calls.append(1)
        entered.set()
        release.wait(1.0)
        return resource

    manager.register(
        FeatureSpec(
            name="toggle-during-load",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=factory,
            provided_services=(_Contract,),
        )
    )
    services().unregister(_Contract)
    try:
        future = manager.ensure_async("toggle-during-load")
        assert entered.wait(1.0)
        settings.set("ENABLED", False)
        settings.set("ENABLED", True)
        release.set()

        assert future.result(timeout=1.0) is resource
        _wait_until(lambda: manager.is_ready("toggle-during-load"))
        assert calls == [1]
        assert services().get(_Contract) is resource
    finally:
        release.set()
        manager.shutdown()
        services().unregister(_Contract)


def test_runtime_feature_shutdown_during_load_never_publishes_service() -> None:
    settings = SettingsRegistry({"ENABLED": True})
    entered = threading.Event()
    release = threading.Event()
    resource = _Implementation()
    manager = RuntimeFeatureManager(settings, max_workers=1)

    def factory():
        entered.set()
        release.wait(1.0)
        return resource

    manager.register(
        FeatureSpec(
            name="shutdown-during-load",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=factory,
            provided_services=(_Contract,),
        )
    )
    services().unregister(_Contract)
    future = manager.ensure_async("shutdown-during-load")
    assert entered.wait(1.0)
    manager.shutdown()
    release.set()

    with pytest.raises(RuntimeError, match="after shutdown"):
        future.result(timeout=1.0)
    assert resource.stopped.is_set()
    assert services().get_optional(_Contract) is None


def test_owned_service_restores_permanent_fallback_on_close() -> None:
    registry = ServiceRegistry()
    fallback = _Implementation("fallback")
    active = _Implementation("active")
    registry.register(_Contract, fallback)

    handle = registry.register_owned(_Contract, active, replace=True)
    assert registry.get(_Contract) is active

    assert handle.close() is True
    assert registry.get(_Contract) is fallback
