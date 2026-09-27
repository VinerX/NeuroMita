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

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from modules.SeaBattle.seabattle_gui import SeaBattleWindow
except ImportError:
    Qt = None
    QApplication = None
    SeaBattleWindow = None


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


class _QueueWithoutEmpty:
    def __init__(self, *items) -> None:
        self.items = list(items)

    def get_nowait(self):
        if not self.items:
            raise queue.Empty
        return self.items.pop(0)

    def empty(self):
        raise AssertionError("Queue.empty() must not be used for cross-process polling")


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
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

    def test_process_commands_drains_queue_without_checking_empty(self) -> None:
        window = SeaBattleWindow(_QueueWithoutEmpty({"action": "get_state"}), queue.Queue(), queue.Queue())
        try:
            with patch.object(window, "send_state_update") as send_state_update:
                window.process_commands()

            send_state_update.assert_called_once_with()
        finally:
            window.close()

    def test_mita_terminal_move_emits_game_over_after_state_update(self) -> None:
        command_queue = queue.Queue()
        state_queue = queue.Queue()
        reaction_queue = queue.Queue()
        window = SeaBattleWindow(command_queue, state_queue, reaction_queue)
        try:
            command_queue.put({"action": "mita_move", "coord": "A1"})
            final_state = {"phase": "game_over", "winner": window.game.mita_id, "player_id": window.game.player_id}
            order = []

            with patch.object(window.game.engine, "make_move", return_value=("hit", "Победа")):
                with patch.object(window.game, "get_full_state", return_value=final_state):
                    with patch.object(window, "update_view"):
                        with patch.object(window, "send_state_update", side_effect=lambda: order.append("state")):
                            original = window._request_game_over_reaction

                            def record_reaction(winner, player_id):
                                order.append("reaction")
                                original(winner, player_id)

                            with patch.object(window, "_request_game_over_reaction", side_effect=record_reaction):
                                window.process_commands()

            self.assertEqual(order, ["state", "reaction"])
            event = reaction_queue.get_nowait()
            self.assertEqual(event["event"], "player_game_over")
            self.assertEqual(event["winner"], window.game.mita_id)
        finally:
            window.close()

    def test_mita_hit_emits_follow_up_reaction_after_state_update(self) -> None:
        command_queue = queue.Queue()
        state_queue = queue.Queue()
        reaction_queue = queue.Queue()
        window = SeaBattleWindow(command_queue, state_queue, reaction_queue)
        try:
            command_queue.put({"action": "mita_move", "coord": "A1"})
            order = []

            with patch.object(window.game.engine, "make_move", return_value=("hit", "Попал!")):
                with patch.object(window.game, "get_full_state", return_value={"phase": "battle"}):
                    with patch.object(window, "update_view"):
                        with patch.object(window, "send_state_update", side_effect=lambda: order.append("state")):
                            with patch.object(window, "_request_mita_hit_reaction", side_effect=lambda *args: order.append("reaction")):
                                window.process_commands()

            self.assertEqual(order, ["state", "reaction"])
        finally:
            window.close()

    def test_manual_turn_button_emits_request_when_automation_is_off(self) -> None:
        command_queue = queue.Queue()
        state_queue = queue.Queue()
        reaction_queue = queue.Queue()
        window = SeaBattleWindow(command_queue, state_queue, reaction_queue)
        try:
            window.mita_reaction_checkbox.setChecked(False)
            window.game.engine.game_phase = "battle"
            window.game.engine.current_player = window.game.mita_id
            window.update_view()

            self.assertFalse(window.btn_request_mita_turn.isHidden())
            window.btn_request_mita_turn.click()
            self.assertEqual(reaction_queue.get_nowait()["event"], "manual_mita_turn")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
