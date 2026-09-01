from __future__ import annotations

from types import MethodType, SimpleNamespace

import ui.widgets.dialogue_runtime_inspector as inspector_module
from ui.widgets.dialogue_runtime_inspector import DialogueRuntimeInspector


class _Check:
    def __init__(self, checked: bool) -> None:
        self.checked = checked
        self.enabled = True

    def isChecked(self) -> bool:
        return self.checked

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class _SignalBlocker:
    def __init__(self, _widget) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass


def _inspector(**values):
    inspector = SimpleNamespace(
        _settings_snapshot=dict(values),
        _setting_updater=None,
    )
    inspector._dialogue_setting = MethodType(
        DialogueRuntimeInspector._dialogue_setting,
        inspector,
    )
    inspector._set_dialogue_setting = MethodType(
        DialogueRuntimeInspector._set_dialogue_setting,
        inspector,
    )
    return inspector


def test_target_routing_checkbox_updates_through_sandbox_intent() -> None:
    updates = []
    inspector = _inspector(MITA_DIALOGUE_TARGET_ROUTING=True)
    inspector._setting_updater = lambda key, value: updates.append((key, value))
    inspector._target_routing_check = _Check(False)

    DialogueRuntimeInspector._update_global_target_routing(inspector)

    assert updates == [("MITA_DIALOGUE_TARGET_ROUTING", False)]


def test_auto_dialogue_checkbox_controls_target_checkbox_availability() -> None:
    updates = []
    target_check = _Check(True)
    inspector = _inspector(MITA_DIALOGUE_AUTO=True)
    inspector._setting_updater = lambda key, value: updates.append((key, value))
    inspector._dialogue_enabled_check = _Check(False)
    inspector._target_routing_check = target_check

    DialogueRuntimeInspector._update_global_dialogue_enabled(inspector)

    assert updates == [("MITA_DIALOGUE_AUTO", False)]
    assert target_check.enabled is False


def test_global_checkboxes_follow_sandbox_settings_state(monkeypatch) -> None:
    monkeypatch.setattr(inspector_module, "QSignalBlocker", _SignalBlocker)
    inspector = _inspector()
    inspector._dialogue_enabled_check = _Check(False)
    inspector._target_routing_check = _Check(False)

    DialogueRuntimeInspector.sync_global_settings(
        inspector,
        {
            "MITA_DIALOGUE_AUTO": True,
            "MITA_DIALOGUE_TARGET_ROUTING": True,
        },
    )

    assert inspector._dialogue_enabled_check.checked is True
    assert inspector._target_routing_check.checked is True
    assert inspector._target_routing_check.enabled is True
