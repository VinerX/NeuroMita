"""Tests for Unity target tracking used by desktop mini-game launch."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.game_link_service import DisconnectedGameLinkService, ServerGameLinkService
from ui.settings.game_settings import (
    _manual_game_button_text,
    _select_manual_game_character,
    _set_sandbox_current_character,
)


class _Character:
    def __init__(self, char_id, display_name=None):
        self.char_id = char_id
        self.display_name = display_name or char_id


class GameLinkTargetTests(unittest.TestCase):
    def test_server_game_link_tracks_and_clears_unity_target(self):
        service = ServerGameLinkService()

        service.set_connected(True)
        service.set_unity_target_character_id("Kind")
        self.assertEqual(service.unity_target_character_id(), "Kind")

        service.set_connected(False)
        self.assertEqual(service.unity_target_character_id(), "")

    def test_disconnected_game_link_has_no_unity_target(self):
        service = DisconnectedGameLinkService()
        self.assertEqual(service.unity_target_character_id(), "")

    def test_unity_character_is_the_default_launch_target(self):
        launcher = _Character("Crazy")
        unity = _Character("Kind")
        received = {}

        target = _select_manual_game_character(
            launcher,
            unity,
            lambda choices, preferred: received.update(choices=choices, preferred=preferred) or preferred,
        )

        self.assertIs(target, unity)
        self.assertEqual(received["preferred"], "Kind (Kind)")
        self.assertEqual(received["choices"], ["Kind (Kind)", "Crazy (Crazy)"])

    def test_launcher_character_can_be_selected_without_switching_registry(self):
        launcher = _Character("Crazy")
        unity = _Character("Kind")

        target = _select_manual_game_character(
            launcher,
            unity,
            lambda choices, _preferred: choices[1],
        )

        self.assertIs(target, launcher)

    def test_cancelled_target_selection_does_not_start_a_game(self):
        launcher = _Character("Crazy")
        unity = _Character("Kind")

        target = _select_manual_game_character(launcher, unity, lambda *_: None)

        self.assertIsNone(target)

    def test_button_identifies_sandbox_and_unity_targets(self):
        self.assertEqual(
            _manual_game_button_text("chess", "Crazy", "Kind"),
            "Шахматы: Crazy / Unity: Kind",
        )
        self.assertEqual(
            _manual_game_button_text("seabattle", "Crazy"),
            "Морской бой с Crazy",
        )

    def test_explicit_unity_target_switches_sandbox_by_character_event(self):
        from core.events import Events

        with patch("ui.settings.game_settings.get_event_bus") as get_bus:
            _set_sandbox_current_character("Kind")

        get_bus.return_value.emit.assert_called_once_with(
            Events.Character.SET_CURRENT,
            {"character_id": "Kind"},
        )


if __name__ == "__main__":
    unittest.main()
