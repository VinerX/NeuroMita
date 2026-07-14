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


if __name__ == "__main__":
    unittest.main()
