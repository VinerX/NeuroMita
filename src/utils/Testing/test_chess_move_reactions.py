"""Regression checks for chess player-move reactions and the checked GUI option."""
from __future__ import annotations

import os
import queue
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

try:
    from PyQt6.QtWidgets import QApplication
    from modules.Chess.chess_board import ChessGuiTkinter
except ImportError:
    QApplication = None
    ChessGuiTkinter = None

from modules.Chess.game_instance import ChessGame


class _Character:
    char_id = "Mita"

    def __init__(self):
        self.variables = {"playingGame": True}

    def get_variable(self, key, default=None):
        return self.variables.get(key, default)

    def set_variable(self, key, value):
        self.variables[key] = value


class _GameHost:
    def __init__(self):
        self.requests = []

    def request_character_reaction(self, game, instruction, *, visible=True):
        self.requests.append((game, instruction, visible))
        return True


class _Controller:
    current_maia_elo = 1500
    is_auto = False

    def get_player_color_is_white_for_gui(self):
        return True


class _DslInterpreter:
    def __init__(self):
        self.paths = []

    def process_file(self, path):
        self.paths.append(path)
        return "game state", []


class ChessMoveReactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([]) if QApplication is not None else None

    def test_player_move_requests_reaction_from_game_host(self):
        character = _Character()
        host = _GameHost()
        game = ChessGame(character, "chess", host=host)

        game._dispatch_player_move_reaction({"uci": "e2e4", "san": "e4"})

        self.assertEqual(len(host.requests), 1)
        requested_game, instruction, visible = host.requests[0]
        self.assertIs(requested_game, game)
        self.assertTrue(visible)
        self.assertIn("e4", instruction)
        self.assertIn("RequestBestChessMove", instruction)
        self.assertNotIn("Do not make a chess move", instruction)

    def test_player_closing_chess_requests_reaction_from_game_host(self):
        character = _Character()
        host = _GameHost()
        game = ChessGame(character, "chess", host=host)

        game._dispatch_player_close_reaction()

        self.assertEqual(len(host.requests), 1)
        self.assertIn("closed the chess game window", host.requests[0][1])

    def test_game_over_requests_reaction_without_a_chess_move(self):
        character = _Character()
        host = _GameHost()
        game = ChessGame(character, "chess", host=host)

        game._dispatch_game_over_reaction({"outcome": "Checkmate."})

        self.assertEqual(len(host.requests), 1)
        instruction = host.requests[0][1]
        self.assertIn("game has ended", instruction)
        self.assertIn("do not make a chess move", instruction)

    def test_player_move_is_not_forwarded_when_game_is_not_active(self):
        character = _Character()
        character.variables["playingGame"] = False
        host = _GameHost()
        game = ChessGame(character, "chess", host=host)

        game._dispatch_player_move_reaction({"uci": "e2e4", "san": "e4"})

        self.assertEqual(host.requests, [])

    def test_manual_turn_request_asks_mita_to_move(self):
        character = _Character()
        host = _GameHost()
        game = ChessGame(character, "chess", host=host)

        game._dispatch_manual_turn_reaction()

        self.assertEqual(len(host.requests), 1)
        self.assertIn("RequestBestChessMove", host.requests[0][1])
        self.assertNotIn("Do not make a chess move", host.requests[0][1])

    @unittest.skipIf(QApplication is None, "PyQt6 is not installed")
    def test_chess_reaction_checkbox_is_checked_by_default(self):
        window = ChessGuiTkinter(_Controller())
        try:
            self.assertIsNotNone(window.mita_reaction_checkbox)
            self.assertTrue(window.mita_reaction_checkbox.isChecked())
        finally:
            window.hide()
            window.deleteLater()

    def test_runtime_state_uses_shared_game_prompt(self):
        character = _Character()
        character.dsl_interpreter = _DslInterpreter()
        game = ChessGame(character, "chess")
        game.state_queue = queue.Queue()
        game.state_queue.put({
            "player_is_white_in_gui": True,
            "turn": "black",
            "current_elo": 1500,
            "last_move_san": "e4",
            "fen": "test-fen",
            "board_ascii": None,
            "is_game_over": False,
            "outcome_message": "Playing",
            "legal_moves_uci": ["e7e5"],
            "legal_moves_short": ["e7e5"],
            "is_auto": False,
            "is_cheat": False,
        })

        self.assertEqual(game.get_state_prompt(), "game state")
        self.assertEqual(character.dsl_interpreter.paths, ["_CommonPrompts/chess.system"])

    def test_runtime_state_reuses_last_board_when_queue_has_no_new_snapshot(self):
        character = _Character()
        character.dsl_interpreter = _DslInterpreter()
        game = ChessGame(character, "chess")
        game.state_queue = queue.Queue()
        game._last_state_data = {
            "player_is_white_in_gui": True,
            "turn": "black",
            "current_elo": 1500,
            "last_move_san": "e4",
            "fen": "test-fen",
            "board_ascii": None,
            "is_game_over": False,
            "outcome_message": "Playing",
            "legal_moves_uci": ["e7e5"],
            "legal_moves_short": ["e7e5"],
            "is_auto": False,
            "is_cheat": False,
        }

        self.assertEqual(game.get_state_prompt(), "game state")
        self.assertEqual(character.dsl_interpreter.paths, ["_CommonPrompts/chess.system"])


if __name__ == "__main__":
    unittest.main()
