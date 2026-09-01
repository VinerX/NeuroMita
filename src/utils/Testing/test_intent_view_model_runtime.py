from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_SRC_ROOT = Path(__file__).resolve().parents[2]


class _BoundSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback, *_args, **_kwargs) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback) -> None:
        self._callbacks.remove(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in tuple(self._callbacks):
            callback(*args, **kwargs)


class _SignalDescriptor:
    def __init__(self, *_args, **_kwargs) -> None:
        self._name = ""

    def __set_name__(self, _owner, name: str) -> None:
        self._name = f"__signal_{name}"

    def __get__(self, instance, _owner):
        if instance is None:
            return self
        signal = instance.__dict__.get(self._name)
        if signal is None:
            signal = _BoundSignal()
            instance.__dict__[self._name] = signal
        return signal


class _QObject:
    destroyed = _SignalDescriptor(object)

    def __init__(self, parent=None) -> None:
        self._parent = parent

    def setParent(self, parent) -> None:
        self._parent = parent


def _slot(*_args, **_kwargs):
    def decorate(function):
        return function

    return decorate


class _Supervisor:
    def __init__(self) -> None:
        self.pending: list = []
        self.fail_start = False

    def start_thread(self, _owner, _name, target, **_kwargs) -> None:
        if self.fail_start:
            raise RuntimeError("thread start failed")
        self.pending.append(target)

    def cancel_owner(self, _owner, timeout=0.0) -> None:
        _ = timeout


def _fake_modules(supervisor: _Supervisor | None = None) -> dict[str, types.ModuleType]:
    qt_core = types.ModuleType("PyQt6.QtCore")
    qt_core.QObject = _QObject
    qt_core.Qt = SimpleNamespace(ConnectionType=SimpleNamespace(QueuedConnection=1))
    qt_core.pyqtSignal = _SignalDescriptor
    qt_core.pyqtSlot = _slot

    pyqt = types.ModuleType("PyQt6")
    pyqt.__path__ = []
    pyqt.QtCore = qt_core

    event_bus = SimpleNamespace(unsubscribe_owner=lambda _owner: None)
    events = types.ModuleType("core.events")
    events.get_event_bus = lambda: event_bus

    task_module = types.ModuleType("core.task_supervisor")
    task_module.task_supervisor = lambda: supervisor

    logger_module = types.ModuleType("main_logger")
    logger_module.logger = SimpleNamespace(
        debug=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )

    return {
        "PyQt6": pyqt,
        "PyQt6.QtCore": qt_core,
        "core.events": events,
        "core.task_supervisor": task_module,
        "main_logger": logger_module,
    }


def _load_module(name: str, relative_path: str, fake_modules: dict[str, types.ModuleType]):
    path = _SRC_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, fake_modules):
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
    return module


@dataclass(frozen=True)
class _State:
    value: int = 0


class IntentViewModelRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supervisor = _Supervisor()
        self.module = _load_module(
            "_intent_view_model_runtime_test",
            "controllers/gui/intent_view_model.py",
            _fake_modules(self.supervisor),
        )
        self.view_model = self.module.IntentViewModel(_State())

    def test_latest_wins_when_results_finish_out_of_order(self) -> None:
        applied: list[str] = []
        self.view_model.run_latest("refresh", lambda: "old", applied.append)
        self.view_model.run_latest("refresh", lambda: "new", applied.append)

        old, new = self.supervisor.pending
        old()
        new()

        self.assertEqual(["new"], applied)

    def test_coalesced_refresh_runs_once_more_and_discards_stale_result(self) -> None:
        applied: list[str] = []
        self.assertTrue(
            self.view_model.run_coalesced("refresh", lambda: "old", applied.append)
        )
        self.assertFalse(
            self.view_model.run_coalesced("refresh", lambda: "new", applied.append)
        )

        self.supervisor.pending.pop(0)()
        self.assertEqual([], applied)
        self.assertEqual(1, len(self.supervisor.pending))

        self.supervisor.pending.pop(0)()
        self.assertEqual(["new"], applied)

    def test_close_rejects_late_result(self) -> None:
        applied: list[str] = []
        self.view_model.run_latest("refresh", lambda: "late", applied.append)
        self.view_model.close()

        self.supervisor.pending.pop(0)()

        self.assertEqual([], applied)

    def test_exclusive_rejects_duplicate_without_throwing(self) -> None:
        self.assertTrue(self.view_model.run_exclusive("install", lambda: "ok"))
        self.assertFalse(self.view_model.run_exclusive("install", lambda: "duplicate"))

    def test_failed_thread_start_does_not_leave_exclusive_operation_stuck(self) -> None:
        self.supervisor.fail_start = True
        self.assertFalse(self.view_model.run_exclusive("install", lambda: "never"))

        self.supervisor.fail_start = False
        self.assertTrue(self.view_model.run_exclusive("install", lambda: "ok"))


class _Subscription:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _SettingsService:
    def __init__(self) -> None:
        self.values = {"VALUE": 1}
        self.fail_writes = False
        self.updates: list[tuple[str, object]] = []
        self.callback = None

    def snapshot(self):
        return dict(self.values)

    def subscribe(self, callback):
        self.callback = callback
        return _Subscription()

    def update(self, key: str, value) -> None:
        if self.fail_writes:
            raise RuntimeError("write failed")
        self.values[key] = value
        self.updates.append((key, value))


class SettingsBindingRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_registry = types.ModuleType("core.settings_registry")

        @dataclass(frozen=True)
        class SettingChange:
            key: str
            value: object
            source: str = "update"

        settings_registry.SettingChange = SettingChange
        fake_modules = _fake_modules(_Supervisor())
        fake_modules["core.settings_registry"] = settings_registry
        self.module = _load_module(
            "_settings_binding_runtime_test",
            "ui/settings/settings_binding.py",
            fake_modules,
        )
        self.service = _SettingsService()
        self.binding = self.module.QtSettingsViewModel(self.service)

    def test_failed_write_rolls_widget_back_to_previous_value(self) -> None:
        owner = _QObject()
        changed = _BoundSignal()
        widget_value = {"value": 2}
        applied: list[object] = []
        self.binding.bind_two_way(
            "VALUE",
            owner,
            changed,
            lambda: widget_value["value"],
            applied.append,
        )
        self.assertEqual([1], applied)

        self.service.fail_writes = True
        changed.emit()

        self.assertEqual(1, self.binding.get("VALUE"))
        self.assertEqual(1, applied[-1])

    def test_unbind_disconnects_widget_write_signal(self) -> None:
        owner = _QObject()
        changed = _BoundSignal()
        widget_value = {"value": 2}
        self.binding.bind_two_way(
            "VALUE",
            owner,
            changed,
            lambda: widget_value["value"],
            lambda _value: None,
        )

        self.binding.unbind_owner(owner)
        changed.emit()

        self.assertEqual([], self.service.updates)


if __name__ == "__main__":
    unittest.main()