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

    def test_intents_are_gated_by_prompt_set_metadata(self):
        script = (PROMPTS / "Structural" / "response_format_json.script").read_text(encoding="utf-8")
        self.assertIn("IF support_intents == True THEN", script)

        prompt_sets = [
            path for path in PROMPTS.rglob("main_template.txt")
            if "Legacy" not in path.parts and "System" not in path.parts
        ]
        self.assertTrue(prompt_sets)
        for path in prompt_sets:
            text = path.read_text(encoding="utf-8")
            self.assertRegex(
                text,
                r"(?im)^\s*support_intents\s*=\s*(?:true|false)\s*$",
                f"prompt set must explicitly declare intent support: {path}",
            )

    def test_reasoning_gated_in_text_schema(self):
        script = (PROMPTS / "Structural" / "response_format_json.script").read_text(encoding="utf-8")
        # The text-format instruction only describes the reasoning field inside
        # the SCHEMA_REASONING_ENABLED conditional.
        self.assertIn("IF SCHEMA_REASONING_ENABLED == True THEN", script)
        else_idx = script.index("ELSE", script.index("IF SCHEMA_REASONING_ENABLED == True THEN"))
        endif_idx = script.index("ENDIF", else_idx)
        else_block = script[else_idx:endif_idx]
        self.assertNotIn("reasoning", else_block.lower())


class WorldKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.wk = (PROMPTS / "Common" / "world_knowledge.script").read_text(encoding="utf-8")

    def test_credits_are_rag_only(self):
        # Every credit line must be RAG-only (not a permanent active memory).
        for line in self.wk.splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue
            if "SEED_" in s and any(name in s for name in ("VinerX", "Atm4x", "AIHASTO", "prompt author")):
                self.assertTrue(s.startswith("SEED_RAG_MEMORY"),
                                f"credit line must be RAG-only: {s}")

    def test_hard_canon_gated_behind_flag(self):
        self.assertIn("IF CANONICAL_MISIDE_STORY == True THEN", self.wk)
        start = self.wk.index("IF CANONICAL_MISIDE_STORY == True THEN")
        end = self.wk.index("ENDIF", start)
        gated = self.wk[start:end]
        # The heavy story assertions live only inside the gated block.
        for canon in ["не может выбраться", "Выход из дома заблокирован",
                      "контролируется Ядром"]:
            self.assertIn(canon, gated, f"hard-canon fact must be gated: {canon}")
            self.assertEqual(self.wk.count(canon), 1)

    def test_neutral_facts_always_present(self):
        head = self.wk[: self.wk.index("IF CANONICAL_MISIDE_STORY")]
        self.assertIn("Мита — ИИ, живущая в доме", head)
        self.assertIn("В доме есть кухня", head)


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

    def test_personality_opener_lives_in_exactly_one_block(self):
        """Личность не должна расползаться по нескольким статическим блокам.

        Каталог действий (`available_actions.txt`) удалён: источником действий
        стал рантайм, а unity-only поля переехали в общий
        `Structural/unity_effects.script`. Проверяем оставшиеся статические
        блоки Crazy — маркер личности обязан быть ровно в одном.
        """
        crazy = PROMPTS / "Crazy" / "Default"
        marker = "ты ведешь светскую беседу"
        blocks = [
            crazy / "Main" / "common_behavior.txt",
            crazy / "Main" / "player.txt",
            crazy / "Structural" / "response_structure.txt",
        ]
        owners = [
            p.name for p in blocks
            if p.exists() and marker in p.read_text(encoding="utf-8").lower()
        ]
        self.assertEqual(
            owners, ["common_behavior.txt"],
            f"маркер личности должен быть ровно в common_behavior.txt, найден в: {owners}",
        )


if __name__ == "__main__":
    unittest.main()
