"""Checks for the standalone Sea Battle window and its Mita-reaction bridge."""
from __future__ import annotations

import os
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from modules.SeaBattle.seabattle_gui import SeaBattleWindow
from modules.SeaBattle.seabattle_instance import SeaBattleGame


class _EventBus:
    def __init__(self) -> None:
        self.events = []

    def emit(self, name, payload) -> None:
        self.events.append((name, payload))


class _Character:
    char_id = "Mita"

    def __init__(self) -> None:
        self.event_bus = _EventBus()
        self.variables = {"playingGame": True}

    def get_variable(self, key, default=None):
        return self.variables.get(key, default)

    def set_variable(self, key, value) -> None:
        self.variables[key] = value


class _Settings:
    def __init__(self, enabled=True) -> None:
        self.enabled = enabled

    def get(self, _key, default=None):
        return self.enabled if self.enabled is not None else default


class SeaBattleWindowReactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_checked_by_default_and_valid_shot_is_forwarded(self) -> None:
        command_queue = queue.Queue()
        state_queue = queue.Queue()
        reaction_queue = queue.Queue()
        window = SeaBattleWindow(command_queue, state_queue, reaction_queue)
        try:
            self.assertTrue(window.mita_reaction_checkbox.isChecked())
            self.assertFalse(window.windowIcon().isNull())

            engine = window.game.engine
            engine.game_phase = "battle"
            engine.current_player = engine.player_id
            window.update_view()
            self.assertFalse(window.mita_reaction_checkbox.isHidden())

            window.on_opponent_board_click(0, 0, Qt.MouseButton.LeftButton)
            event = reaction_queue.get_nowait()
            self.assertEqual(event["event"], "player_target_selected")
            self.assertEqual(event["coord"], "A1")

            window.mita_reaction_checkbox.setChecked(False)
            engine.current_player = engine.player_id
            window.on_opponent_board_click(1, 0, Qt.MouseButton.LeftButton)
            with self.assertRaises(queue.Empty):
                reaction_queue.get_nowait()
        finally:
            window.close()

    def test_bridge_uses_visible_l2_reaction_and_respects_global_switches(self) -> None:
        character = _Character()
        game = SeaBattleGame(character)

        with patch("modules.SeaBattle.seabattle_instance.use", return_value=_Settings(True)):
            game._dispatch_player_target_reaction(
                {"coord": "C7", "message": "Попал! Стреляйте еще раз."}
            )

        self.assertEqual(len(character.event_bus.events), 1)
        _event_name, payload = character.event_bus.events[0]
        self.assertEqual(payload["event_type"], "react")
        self.assertEqual(payload["policy"]["react_level"], 2)
        self.assertIn("C7", payload["system_input"])

        character.event_bus.events.clear()
        with patch("modules.SeaBattle.seabattle_instance.use", return_value=_Settings(False)):
            game._dispatch_player_target_reaction({"coord": "D7", "message": "Мимо!"})
        self.assertEqual(character.event_bus.events, [])


if __name__ == "__main__":
    unittest.main()
