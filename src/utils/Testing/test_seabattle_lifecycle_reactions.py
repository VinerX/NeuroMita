"""Regression checks for Sea Battle lifecycle reactions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from modules.SeaBattle.seabattle_instance import SeaBattleGame


class _EventBus:
    def __init__(self):
        self.events = []

    def emit(self, name, payload):
        self.events.append((name, payload))


class _Character:
    char_id = "Mita"

    def __init__(self):
        self.event_bus = _EventBus()

    def get_variable(self, _key, default=None):
        return default


class _Settings:
    def get(self, key, default=None):
        return {"REACT_ENABLED": True, "REACT_L2_ENABLED": True}.get(key, default)


class SeaBattleLifecycleReactionTests(unittest.TestCase):
    def test_finishing_placement_emits_reaction(self):
        character = _Character()
        game = SeaBattleGame(character)

        with patch("modules.SeaBattle.seabattle_instance.use", return_value=_Settings()):
            game._dispatch_placement_completed_reaction()

        self.assertEqual(len(character.event_bus.events), 1)
        _event, payload = character.event_bus.events[0]
        self.assertEqual(payload["event_type"], "react")
        self.assertIn("finished placing all ships", payload["system_input"])

    def test_closing_window_emits_reaction(self):
        character = _Character()
        game = SeaBattleGame(character)

        with patch("modules.SeaBattle.seabattle_instance.use", return_value=_Settings()):
            game._dispatch_player_close_reaction()

        self.assertEqual(len(character.event_bus.events), 1)
        _event, payload = character.event_bus.events[0]
        self.assertIn("closed the Sea Battle game window", payload["system_input"])


if __name__ == "__main__":
    unittest.main()
