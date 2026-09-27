"""Regression checks for Sea Battle lifecycle reactions."""
from __future__ import annotations

import sys
import queue
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from modules.SeaBattle.seabattle_instance import SeaBattleGame


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


class _DslInterpreter:
    def __init__(self):
        self.paths = []

    def process_file(self, path):
        self.paths.append(path)
        return "game state", []


class SeaBattleLifecycleReactionTests(unittest.TestCase):
    def test_finishing_placement_requests_reaction_from_game_host(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_placement_completed_reaction()

        self.assertEqual(len(host.requests), 1)
        instruction = host.requests[0][1]
        self.assertIn("finished placing all ships", instruction)
        self.assertIn("PlaceShipsRandomly", instruction)

    def test_player_shot_requests_an_immediate_sea_battle_move(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_player_target_reaction({"coord": "A1", "result": "miss"})

        self.assertEqual(len(host.requests), 1)
        instruction = host.requests[0][1]
        self.assertIn("MakeMove,<coordinate>", instruction)
        self.assertNotIn("Do not take a Sea Battle turn", instruction)

    def test_mita_hit_requests_a_follow_up_shot(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_mita_target_hit_reaction({"coord": "B1", "result": "hit"})

        self.assertEqual(len(host.requests), 1)
        instruction = host.requests[0][1]
        self.assertIn("It is still your turn", instruction)
        self.assertIn("MakeMove,<coordinate>", instruction)

    def test_manual_turn_request_asks_mita_to_move(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_manual_turn_reaction()

        self.assertEqual(len(host.requests), 1)
        self.assertIn("MakeMove,<coordinate>", host.requests[0][1])

    def test_game_over_requests_reaction_without_another_shot(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_game_over_reaction({"winner": 0, "player_id": 0})

        self.assertEqual(len(host.requests), 1)
        instruction = host.requests[0][1]
        self.assertIn("The player won", instruction)
        self.assertIn("do not take another shot", instruction)

    def test_runtime_state_uses_shared_game_prompt(self):
        character = _Character()
        character.dsl_interpreter = _DslInterpreter()
        game = SeaBattleGame(character)
        game.state_queue = queue.Queue()
        game.state_queue.put({
            "phase": "battle",
            "is_player_turn": False,
            "mita_id": "mita",
            "mita_my_board_str": "my board",
            "mita_opponent_view_str": "opponent board",
            "mita_ships_to_place": [],
            "hunt_info": {},
            "shot_history_str": "",
        })

        self.assertEqual(game.get_state_prompt(), "game state")
        self.assertEqual(character.dsl_interpreter.paths, ["_CommonPrompts/seabattle.system"])

    def test_runtime_state_reuses_last_boards_when_queue_has_no_new_snapshot(self):
        character = _Character()
        character.dsl_interpreter = _DslInterpreter()
        game = SeaBattleGame(character)
        game.state_queue = queue.Queue()
        game._last_state = {
            "phase": "battle",
            "is_player_turn": False,
            "mita_id": "mita",
            "mita_my_board_str": "my board",
            "mita_opponent_view_str": "opponent board",
            "mita_ships_to_place": [],
            "hunt_info": {},
            "shot_history_str": "",
        }

        self.assertEqual(game.get_state_prompt(), "game state")
        self.assertEqual(character.dsl_interpreter.paths, ["_CommonPrompts/seabattle.system"])

    def test_closing_window_requests_reaction_from_game_host(self):
        character = _Character()
        host = _GameHost()
        game = SeaBattleGame(character, host=host)

        game._dispatch_player_close_reaction()

        self.assertEqual(len(host.requests), 1)
        self.assertIn("closed the Sea Battle game window", host.requests[0][1])


if __name__ == "__main__":
    unittest.main()
