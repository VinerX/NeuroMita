"""Просмотрщик БД должен фильтроваться по правильной Мите независимо от кнопки.

Регресс: кнопки «История» в чат-панели и песочнице знают, с какой Митой идёт
диалог, но open_db_viewer заново вычислял фильтр из _configured_char_id (Мита,
выбранная в НАСТРОЙКАХ). Из-за приоритета _configured_char_id над остальным это
показывало БД не той Миты. Явно переданный character_id должен побеждать.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from controllers.gui import character_settings_logic as csl


class _Gui:
    # Как настроено в реальном окне: в настройках выбрана одна Мита...
    _configured_char_id = "KindMita"
    _active_character_id = "KindMita"


class OpenDbViewerCharacterFilterTests(unittest.TestCase):
    def _capture_character_id(self, **call_kwargs):
        captured = {}

        class _FakeDialog:
            def __init__(self, parent=None, character_id=None):
                captured["character_id"] = character_id

            def exec(self):
                return 0

        with mock.patch.object(csl, "DbViewerDialog", _FakeDialog):
            csl.open_db_viewer(_Gui(), **call_kwargs)
        return captured["character_id"]

    def test_explicit_character_id_wins_over_settings_selection(self):
        # ...а диалог с Митой из чата ("CrazyMita") — именно она и должна попасть в фильтр.
        self.assertEqual(self._capture_character_id(character_id="CrazyMita"), "CrazyMita")

    def test_falls_back_to_settings_selection_when_not_given(self):
        # Не-чатовые кнопки (настройки) фильтр не передают — берём выбранную в настройках.
        self.assertEqual(self._capture_character_id(), "KindMita")

    def test_blank_override_falls_back(self):
        self.assertEqual(self._capture_character_id(character_id=""), "KindMita")
        self.assertEqual(self._capture_character_id(character_id=None), "KindMita")


if __name__ == "__main__":
    unittest.main()
