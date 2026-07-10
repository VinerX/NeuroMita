from __future__ import annotations

import json
import time
from pathlib import Path

from core.settings_registry import SettingsRegistry
from managers.settings_manager import SettingsManager


def test_registry_snapshot_subscription_and_revision():
    registry = SettingsRegistry({"alpha": 1, "beta": 2})
    changes = []
    subscription = registry.subscribe(changes.append, keys=("alpha",))

    assert registry.snapshot() == {"alpha": 1, "beta": 2}
    assert registry.require("alpha") == 1
    assert registry.set("alpha", 3, source="test") is True
    assert registry.set("alpha", 3, source="test") is False
    assert registry.set("beta", 4, source="test") is True

    assert registry.revision == 2
    assert [(item.key, item.previous, item.value, item.source) for item in changes] == [
        ("alpha", 1, 3, "test")
    ]

    subscription.close()
    registry.set("alpha", 5)
    assert len(changes) == 1


def test_registry_update_many_is_immediately_visible():
    registry = SettingsRegistry({"a": 1})
    seen = []
    registry.subscribe(seen.append)

    changes = registry.update_many({"a": 2, "b": 3}, source="bulk")

    assert registry.snapshot(("a", "b")) == {"a": 2, "b": 3}
    assert [item.key for item in changes] == ["a", "b"]
    assert [item.key for item in seen] == ["a", "b"]


def test_settings_manager_persists_registry_changes(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"initial": true}', encoding="utf-8")

    previous = SettingsManager.instance
    manager = SettingsManager(str(path))
    manager.SAVE_DEBOUNCE_SEC = 0.02
    try:
        manager.set("answer", 42, source="test")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("answer") == 42:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("settings writer did not persist registry change")

        assert manager.snapshot()["answer"] == 42
    finally:
        manager.close()
        SettingsManager.instance = previous
