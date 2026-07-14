from __future__ import annotations

import gc
import unittest
from unittest.mock import patch

from controllers.gui import async_runner


class _Owner:
    is_closed = False


class _ImmediateSupervisor:
    is_shutdown = False

    def start_thread(self, _owner, _name, target, *, allow_overlap=False):
        target()
        return object()


class AsyncRunnerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        async_runner._operations.clear()
        async_runner._tracked_owner_ids.clear()
        self.callbacks: list[object] = []
        self.supervisor = _ImmediateSupervisor()
        self.supervisor_patch = patch(
            "controllers.gui.async_runner.task_supervisor",
            new=lambda: self.supervisor,
        )
        self.dispatch_patch = patch(
            "controllers.gui.async_runner.dispatch_to_gui",
            new=lambda _target, callback: self.callbacks.append(callback) or True,
        )
        self.supervisor_patch.start()
        self.dispatch_patch.start()

    def tearDown(self) -> None:
        self.dispatch_patch.stop()
        self.supervisor_patch.stop()
        async_runner._operations.clear()
        async_runner._tracked_owner_ids.clear()

    def test_exclusive_slot_is_held_until_gui_callback_finishes(self) -> None:
        owner = _Owner()
        first = async_runner.run_async(
            owner,
            lambda: "first",
            lambda _result: None,
            name="install",
            policy="exclusive",
        )
        second = async_runner.run_async(
            owner,
            lambda: "second",
            lambda _result: None,
            name="install",
            policy="exclusive",
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(1, len(self.callbacks))
        self.callbacks.pop(0)()

        third = async_runner.run_async(
            owner,
            lambda: "third",
            lambda _result: None,
            name="install",
            policy="exclusive",
        )
        self.assertIsNotNone(third)

    def test_latest_operations_cleanup_after_out_of_order_callbacks(self) -> None:
        owner = _Owner()
        applied: list[str] = []
        async_runner.run_async(owner, lambda: "old", applied.append, name="refresh")
        async_runner.run_async(owner, lambda: "new", applied.append, name="refresh")

        old_callback, new_callback = self.callbacks
        new_callback()
        old_callback()

        self.assertEqual(["new"], applied)
        self.assertEqual({}, async_runner._operations)

    def test_owner_finalizer_purges_queued_operation_state(self) -> None:
        owner = _Owner()
        owner_id = id(owner)
        async_runner.run_async(owner, lambda: "value", lambda _result: None, name="refresh")
        self.assertTrue(any(key[0] == owner_id for key in async_runner._operations))

        del owner
        gc.collect()

        self.assertFalse(any(key[0] == owner_id for key in async_runner._operations))
        self.assertNotIn(owner_id, async_runner._tracked_owner_ids)


if __name__ == "__main__":
    unittest.main()