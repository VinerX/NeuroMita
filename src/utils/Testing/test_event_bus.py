from __future__ import annotations

import gc
import threading
import time
import unittest

from core.events import EventBus


class EventBusNotificationTests(unittest.TestCase):
    def test_sync_response_api_is_not_exposed(self) -> None:
        bus = EventBus()
        try:
            legacy_method_name = "emit" + "_and_wait"
            self.assertFalse(hasattr(bus, legacy_method_name))
        finally:
            bus.shutdown()

    def test_legacy_sync_flag_routes_to_ordered_channel(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        try:
            bus.subscribe("ordered", lambda _event: calls.append("first"), weak=False)
            bus.subscribe("ordered", lambda _event: calls.append("second"), weak=False)

            result = bus.emit("ordered", {"value": 1}, sync=True)

            self.assertIsNone(result)
            self.assertTrue(bus.flush(1.0))
            self.assertEqual(calls, ["first", "second"])
        finally:
            bus.shutdown()

    def test_handler_failure_does_not_skip_remaining_subscribers(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        def broken(_event) -> None:
            calls.append("broken")
            raise RuntimeError("boom")

        try:
            bus.subscribe("event", broken, weak=False)
            bus.subscribe("event", lambda _event: calls.append("healthy"), weak=False)

            bus.emit("event", sync=True)
            self.assertTrue(bus.flush(1.0))

            self.assertEqual(calls, ["broken", "healthy"])
        finally:
            bus.shutdown()

    def test_async_emit_delivers_without_blocking_caller(self) -> None:
        bus = EventBus()
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def subscriber(_event) -> None:
            started.set()
            release.wait(1.0)
            completed.set()

        try:
            bus.subscribe("async", subscriber, weak=False)
            before = time.perf_counter()
            bus.emit("async")
            elapsed = time.perf_counter() - before

            self.assertLess(elapsed, 0.1)
            self.assertTrue(started.wait(1.0))
            self.assertFalse(completed.is_set())
            release.set()
            self.assertTrue(completed.wait(1.0))
        finally:
            release.set()
            bus.shutdown()

    def test_ordered_queued_event_runs_subscribers_sequentially(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        finished = threading.Event()

        def first(_event) -> None:
            calls.append("first:start")
            time.sleep(0.02)
            calls.append("first:end")

        def second(_event) -> None:
            calls.append("second")
            finished.set()

        try:
            bus.subscribe("create_task", first, weak=False)
            bus.subscribe("create_task", second, weak=False)
            bus.emit("create_task")

            self.assertTrue(finished.wait(1.0))
            self.assertEqual(calls, ["first:start", "first:end", "second"])
        finally:
            bus.shutdown()

    def test_unsubscribe_accepts_a_fresh_bound_method_object(self) -> None:
        bus = EventBus()

        class Receiver:
            def __init__(self) -> None:
                self.calls = 0

            def on_event(self, _event) -> None:
                self.calls += 1

        receiver = Receiver()
        try:
            bus.subscribe("event", receiver.on_event, weak=False)
            bus.unsubscribe("event", receiver.on_event)
            bus.emit("event", sync=True)
            self.assertEqual(receiver.calls, 0)
        finally:
            bus.shutdown()

    def test_dead_weak_subscriber_is_removed(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        class Receiver:
            def on_event(self, _event) -> None:
                calls.append("called")

        receiver = Receiver()
        bus.subscribe("event", receiver.on_event)
        del receiver
        gc.collect()

        try:
            bus.emit("event", sync=True)
            self.assertTrue(bus.flush(1.0))
            self.assertEqual(calls, [])
        finally:
            bus.shutdown()

    def test_emit_after_shutdown_is_a_noop(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        bus.subscribe("late", lambda _event: calls.append("called"), weak=False)
        bus.shutdown()

        bus.emit("late", sync=True)

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()


def test_weak_bound_method_stays_subscribed_while_receiver_is_alive() -> None:
    bus = EventBus()

    class Receiver:
        def __init__(self) -> None:
            self.calls = 0

        def on_event(self, _event) -> None:
            self.calls += 1

    receiver = Receiver()
    try:
        bus.subscribe("event", receiver.on_event)
        gc.collect()
        bus.emit("event", sync=True)
        assert bus.flush(1.0)
        assert receiver.calls == 1
    finally:
        bus.shutdown()


def test_subscription_handle_does_not_keep_weak_receiver_alive() -> None:
    bus = EventBus()
    calls: list[str] = []

    class Receiver:
        def on_event(self, _event) -> None:
            calls.append("called")

    receiver = Receiver()
    handle = bus.subscribe("event", receiver.on_event)
    del receiver
    gc.collect()
    try:
        bus.emit("event", sync=True)
        assert bus.flush(1.0)
        assert calls == []
        handle.close()
    finally:
        bus.shutdown()


def test_duplicate_subscription_is_delivered_once() -> None:
    bus = EventBus()
    calls: list[str] = []

    def callback(_event) -> None:
        calls.append("called")

    try:
        bus.subscribe("event", callback, weak=False)
        bus.subscribe("event", callback, weak=False)
        bus.emit("event", sync=True)
        assert bus.flush(1.0)
        assert calls == ["called"]
    finally:
        bus.shutdown()


def test_subscription_handle_unsubscribes_strong_callback() -> None:
    bus = EventBus()
    calls: list[str] = []

    def callback(_event) -> None:
        calls.append("called")

    try:
        handle = bus.subscribe("event", callback, weak=False)
        handle.close()
        handle.close()
        bus.emit("event", sync=True)
        assert calls == []
    finally:
        bus.shutdown()


def test_unsubscribe_owner_removes_strong_bound_methods() -> None:
    bus = EventBus()

    class Receiver:
        def __init__(self) -> None:
            self.calls = 0

        def first(self, _event) -> None:
            self.calls += 1

        def second(self, _event) -> None:
            self.calls += 10

    receiver = Receiver()
    try:
        bus.subscribe("first", receiver.first, weak=False)
        bus.subscribe("second", receiver.second, weak=False)
        assert bus.unsubscribe_owner(receiver) == 2
        bus.emit("first", sync=True)
        bus.emit("second", sync=True)
        assert receiver.calls == 0
    finally:
        bus.shutdown()


def test_try_emit_reports_rejection_after_shutdown() -> None:
    bus = EventBus()
    bus.shutdown()
    assert bus.try_emit("late") is False


def test_legacy_sync_flag_never_runs_subscriber_inline() -> None:
    bus = EventBus()
    entered = threading.Event()
    release = threading.Event()

    def slow(_event) -> None:
        entered.set()
        release.wait(1.0)

    try:
        bus.subscribe("ordered", slow, weak=False)
        started = time.perf_counter()
        bus.emit("ordered", sync=True)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.1
        assert entered.wait(1.0)
    finally:
        release.set()
        bus.shutdown()


def test_query_names_are_rejected_by_fact_bus() -> None:
    bus = EventBus()
    try:
        import pytest
        with pytest.raises(ValueError, match="query"):
            bus.subscribe("get_debug_info", lambda _event: None, weak=False)
        with pytest.raises(ValueError, match="query"):
            bus.emit("ai_get_engine")
    finally:
        bus.shutdown()


def test_best_effort_saturation_does_not_execute_inline(monkeypatch) -> None:
    from core.events import EventDelivery
    from core.executors import PoolSaturated, Pools, executors

    bus = EventBus()
    calls: list[str] = []
    pool = executors().pool(Pools.EVENT_BUS)
    monkeypatch.setattr(
        pool,
        "try_submit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PoolSaturated(Pools.EVENT_BUS, 1)
        ),
    )
    try:
        bus.subscribe("telemetry", lambda _event: calls.append("called"), weak=False)
        assert bus.try_emit(
            "telemetry", delivery=EventDelivery.BEST_EFFORT
        ) is False
        assert calls == []
    finally:
        bus.shutdown()


def test_event_admission_is_atomic_for_all_subscribers(monkeypatch) -> None:
    bus = EventBus()
    calls: list[str] = []
    submissions: list[tuple] = []

    def fake_submit(*args, **kwargs):
        submissions.append((args, kwargs))
        return False

    monkeypatch.setattr(bus._critical, "submit", fake_submit)
    try:
        bus.subscribe("fact", lambda _event: calls.append("first"), weak=False)
        bus.subscribe("fact", lambda _event: calls.append("second"), weak=False)
        assert bus.try_emit("fact") is False
        assert len(submissions) == 1
        assert calls == []
    finally:
        bus.shutdown()


def test_install_commands_are_isolated_from_blocked_critical_lane() -> None:
    from core.events import EventDelivery

    bus = EventBus()
    critical_started = threading.Event()
    release_critical = threading.Event()
    command_delivered = threading.Event()

    def block_critical(_event) -> None:
        critical_started.set()
        release_critical.wait(2.0)

    try:
        bus.subscribe("blocked_fact", block_critical, weak=False)
        bus.subscribe(
            "installable_install",
            lambda _event: command_delivered.set(),
            weak=False,
        )

        assert bus.try_emit(
            "blocked_fact",
            delivery=EventDelivery.CRITICAL,
        )
        assert critical_started.wait(1.0)

        assert bus.try_emit("installable_install", {"component_id": "tts:test"})
        assert command_delivered.wait(1.0)
    finally:
        release_critical.set()
        bus.shutdown()


def test_install_command_channel_rejection_is_reported(monkeypatch) -> None:
    bus = EventBus()
    calls: list[str] = []

    monkeypatch.setattr(bus._commands, "submit", lambda *_args, **_kwargs: False)
    try:
        bus.subscribe(
            "run_install_with_ui",
            lambda _event: calls.append("called"),
            weak=False,
        )
        assert bus.try_emit("run_install_with_ui", {}) is False
        assert calls == []
    finally:
        bus.shutdown()


def test_serial_dispatcher_close_discards_unbounded_backlog_after_timeout() -> None:
    from core.serial_dispatcher import SerialDispatcher

    entered = threading.Event()
    release = threading.Event()
    second_called = threading.Event()
    dispatcher = SerialDispatcher(
        "close-timeout-test",
        lanes=1,
        capacity_per_lane=0,
    )

    def blocking() -> None:
        entered.set()
        release.wait(2.0)

    assert dispatcher.submit(blocking, description="blocking")
    assert entered.wait(1.0)
    assert dispatcher.submit(second_called.set, description="must-be-discarded")

    dispatcher.close(drain=True, timeout=0.01)
    release.set()

    deadline = time.monotonic() + 1.0
    while dispatcher.pending and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not second_called.is_set()
    assert dispatcher.pending == 0
