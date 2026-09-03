from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from localization import TrStr


class TrStrTests(unittest.TestCase):
    def test_deepcopy_preserves_translation_sources(self):
        value = TrStr("English", "Русский", "English")

        cloned = copy.deepcopy(value)

        self.assertIs(cloned, value)
        self.assertEqual(cloned.tr_ru, "Русский")
        self.assertEqual(cloned.tr_en, "English")

    def test_repeat_restore_prompt_is_translated_in_every_bundled_locale(self):
        locale_dir = Path(__file__).resolve().parents[2] / "localization" / "locales"
        keys = (
            "Возможно, уже восстановлено",
            "Похоже, этот архив уже восстанавливали. Повторить восстановление?",
        )
        for locale_path in locale_dir.glob("*.json"):
            if locale_path.name.startswith("_"):
                continue
            catalog = json.loads(locale_path.read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(catalog.get(key), f"{locale_path.name}: missing {key!r}")


if __name__ == "__main__":
    unittest.main()
