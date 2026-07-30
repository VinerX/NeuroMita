from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.app_paths import prompt_path, prompts_dir


class PromptPathTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.base = self.root / "base"
        self.prompts = self.root / "prompts_elsewhere"
        (self.base / "Prompts" / "System").mkdir(parents=True)
        (self.prompts / "System").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def _env(self, **overrides):
        env = {"NEUROMITA_BASE_DIR": str(self.base), **overrides}
        return patch.dict(os.environ, env, clear=False)

    def test_prompts_dir_follows_explicit_override(self) -> None:
        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            self.assertEqual(prompts_dir(), self.prompts.resolve())

    def test_prompts_dir_falls_back_to_base_dir(self) -> None:
        with patch.dict(os.environ, {"NEUROMITA_BASE_DIR": str(self.base)}, clear=False):
            os.environ.pop("NEUROMITA_PROMPTS_DIR", None)
            self.assertEqual(prompts_dir(), (self.base / "Prompts").resolve())

    def test_settings_path_with_prompts_prefix_lands_in_moved_prompt_set(self) -> None:
        """Настройка написана как `Prompts/System/...`, а каталог промптов вынесен."""
        target = self.prompts / "System" / "compression_prompt.txt"
        target.write_text("moved", encoding="utf-8")

        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            resolved = prompt_path("Prompts/System/compression_prompt.txt")

        self.assertEqual(resolved, target)

    def test_prompt_set_wins_over_stale_copy_near_base_dir(self) -> None:
        stale = self.base / "Prompts" / "System" / "compression_prompt.txt"
        stale.write_text("stale", encoding="utf-8")
        actual = self.prompts / "System" / "compression_prompt.txt"
        actual.write_text("actual", encoding="utf-8")

        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            self.assertEqual(prompt_path("Prompts/System/compression_prompt.txt"), actual)

    def test_path_without_prefix_resolves_inside_prompt_set(self) -> None:
        target = self.prompts / "System" / "graph_extraction_prompt.txt"
        target.write_text("graph", encoding="utf-8")

        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            self.assertEqual(prompt_path("System/graph_extraction_prompt.txt"), target)

    def test_base_dir_layout_still_resolves_without_override(self) -> None:
        target = self.base / "Prompts" / "System" / "compression_prompt.txt"
        target.write_text("classic", encoding="utf-8")

        with patch.dict(os.environ, {"NEUROMITA_BASE_DIR": str(self.base)}, clear=False):
            os.environ.pop("NEUROMITA_PROMPTS_DIR", None)
            self.assertEqual(prompt_path("Prompts/System/compression_prompt.txt"), target)

    def test_absolute_path_is_left_alone(self) -> None:
        target = self.root / "custom" / "prompt.txt"
        target.parent.mkdir()
        target.write_text("custom", encoding="utf-8")

        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            self.assertEqual(prompt_path(str(target)), target)

    def test_missing_file_reports_prompt_set_candidate(self) -> None:
        """Путь для сообщения об ошибке должен указывать на актуальный каталог."""
        with self._env(NEUROMITA_PROMPTS_DIR=str(self.prompts)):
            resolved = prompt_path("Prompts/System/nowhere.txt")

        self.assertEqual(resolved, self.prompts / "System" / "nowhere.txt")


if __name__ == "__main__":
    unittest.main()
