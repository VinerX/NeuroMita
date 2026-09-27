"""Public mini-game session context never exposes private game state."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.mini_game_session_registry import mini_game_sessions
from controllers.prompt_controller import PromptController
from modules.Chess.game_instance import ChessGame
from modules.SeaBattle.seabattle_instance import SeaBattleGame


class _Character:
    char_id = "Kind"
    display_name = "Good Mita"

    def __init__(self):
        self.variables = {"playingGame": True}

    def get_variable(self, key, default=None):
        return self.variables.get(key, default)

    def set_variable(self, key, value):
        self.variables[key] = value


class _Host:
    def request_character_reaction(self, _game, _instruction, *, visible=True):
        return True


class MiniGamePublicContextTests(unittest.TestCase):
    def setUp(self):
        self.registry = mini_game_sessions()

    def tearDown(self):
        self.registry.stop("Kind")

    def test_other_character_gets_only_public_session_and_event(self):
        self.registry.start("Kind", "Good Mita", "chess")
        self.registry.update_public_event("Kind", "chess", "The player made the chess move e4.")

        message = PromptController._build_shared_minigame_context("Crazy")

        self.assertIsNotNone(message)
        self.assertIn("currently playing Chess with Good Mita", message["content"])
        self.assertIn("Latest public event: The player made the chess move e4", message["content"])
        self.assertIn("Do not issue Chess or Sea Battle commands", message["content"])
        for private_value in ("FEN", "legal_moves", "MakeChessMoveAsLLM", "hidden ships"):
            self.assertNotIn(private_value, message["content"])

    def test_owner_does_not_get_duplicate_public_context(self):
        self.registry.start("Kind", "Good Mita", "seabattle")
        self.assertIsNone(PromptController._build_shared_minigame_context("Kind"))

    def test_chess_and_seabattle_have_the_same_public_projection(self):
        for game_id, label in (("chess", "Chess"), ("seabattle", "Sea Battle")):
            with self.subTest(game_id=game_id):
                self.registry.start("Kind", "Good Mita", game_id)
                message = PromptController._build_shared_minigame_context("Crazy")
                self.assertIn(f"currently playing {label} with Good Mita", message["content"])
                self.registry.stop("Kind")

    def test_chess_player_move_is_public_and_cleanup_removes_session(self):
        character = _Character()
        game = ChessGame(character, "chess", host=_Host())
        self.registry.start("Kind", "Good Mita", "chess")

        game._dispatch_player_move_reaction({"san": "e4", "uci": "e2e4"})

        session = self.registry.snapshot()[0]
        self.assertEqual(session.last_public_event, "The player made the chess move e4.")
        game.cleanup()
        self.assertEqual(self.registry.snapshot(), ())

    def test_seabattle_publishes_only_player_shot_and_cleanup_removes_session(self):
        character = _Character()
        game = SeaBattleGame(character, "seabattle", host=_Host())
        self.registry.start("Kind", "Good Mita", "seabattle")

        game._dispatch_player_target_reaction({"coord": "B4", "message": "miss"})

        session = self.registry.snapshot()[0]
        self.assertEqual(session.last_public_event, "The player fired at B4: miss.")
        game.cleanup()
        self.assertEqual(self.registry.snapshot(), ())


if __name__ == "__main__":
    unittest.main()
