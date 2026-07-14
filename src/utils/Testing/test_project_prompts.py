from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPTS = PROJECT_ROOT / "extra" / "Prompts"


class ProjectInfoTests(unittest.TestCase):
    def test_project_info_has_brief_credits(self):
        text = (PROMPTS / "Common" / "ProjectInfo.txt").read_text(encoding="utf-8")
        for name in ["NeuroMita", "VinerX", "Atm4x", "AIHASTO", "MiSide"]:
            self.assertIn(name, text)
        self.assertIn("Mention project credits only when the Player directly asks", text)

    def test_project_info_has_no_code_23(self):
        text = (PROMPTS / "Common" / "ProjectInfo.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("code 23", text)
        self.assertNotIn("код 23", text)
        self.assertNotIn(" 23", text)

    def test_none_txt_is_gone_and_unreferenced(self):
        self.assertFalse((PROMPTS / "Common" / "None.txt").exists(),
                         "Common/None.txt must be deleted")
        offenders = []
        for path in PROMPTS.rglob("*.txt"):
            try:
                if "None.txt" in path.read_text(encoding="utf-8", errors="ignore"):
                    offenders.append(str(path))
            except Exception:
                pass
        self.assertEqual(offenders, [], f"None.txt still referenced: {offenders}")

    def test_credits_do_not_mention_code_23(self):
        wk = (PROMPTS / "Common" / "world_knowledge.script").read_text(encoding="utf-8").lower()
        # The credits block must not tie developers to the code 23 easter egg.
        self.assertNotIn("code 23", wk)
        self.assertNotIn("код 23", wk)

    def test_reasoning_gated_in_text_schema(self):
        script = (PROMPTS / "Structural" / "response_format_json.script").read_text(encoding="utf-8")
        # The text-format instruction only describes the reasoning field inside
        # the SCHEMA_REASONING_ENABLED conditional.
        self.assertIn("IF SCHEMA_REASONING_ENABLED == True THEN", script)
        else_idx = script.index("ELSE", script.index("IF SCHEMA_REASONING_ENABLED == True THEN"))
        endif_idx = script.index("ENDIF", else_idx)
        else_block = script[else_idx:endif_idx]
        self.assertNotIn("reasoning", else_block.lower())


class ContextBudgetTests(unittest.TestCase):
    """Guard against large accidental duplication / bloat after the refactor."""

    def _tokens(self, text):
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model("gpt-4o-mini")
            return len(enc.encode(text))
        except Exception:
            return None

    def test_crazy_static_blocks_within_budget(self):
        crazy = PROMPTS / "Crazy" / "Default"
        blocks = [
            crazy / "Main" / "common_behavior.txt",
            crazy / "Main" / "available_actions.txt",
            crazy / "Main" / "player.txt",
            PROMPTS / "Common" / "ProjectInfo.txt",
            PROMPTS / "Common" / "Security.txt",
            PROMPTS / "Common" / "Dialogue.txt",
        ]
        combined = "\n".join(p.read_text(encoding="utf-8") for p in blocks if p.exists())
        toks = self._tokens(combined)
        if toks is None:
            self.skipTest("tiktoken unavailable")
        # Generous ceiling — a few service tokens won't trip it, but a whole
        # block duplicated into the assembly would.
        self.assertLess(toks, 6000, f"static Crazy blocks unexpectedly large: {toks} tokens")

    def test_split_did_not_duplicate_personality_into_actions(self):
        crazy = PROMPTS / "Crazy" / "Default" / "Main"
        behavior = (crazy / "common_behavior.txt").read_text(encoding="utf-8")
        actions = (crazy / "available_actions.txt").read_text(encoding="utf-8")
        # The distinctive personality opener must live in exactly one file.
        marker = "ты ведешь светскую беседу"
        self.assertIn(marker, behavior.lower())
        self.assertNotIn(marker, actions.lower())


if __name__ == "__main__":
    unittest.main()
