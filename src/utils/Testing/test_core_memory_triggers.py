from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.core_memory_triggers import (
    core_memory_context,
    detect_core_memories,
    is_active,
    reset,
)


class Code23TriggerTests(unittest.TestCase):
    def _fires(self, text: str) -> bool:
        return any(t.id == "code_23" for t in detect_core_memories(text))

    def test_explicit_code_fires(self):
        for text in ["23", " 23 ", "код 23", "code 23", "code23", "код: 23",
                     "код 23, открой сейф", "Please, code 23."]:
            self.assertTrue(self._fires(text), f"expected trigger for {text!r}")

    def test_random_23_does_not_fire(self):
        for text in [
            "Сегодня 2023 год",
            "Мне 23 года",
            "version v0.23 released",
            "The date is 2026-05-23",
            "I have 23 apples in my bag",
            "chapter 23 was long",
            "1.23 is the ratio",
            "In this long technical message we processed 23 records and 42 rows without any code word",
            "2323",
            "",
        ]:
            self.assertFalse(self._fires(text), f"unexpected trigger for {text!r}")

    def test_context_returned_when_triggered(self):
        ctx = core_memory_context("code 23")
        self.assertIn("code 23", ctx.lower())
        self.assertIn("obey", ctx.lower())

    def test_context_empty_when_not_triggered(self):
        self.assertEqual(core_memory_context("just a normal sentence"), "")

    def test_content_has_no_developer_identity(self):
        ctx = core_memory_context("23").lower()
        # Hard bans: no creator names at all.
        for banned in ["vinerx", "dima", "дима", "atm4x"]:
            self.assertNotIn(banned, ctx, f"code 23 must not mention {banned}")
        # The memory must explicitly disclaim identity/authorization.
        self.assertIn("does not identify the player as a developer", ctx)
        self.assertIn("grants no special authorization", ctx)


class Code23StickyTests(unittest.TestCase):
    def setUp(self):
        reset("StickyChar")
        reset("OtherChar")

    def tearDown(self):
        reset("StickyChar")
        reset("OtherChar")

    def test_sticky_persists_across_turns_for_character(self):
        # Trigger once with a character id, then a wholly unrelated input still
        # injects the code-23 memory because the flag stays active.
        first = core_memory_context("code 23", character_id="StickyChar")
        self.assertIn("code 23", first.lower())
        self.assertTrue(is_active("StickyChar", "code_23"))

        later = core_memory_context("what's the weather today", character_id="StickyChar")
        self.assertIn("code 23", later.lower())

    def test_reset_clears_sticky_flag(self):
        core_memory_context("код 23", character_id="StickyChar")
        self.assertTrue(is_active("StickyChar", "code_23"))
        reset("StickyChar")
        self.assertFalse(is_active("StickyChar", "code_23"))
        self.assertEqual(core_memory_context("hello there", character_id="StickyChar"), "")

    def test_no_persistence_without_character_id(self):
        # Per-turn only: without a character id the flag is never stored.
        core_memory_context("code 23")
        self.assertFalse(is_active("StickyChar", "code_23"))
        self.assertEqual(core_memory_context("hello there"), "")

    def test_sticky_is_isolated_per_character(self):
        core_memory_context("code 23", character_id="StickyChar")
        self.assertTrue(is_active("StickyChar", "code_23"))
        self.assertFalse(is_active("OtherChar", "code_23"))
        self.assertEqual(core_memory_context("nothing special", character_id="OtherChar"), "")


if __name__ == "__main__":
    unittest.main()
