from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ui.windows.app_window_base import AppWindowBase


class InstantVoiceMergeTests(unittest.TestCase):
    def test_merge_keeps_voice_prefix_and_appends_typed_input(self):
        merged, consumed = AppWindowBase._merge_explicit_and_entry_text(
            "Во смотри",
            "https://example.com",
            merge_with_entry=True,
        )

        self.assertEqual(merged, "Во смотри\nhttps://example.com")
        self.assertTrue(consumed)

    def test_merge_can_be_disabled(self):
        merged, consumed = AppWindowBase._merge_explicit_and_entry_text(
            "Во смотри",
            "https://example.com",
            merge_with_entry=False,
        )

        self.assertEqual(merged, "Во смотри")
        self.assertFalse(consumed)

    def test_blank_draft_does_not_add_extra_separator(self):
        merged, consumed = AppWindowBase._merge_explicit_and_entry_text(
            "Во смотри",
            "   ",
            merge_with_entry=True,
        )

        self.assertEqual(merged, "Во смотри")
        self.assertFalse(consumed)


if __name__ == "__main__":
    unittest.main()
