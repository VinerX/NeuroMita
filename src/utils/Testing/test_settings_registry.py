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
    assert registry.flush_notifications(1.0)
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
    assert registry.flush_notifications(1.0)
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


def test_broken_settings_observer_does_not_hide_following_observers():
    registry = SettingsRegistry({"key": 1})
    seen = []

    def broken(_change):
        raise RuntimeError("observer failed")

    registry.subscribe(broken, keys=("key",))
    registry.subscribe(seen.append, keys=("key",))

    assert registry.set("key", 2) is True
    assert registry.flush_notifications(1.0)
    assert [change.value for change in seen] == [2]


def test_broken_replay_observer_does_not_escape_subscribe():
    registry = SettingsRegistry({"key": 1})

    def broken(_change):
        raise RuntimeError("replay failed")

    subscription = registry.subscribe(broken, replay=True)
    subscription.close()


def test_settings_observer_never_blocks_mutating_thread():
    registry = SettingsRegistry({"key": 1})
    entered = __import__("threading").Event()
    release = __import__("threading").Event()

    def slow(_change):
        entered.set()
        release.wait(1.0)

    registry.subscribe(slow, keys=("key",))
    started = time.perf_counter()
    assert registry.set("key", 2) is True
    elapsed = time.perf_counter() - started
    assert elapsed < 0.1
    assert entered.wait(1.0)
    release.set()
    assert registry.flush_notifications(1.0)
    registry.close()


def test_settings_observer_order_follows_revision_order():
    registry = SettingsRegistry({"key": 0})
    seen = []
    registry.subscribe(lambda change: seen.append((change.revision, change.value)))
    registry.set("key", 1)
    registry.set("key", 2)
    registry.set("key", 3)
    assert registry.flush_notifications(1.0)
    assert seen == [(1, 1), (2, 2), (3, 3)]
    registry.close()


def test_slow_observer_does_not_block_independent_observer():
    import threading

    registry = SettingsRegistry({"key": 0})
    slow_entered = threading.Event()
    release_slow = threading.Event()
    fast_seen = threading.Event()

    def slow(_change):
        slow_entered.set()
        release_slow.wait(1.0)

    registry.subscribe(slow, keys=("key",))
    registry.subscribe(lambda _change: fast_seen.set(), keys=("key",))
    try:
        registry.set("key", 1)
        assert slow_entered.wait(1.0)
        assert fast_seen.wait(0.5)
    finally:
        release_slow.set()
        assert registry.flush_notifications(1.0)
        registry.close()
