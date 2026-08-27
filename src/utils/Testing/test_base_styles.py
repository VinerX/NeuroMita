from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from styles.base import BASE_QSS
from styles.compose import get_main_window_stylesheet


class BaseStylesTests(unittest.TestCase):
    def test_child_widgets_are_transparent_by_default(self):
        self.assertIn(
            "QWidget {\n    background-color: transparent;",
            BASE_QSS,
        )

    def test_top_level_surfaces_keep_an_explicit_background(self):
        self.assertIn("QWidget:window { background-color: {bg_root}; }", BASE_QSS)
        self.assertIn("QMainWindow { background-color: {bg_window}; }", BASE_QSS)
        self.assertIn("QDialog { background-color: {bg_root}; }", BASE_QSS)
        self.assertIn("QMenu {", BASE_QSS)

    def test_rendered_stylesheet_has_no_unresolved_theme_tokens(self):
        stylesheet = get_main_window_stylesheet()

        self.assertIn("QWidget {\n    background-color: transparent;", stylesheet)
        self.assertNotIn("{bg_root}", stylesheet)
        self.assertNotIn("{card_bg}", stylesheet)


if __name__ == "__main__":
    unittest.main()
