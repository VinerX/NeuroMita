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

    def test_sync_emit_preserves_subscription_order(self) -> None:
        bus = EventBus()
        calls: list[str] = []
        try:
            bus.subscribe("ordered", lambda _event: calls.append("first"), weak=False)
            bus.subscribe("ordered", lambda _event: calls.append("second"), weak=False)

            result = bus.emit("ordered", {"value": 1}, sync=True)

            self.assertIsNone(result)
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
