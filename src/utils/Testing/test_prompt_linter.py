from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from utils.prompt_linter import lint_prompts


class PromptLinterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nm_lint_"))

    def _write(self, rel, content):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _kinds(self, warnings):
        return {w.kind for w in warnings}

    def test_missing_include(self):
        self._write("Char/Default/main_template.txt", "[<Main/missing.txt>]\n")
        warnings = lint_prompts(self.tmp)
        self.assertIn("missing-include", self._kinds(warnings))

    def test_cyclic_include(self):
        self._write("Char/Default/main_template.txt", "[<a.txt>]\n")
        self._write("Char/Default/a.txt", "[<b.txt>]\n")
        self._write("Char/Default/b.txt", "[<a.txt>]\n")
        warnings = lint_prompts(self.tmp)
        self.assertIn("cyclic-include", self._kinds(warnings))

    def test_none_txt_reinclusion(self):
        self._write("Char/Default/main_template.txt", "[<../../Common/None.txt>]\n")
        self._write("Common/None.txt", "x")
        warnings = lint_prompts(self.tmp)
        self.assertIn("none-txt-include", self._kinds(warnings))

    def test_intents_mention_requires_prompt_set_opt_in(self):
        self._write("Char/Default/main_template.txt", "[<response.txt>]\n")
        self._write("Char/Default/response.txt", "You may emit intents in a segment.\n")
        warnings = lint_prompts(self.tmp)
        self.assertIn("intents-mention", self._kinds(warnings))

        self._write(
            "Char/Default/main_template.txt",
            "support_intents=True\n[<response.txt>]\n",
        )
        warnings2 = lint_prompts(self.tmp)
        self.assertNotIn("intents-mention", self._kinds(warnings2))

    def test_deprecated_item_in_structural(self):
        self._write("Char/Default/Structural/fmt.txt", "Use item|priority|content here.\n")
        warnings = lint_prompts(self.tmp)
        self.assertIn("deprecated-item", self._kinds(warnings))

    def test_conflicting_length_rules(self):
        self._write("Char/Default/rules.txt",
                    "Keep replies 25-70 words total.\nBut also 100-200 words sometimes.\n")
        warnings = lint_prompts(self.tmp)
        self.assertIn("conflicting-length", self._kinds(warnings))

    def test_clean_tree_has_no_warnings(self):
        self._write("Char/Default/main_template.txt", "[<Main/ok.txt>]\n")
        self._write("Char/Default/Main/ok.txt", "A calm personality description with enough words to be a paragraph here.\n")
        warnings = lint_prompts(self.tmp)
        self.assertEqual(warnings, [], [w.format() for w in warnings])


if __name__ == "__main__":
    unittest.main()
