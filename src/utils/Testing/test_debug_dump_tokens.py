from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from utils.context_token_stats import (
    classify_message_section as _classify_message_section,
    compute_token_usage as _compute_token_usage,
)


def _sys(text):
    return {"role": "system", "content": text}


class SectionClassifierTests(unittest.TestCase):
    def test_markers(self):
        self.assertEqual(_classify_message_section(_sys("[MiSide World State]\nfoo"), False), "MiSide World State")
        self.assertEqual(_classify_message_section(_sys("[System State]\nfoo"), False), "System State")
        self.assertEqual(_classify_message_section(_sys("<active_memory>\nN:1 ..."), False), "memories")
        self.assertEqual(_classify_message_section(_sys("<relevant_memories>\n..."), False), "memories")
        self.assertEqual(_classify_message_section(_sys("[Core Memory: obedience code]\n..."), False), "core memories")
        self.assertEqual(_classify_message_section(_sys("[Available Tools]\n- memory_search(...)"), False), "tools")
        self.assertEqual(_classify_message_section(_sys("You are a cute doll."), False), "character prompts")

    def test_user_vs_history(self):
        self.assertEqual(_classify_message_section({"role": "user", "content": "hi"}, True), "user input")
        self.assertEqual(_classify_message_section({"role": "user", "content": "old"}, False), "history")
        self.assertEqual(_classify_message_section({"role": "assistant", "content": "reply"}, False), "history")


class TokenUsageTests(unittest.TestCase):
    def test_usage_breakdown(self):
        messages = [
            _sys("You are Crazy Mita, a playful and controlling character."),
            _sys("<active_memory>\nN:1 [High] player likes cats</active_memory>"),
            _sys("[MiSide World State]\nThe player is in the kitchen.\n[/MiSide World State]"),
            _sys("[System State]\nYou currently receive only typed text from the Player."),
            {"role": "user", "content": "earlier message"},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": [{"type": "text", "text": "what is your name?"}]},
        ]
        usage = _compute_token_usage(messages)
        if not usage.get("available"):
            self.skipTest(f"tiktoken unavailable: {usage.get('note')}")

        self.assertTrue(usage.get("estimated"))
        self.assertEqual(len(usage["per_message"]), len(messages))
        self.assertGreater(usage["estimated_total"], 0)
        self.assertEqual(usage["estimated_total"], sum(usage["estimated_by_section"].values()))
        self.assertEqual(usage["estimated_total"], sum(m["estimated_tokens"] for m in usage["per_message"]))

        sections = usage["estimated_by_section"]
        for expected in ["character prompts", "memories", "MiSide World State", "System State", "history", "user input"]:
            self.assertIn(expected, sections, f"missing section {expected}")

    def test_graceful_when_empty(self):
        usage = _compute_token_usage([])
        self.assertFalse(usage["available"])


if __name__ == "__main__":
    unittest.main()
