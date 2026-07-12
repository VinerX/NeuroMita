from __future__ import annotations

import unittest

from controllers.gui.app_shell_controller import AppShellController


class InstantVoiceMergeTests(unittest.TestCase):
    def test_merge_keeps_voice_prefix_and_appends_typed_input(self):
        merged, consumed = AppShellController._merge_text(
            "Во смотри",
            "https://example.com",
            merge_with_entry=True,
        )
        self.assertEqual(merged, "Во смотри\nhttps://example.com")
        self.assertTrue(consumed)

    def test_merge_can_be_disabled(self):
        merged, consumed = AppShellController._merge_text(
            "Во смотри",
            "https://example.com",
            merge_with_entry=False,
        )
        self.assertEqual(merged, "Во смотри")
        self.assertFalse(consumed)

    def test_blank_draft_does_not_add_extra_separator(self):
        merged, consumed = AppShellController._merge_text(
            "Во смотри",
            "   ",
            merge_with_entry=True,
        )
        self.assertEqual(merged, "Во смотри")
        self.assertFalse(consumed)


if __name__ == "__main__":
    unittest.main()
