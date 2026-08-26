from __future__ import annotations

import unittest

from controllers.gui.window_action_adapters import ShellActionsAdapter


class _ShellActionsTarget:
    def __init__(self) -> None:
        self.cancel_count = 0

    def cancel_active_generations(self) -> None:
        self.cancel_count += 1


class ShellActionsAdapterTests(unittest.TestCase):
    def test_cancel_active_generations_forwards_to_bound_target(self):
        target = _ShellActionsTarget()
        adapter = ShellActionsAdapter()
        adapter.bind(target)

        adapter.cancel_active_generations()

        self.assertEqual(target.cancel_count, 1)

    def test_cancel_active_generations_is_safe_before_binding(self):
        ShellActionsAdapter().cancel_active_generations()


if __name__ == "__main__":
    unittest.main()
