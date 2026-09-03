"""Regression checks for settings rows controlled by another setting."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from core.settings_registry import SettingsRegistry
from ui.gui_templates import create_setting_widget
from ui.settings.settings_binding import QtSettingsViewModel


class _SettingsGui(QWidget):
    def __init__(self, binding: QtSettingsViewModel) -> None:
        super().__init__()
        self.settings_binding = binding


class SettingsDependenciesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_bound_controller_refreshes_dependent_row(self) -> None:
        settings = SettingsRegistry({"ENABLE_GAMES": False, "ENABLE_GAME_CHESS": False})
        binding = QtSettingsViewModel(settings)
        gui = _SettingsGui(binding)
        layout = QVBoxLayout(gui)
        try:
            layout.addWidget(
                create_setting_widget(
                    gui, gui, "Enable games", setting_key="ENABLE_GAMES",
                    widget_type="checkbutton", widget_name="ENABLE_GAMES",
                )
            )
            layout.addWidget(
                create_setting_widget(
                    gui, gui, "Chess", setting_key="ENABLE_GAME_CHESS",
                    widget_type="checkbutton", widget_name="ENABLE_GAME_CHESS",
                    depends_on="ENABLE_GAMES",
                )
            )

            self.assertFalse(gui.ENABLE_GAME_CHESS.isEnabled())
            settings.set("ENABLE_GAMES", True)
            self.app.processEvents()
            self.app.processEvents()
            self.assertTrue(gui.ENABLE_GAMES.isChecked())
            self.assertTrue(gui.ENABLE_GAME_CHESS.isEnabled())
        finally:
            binding.close()
            settings.close()


if __name__ == "__main__":
    unittest.main()
