from __future__ import annotations

import threading
import time

import pytest

from core.settings_registry import SettingsRegistry
from services.runtime_features import FeatureSpec, FeatureState, RuntimeFeatureManager


class _Resource:
    def __init__(self):
        self.stopped = threading.Event()

    def shutdown(self):
        self.stopped.set()


def _wait_until(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_disabled_feature_is_not_constructed_until_enabled():
    settings = SettingsRegistry({"ENABLED": False})
    calls = []
    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="feature",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: calls.append("created") or _Resource(),
        )
    )
    try:
        assert manager.start_enabled() == {}
        assert calls == []
        assert manager.state("feature") is FeatureState.DISABLED

        settings.set("ENABLED", True)
        _wait_until(lambda: manager.is_ready("feature"))
        assert calls == ["created"]
    finally:
        manager.shutdown()


def test_concurrent_ensure_deduplicates_factory():
    settings = SettingsRegistry()
    gate = threading.Event()
    calls = []
    manager = RuntimeFeatureManager(settings)

    def factory():
        calls.append(1)
        gate.wait(1.0)
        return _Resource()

    manager.register(
        FeatureSpec(name="feature", enabled=lambda _settings: False, factory=factory, startup=False)
    )
    try:
        first = manager.ensure_async("feature")
        second = manager.ensure_async("feature")
        assert first is second
        gate.set()
        assert first.result(timeout=2.0) is manager.get("feature")
        assert len(calls) == 1
    finally:
        manager.shutdown()


def test_explicit_ensure_keeps_on_demand_feature_ready_while_auto_disabled():
    settings = SettingsRegistry({"ENABLED": False})
    resource = _Resource()
    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="feature",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: resource,
            stop_when_disabled=False,
        )
    )
    try:
        assert manager.start_enabled() == {}
        assert manager.ensure("feature", timeout=2.0) is resource
        assert manager.is_ready("feature")

        settings.set("ENABLED", True)
        settings.set("ENABLED", False)
        assert settings.flush_notifications(1.0)

        assert manager.is_ready("feature")
        assert manager.get("feature") is resource
        assert not resource.stopped.is_set()
    finally:
        manager.shutdown()


def test_enabled_feature_stops_when_setting_is_disabled():
    settings = SettingsRegistry({"ENABLED": True})
    resource = _Resource()
    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="feature",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: resource,
        )
    )
    try:
        manager.start_enabled()["feature"].result(timeout=2.0)
        settings.set("ENABLED", False)
        assert resource.stopped.wait(2.0)
        _wait_until(lambda: manager.state("feature") is FeatureState.DISABLED)
        assert manager.get("feature") is None
    finally:
        manager.shutdown()


def test_missing_required_module_skips_factory():
    settings = SettingsRegistry({"ENABLED": True})
    calls = []
    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="feature",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: calls.append(1),
            required_modules=("__neuromita_definitely_missing_package__",),
        )
    )
    try:
        with pytest.raises(RuntimeError, match="missing modules"):
            manager.ensure("feature", timeout=1.0)
        assert calls == []
        assert manager.state("feature") is FeatureState.UNAVAILABLE
    finally:
        manager.shutdown()


def test_dependency_dag_starts_without_nested_executor_waits():
    settings = SettingsRegistry({"ENABLED": True})
    order = []
    manager = RuntimeFeatureManager(settings, max_workers=1)
    manager.register(
        FeatureSpec(
            name="base",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: order.append("base") or _Resource(),
            priority=20,
        )
    )
    manager.register(
        FeatureSpec(
            name="dependent",
            enabled=lambda values: values.get("ENABLED", False),
            setting_keys=("ENABLED",),
            factory=lambda: order.append("dependent") or _Resource(),
            depends_on=("base",),
            priority=10,
        )
    )
    try:
        manager.ensure("dependent", timeout=2.0)
        assert order == ["base", "dependent"]
        assert manager.is_ready("base")
        assert manager.is_ready("dependent")
    finally:
        manager.shutdown()
        settings.close()


def test_dependency_cycle_is_rejected_before_factory_runs():
    settings = SettingsRegistry()
    calls = []
    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="a",
            enabled=lambda _settings: True,
            factory=lambda: calls.append("a"),
            depends_on=("b",),
        )
    )
    manager.register(
        FeatureSpec(
            name="b",
            enabled=lambda _settings: True,
            factory=lambda: calls.append("b"),
            depends_on=("a",),
        )
    )
    try:
        with pytest.raises(RuntimeError, match="cycle"):
            manager.ensure("a", timeout=1.0)
        assert calls == []
    finally:
        manager.shutdown()
        settings.close()


def test_disabling_dependency_stops_dependent_first():
    settings = SettingsRegistry({"BASE": True, "CHILD": True})
    stopped = []

    class Resource:
        def __init__(self, name):
            self.name = name

        def shutdown(self):
            stopped.append(self.name)

    manager = RuntimeFeatureManager(settings)
    manager.register(
        FeatureSpec(
            name="base",
            enabled=lambda values: values.get("BASE", False),
            setting_keys=("BASE",),
            factory=lambda: Resource("base"),
        )
    )
    manager.register(
        FeatureSpec(
            name="child",
            enabled=lambda values: values.get("CHILD", False),
            setting_keys=("CHILD",),
            factory=lambda: Resource("child"),
            depends_on=("base",),
        )
    )
    try:
        manager.ensure("child", timeout=2.0)
        settings.set("BASE", False)
        assert settings.flush_notifications(1.0)
        _wait_until(lambda: manager.state("base") is FeatureState.DISABLED)
        _wait_until(lambda: manager.state("child") is FeatureState.DISABLED)
        assert stopped[:2] == ["child", "base"]
    finally:
        manager.shutdown()
        settings.close()
