from __future__ import annotations

import copy
import unittest

from localization import TrStr


class TrStrTests(unittest.TestCase):
    def test_deepcopy_preserves_translation_sources(self):
        value = TrStr("English", "Русский", "English")

        cloned = copy.deepcopy(value)

        self.assertIs(cloned, value)
        self.assertEqual(cloned.tr_ru, "Русский")
        self.assertEqual(cloned.tr_en, "English")


if __name__ == "__main__":
    unittest.main()
