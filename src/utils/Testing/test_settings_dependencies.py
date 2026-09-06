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

from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton, QVBoxLayout, QWidget

from core.settings_registry import SettingsRegistry
from ui.gui_templates import create_setting_widget
from ui.settings.game_settings import _bind_manual_game_launch_buttons
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

    def test_manual_game_buttons_follow_global_and_per_game_switches(self) -> None:
        gui = QWidget()
        gui.ENABLE_GAMES = QCheckBox()
        gui.ENABLE_GAME_CHESS = QCheckBox()
        gui.ENABLE_GAME_SEABATTLE = QCheckBox()
        gui.launch_chess_button = QPushButton()
        gui.launch_seabattle_button = QPushButton()

        _bind_manual_game_launch_buttons(gui)
        self.assertFalse(gui.launch_chess_button.isEnabled())
        self.assertFalse(gui.launch_seabattle_button.isEnabled())

        gui.ENABLE_GAMES.setChecked(True)
        gui.ENABLE_GAME_CHESS.setChecked(True)
        self.assertTrue(gui.launch_chess_button.isEnabled())
        self.assertFalse(gui.launch_seabattle_button.isEnabled())

        gui.ENABLE_GAME_SEABATTLE.setChecked(True)
        self.assertTrue(gui.launch_seabattle_button.isEnabled())
        gui.ENABLE_GAMES.setChecked(False)
        self.assertFalse(gui.launch_chess_button.isEnabled())
        self.assertFalse(gui.launch_seabattle_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
