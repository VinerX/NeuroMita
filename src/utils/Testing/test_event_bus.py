from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.events import EventBus


class EventBusSyncTests(unittest.TestCase):
    def test_single_subscriber_none_result_is_preserved(self) -> None:
        bus = EventBus()
        try:
            bus.subscribe("ping", lambda _event: None, weak=False)
            self.assertEqual(bus.emit_and_wait("ping", timeout=0.2), [None])
        finally:
            bus.shutdown()

    def test_multiple_subscribers_return_in_subscription_order(self) -> None:
        bus = EventBus()
        try:
            def slow(_event):
                time.sleep(0.05)
                return "second"

            def fast(_event):
                return "first"

            bus.subscribe("ordered", fast, weak=False)
            bus.subscribe("ordered", slow, weak=False)

            self.assertEqual(bus.emit_and_wait("ordered", timeout=0.3), ["first", "second"])
        finally:
            bus.shutdown()

    def test_timed_out_subscribers_do_not_block_follow_up_calls(self) -> None:
        bus = EventBus()
        try:
            def slow(_event):
                time.sleep(0.2)
                return "slow"

            bus.subscribe("slow", slow, weak=False)
            for _ in range(30):
                self.assertEqual(bus.emit_and_wait("slow", timeout=0.01), [])

            bus.subscribe("fast", lambda _event: "ok", weak=False)
            self.assertEqual(bus.emit_and_wait("fast", timeout=0.2), ["ok"])
        finally:
            bus.shutdown()

    def test_nested_emit_and_wait_does_not_starve_sync_workers(self) -> None:
        bus = EventBus()
        try:
            bus.subscribe("inner", lambda _event: "inner", weak=False)

            def outer(_event):
                nested = bus.emit_and_wait("inner", timeout=0.3)
                return nested[0] if nested else "missing"

            for _ in range(30):
                bus.subscribe("outer", outer, weak=False)

            result = bus.emit_and_wait("outer", timeout=1.0)
            self.assertEqual(result, ["inner"] * 30)
        finally:
            bus.shutdown()


if __name__ == "__main__":
    unittest.main()
