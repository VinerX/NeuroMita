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

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from core.settings_registry import SettingsRegistry
from ui.gui_templates import create_setting_widget
from ui.settings.game_settings import _bind_manual_game_launch_buttons
from ui.settings.settings_binding import QtSettingsViewModel
from styles.main_styles import get_stylesheet
from styles.theme import get_theme
from services.settings_service import SettingsManagerService


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

    def test_persisted_enabled_games_make_child_rows_visually_active(self) -> None:
        settings = SettingsRegistry({"ENABLE_GAMES": True, "ENABLE_GAME_CHESS": True})
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
            chess_row = create_setting_widget(
                gui, gui, "Chess", setting_key="ENABLE_GAME_CHESS",
                widget_type="checkbutton", widget_name="ENABLE_GAME_CHESS",
                depends_on="ENABLE_GAMES",
            )
            layout.addWidget(chess_row)

            self.assertTrue(gui.ENABLE_GAMES.isChecked())
            self.assertTrue(gui.ENABLE_GAME_CHESS.isEnabled())
            self.assertEqual(chess_row.property("disabled"), "false")
        finally:
            binding.close()
            settings.close()

    def test_camera_row_labels_follow_enabled_state_in_both_directions(self) -> None:
        settings = SettingsRegistry({"MITA_CAMERA_ENABLED": False, "MITA_CAMERA_CONTINUOUS": True})
        binding = QtSettingsViewModel(settings)
        gui = _SettingsGui(binding)
        gui.setObjectName("SettingsPageRoot")
        gui.setStyleSheet(
            'QWidget#SettingsPageRoot QLabel { color: white; }'
            'QWidget#SettingsPageRoot QWidget#SettingRow[disabled="true"] QLabel '
            '{ color: rgba(188,169,187,0.34); }'
        )
        layout = QVBoxLayout(gui)
        try:
            layout.addWidget(create_setting_widget(
                gui, gui, "Camera", setting_key="MITA_CAMERA_ENABLED",
                widget_type="checkbutton", widget_name="MITA_CAMERA_ENABLED",
            ))
            row = create_setting_widget(
                gui, gui, "Continuous capture", setting_key="MITA_CAMERA_CONTINUOUS",
                widget_type="checkbutton", widget_name="MITA_CAMERA_CONTINUOUS",
                depends_on="MITA_CAMERA_ENABLED", description="Frames accompany the next turn.",
            )
            layout.addWidget(row)
            gui.show()
            self.app.processEvents()
            labels = row.findChildren(QLabel)
            self.assertEqual(len(labels), 2)
            for enabled in (True, False, True):
                settings.set("MITA_CAMERA_ENABLED", enabled)
                self.app.processEvents()
                self.app.processEvents()
                self.assertEqual(gui.MITA_CAMERA_CONTINUOUS.isEnabled(), enabled)
                self.assertEqual(row.property("disabled"), "false" if enabled else "true")
                expected = (255, 255, 255, 255) if enabled else (188, 169, 187, 86)
                for label in labels:
                    self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).getRgb(), expected)
        finally:
            gui.close()
            binding.close()
            settings.close()

    def test_request_interval_uses_active_style_with_the_production_theme(self) -> None:
        for initial_enabled in (False, True):
            with self.subTest(initial_enabled=initial_enabled):
                settings = SettingsRegistry({
                    "SEND_IMAGE_REQUESTS": initial_enabled, "IMAGE_REQUEST_INTERVAL": "20.0",
                })
                binding = QtSettingsViewModel(SettingsManagerService(settings))
                gui = _SettingsGui(binding)
                gui.setObjectName("SettingsPageRoot")
                gui.setStyleSheet(get_stylesheet())
                layout = QVBoxLayout(gui)
                try:
                    layout.addWidget(create_setting_widget(
                        gui, gui, "Send Image Requests", setting_key="SEND_IMAGE_REQUESTS",
                        widget_type="checkbutton", widget_name="SEND_IMAGE_REQUESTS",
                    ))
                    row = create_setting_widget(
                        gui, gui, "Request Interval (sec)", setting_key="IMAGE_REQUEST_INTERVAL",
                        widget_type="entry", widget_name="IMAGE_REQUEST_INTERVAL",
                        depends_on="SEND_IMAGE_REQUESTS", default="20.0",
                    )
                    layout.addWidget(row)
                    gui.show()
                    self.app.processEvents()
                    label = row.findChild(QLabel)

                    def assert_state(enabled: bool) -> None:
                        self.assertEqual(gui.SEND_IMAGE_REQUESTS.isChecked(), enabled)
                        self.assertEqual(gui.IMAGE_REQUEST_INTERVAL.isEnabled(), enabled)
                        self.assertEqual(label.isEnabled(), enabled)
                        self.assertEqual(row.property("disabled"), "false" if enabled else "true")
                        expected = QColor(get_theme()["text"]).getRgb() if enabled else (188, 169, 187, 86)
                        self.assertEqual(label.palette().color(QPalette.ColorRole.WindowText).getRgb(), expected)
                        self.assertEqual(gui.IMAGE_REQUEST_INTERVAL.text(), "20.0")

                    assert_state(initial_enabled)
                    for _ in range(2):
                        QTest.mouseClick(gui.SEND_IMAGE_REQUESTS, Qt.MouseButton.LeftButton)
                        assert_state(gui.SEND_IMAGE_REQUESTS.isChecked())
                    for enabled in (not initial_enabled, initial_enabled):
                        settings.set("SEND_IMAGE_REQUESTS", enabled)
                        for _ in range(50):
                            self.app.processEvents()
                            if gui.SEND_IMAGE_REQUESTS.isChecked() == enabled:
                                break
                            QTest.qWait(10)
                        assert_state(enabled)
                finally:
                    gui.close()
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
