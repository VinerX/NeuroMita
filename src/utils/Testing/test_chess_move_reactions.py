"""Regression checks for chess player-move reactions and the checked GUI option."""
from __future__ import annotations

import os
import json
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
from modules.Chess.board_logic import PureBoardLogic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
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
    engine_is_thinking = False

    def __init__(self, fen=chess.STARTING_FEN, player_is_white=True):
        self.board = chess.Board(fen)
        self.player_is_white = player_is_white
        self.player_is_white_in_gui = player_is_white

    def get_player_color_is_white_for_gui(self):
        return self.player_is_white

    def get_current_board_object_for_gui(self):
        return self.board

    def new_game(self):
        self.board.reset()


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

    def test_game_over_identifies_winner_independently_of_localized_text(self):
        for result, expected in (
            ("player_win", "The player won; you lost."),
            ("mita_win", "You won; the player lost."),
            ("draw", "The game was a draw."),
        ):
            with self.subTest(result=result):
                host = _GameHost()
                game = ChessGame(_Character(), "chess", host=host)
                game._dispatch_game_over_reaction({"outcome": "localized result", "result": result})
                self.assertIn(expected, host.requests[0][1])
                self.assertIn("do not make a chess move", host.requests[0][1])

    @unittest.skipIf(QApplication is None, "PyQt6 is not installed")
    def test_win_and_draw_react_before_result_dialog_is_dismissed(self):
        for fen, player_is_white, result in (
            ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", True, "player_win"),
            ("8/8/8/8/8/5k2/6q1/7K w - - 0 1", False, "player_win"),
            ("7k/8/5K2/8/8/8/8/8 w - - 0 1", True, "draw"),
        ):
            for enabled in (True, False):
                with self.subTest(result=result, white=player_is_white, enabled=enabled):
                    reactions = queue.Queue()
                    window = ChessGuiTkinter(_Controller(fen, player_is_white), reaction_queue=reactions)
                    window.mita_reaction_checkbox.setChecked(enabled)

                    def check_before_dismissal(dialog):
                        if enabled:
                            event = reactions.get_nowait()
                            self.assertEqual(event["event"], "player_game_over")
                            self.assertEqual(event["result"], result)
                        else:
                            self.assertTrue(reactions.empty())
                        return 0

                    try:
                        with patch.object(QMessageBox, "exec", new=check_before_dismissal):
                            window.show_game_over_message_slot("result")
                        self.assertTrue(reactions.empty(), "Must not react again after OK")
                    finally:
                        window.hide()
                        window.deleteLater()

    @unittest.skipIf(QApplication is None, "PyQt6 is not installed")
    def test_defeat_rematch_preserves_result_after_board_reset(self):
        reactions = queue.Queue()
        controller = _Controller("8/8/8/8/8/5k2/6q1/7K w - - 0 1")
        window = ChessGuiTkinter(controller, reaction_queue=reactions)
        selected = []

        def choose_rematch(dialog):
            self.assertTrue(reactions.empty())
            selected.append(next(b for b in dialog.buttons() if dialog.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole))
            return 0

        try:
            with patch.object(QMessageBox, "exec", new=choose_rematch), patch.object(
                QMessageBox, "clickedButton", new=lambda dialog: selected[0]
            ):
                window.show_game_over_message_slot("Checkmate")
            event = reactions.get_nowait()
            self.assertEqual(event["choice"], "restart")
            self.assertEqual(event["result"], "mita_win")
            self.assertEqual(controller.board.fen(), chess.STARTING_FEN)
            self.assertTrue(reactions.empty())
        finally:
            window.hide()
            window.deleteLater()

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


class ChessResultLocalizationTests(unittest.TestCase):
    def _positions(self):
        cases = [
            ("8/8/8/8/8/5k2/6q1/7K w - - 0 1", True, "Мат! Победили Черные."),
            ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", True, "Мат! Победили Белые."),
            ("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1", True, "Ничья (пат)."),
            ("7k/8/5K2/8/8/8/8/8 w - - 0 1", True, "Ничья (недостаточно материала)."),
            ("7k/8/5K2/8/8/8/8/R7 w - - 150 80", True, "Ничья (правило 75 ходов)."),
            ("7k/8/5K2/8/8/8/8/R7 w - - 100 80", True,
             "Ничья (можно заявить по правилу 50 ходов или трехкратного повторения)."),
            (chess.STARTING_FEN, False, "Игра продолжается."),
        ]
        for fen, ended, key in cases:
            logic = PureBoardLogic()
            logic.reset_board(fen)
            yield logic, ended, key
        logic = PureBoardLogic()
        for move in ["g1f3", "g8f6", "f3g1", "f6g8"] * 4:
            logic.board.push_uci(move)
        yield logic, True, "Ничья (пятикратное повторение позиции)."

    def test_every_chess_result_uses_current_locale(self):
        locale_dir = PROJECT_SRC / "localization" / "locales"
        english = json.loads((locale_dir / "en.json").read_text(encoding="utf-8"))
        for logic, ended, key in self._positions():
            for language, expected in (("RU", key), ("EN", english[key])):
                with self.subTest(key=key, language=language):
                    with patch("localization._current_language", return_value=language):
                        self.assertEqual(logic.is_game_over(), (ended, expected))

    def test_game_results_exist_in_every_bundled_locale(self):
        keys = [key for _, _, key in self._positions()]
        keys += ["Вы победили!", "Мита победила.", "Игра окончена"]
        for path in (PROJECT_SRC / "localization" / "locales").glob("*.json"):
            if path.name.startswith("_"):
                continue
            catalog = json.loads(path.read_text(encoding="utf-8"))
            for key in keys:
                with self.subTest(locale=path.stem, key=key):
                    self.assertTrue(catalog.get(key), f"{path.name}: missing {key}")


if __name__ == "__main__":
    unittest.main()
