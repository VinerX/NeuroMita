"""Regression tests for mini-games started from the desktop settings panel."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.game_manager import GameManager


class _EventBus:
    def __init__(self) -> None:
        self.events = []

    def emit(self, name, payload) -> None:
        self.events.append((name, payload))


class _Character:
    char_id = "Mita"

    def __init__(self) -> None:
        self.event_bus = _EventBus()


class _Settings:
    def __init__(self, **values) -> None:
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class ManualGameLaunchTests(unittest.TestCase):
    def test_launch_emits_l2_reaction_when_game_requests_are_accepted(self) -> None:
        character = _Character()
        manager = GameManager(character)
        settings = _Settings(
            IGNORE_GAME_REQUESTS=False,
            REACT_ENABLED=True,
            REACT_L2_ENABLED=True,
        )

        with patch.object(manager, "start_game", return_value=True) as start_game:
            with patch("managers.game_manager.use", return_value=settings):
                self.assertTrue(manager.start_game_from_player("chess"))

        start_game.assert_called_once_with("chess")
        self.assertEqual(len(character.event_bus.events), 1)
        _name, payload = character.event_bus.events[0]
        self.assertEqual(payload["event_type"], "react")
        self.assertEqual(payload["policy"]["react_level"], 2)
        self.assertIn("chess", payload["system_input"])

    def test_launch_does_not_react_when_game_requests_are_muted(self) -> None:
        character = _Character()
        manager = GameManager(character)
        settings = _Settings(
            IGNORE_GAME_REQUESTS=True,
            REACT_ENABLED=True,
            REACT_L2_ENABLED=True,
        )

        with patch.object(manager, "start_game", return_value=True):
            with patch("managers.game_manager.use", return_value=settings):
                self.assertTrue(manager.start_game_from_player("seabattle"))

        self.assertEqual(character.event_bus.events, [])


if __name__ == "__main__":
    unittest.main()
