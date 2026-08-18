from __future__ import annotations

import threading

from controllers.chat_controller import ChatController
from services.contracts import PlayerMessageSource, parse_player_message_source


def _controller() -> ChatController:
    controller = object.__new__(ChatController)
    controller._player_message_source_lock = threading.Lock()
    controller._last_player_message_source = PlayerMessageSource.NONE
    return controller


def test_source_parser_accepts_transport_aliases():
    assert parse_player_message_source("python") is PlayerMessageSource.APPLICATION
    assert parse_player_message_source("application") is PlayerMessageSource.APPLICATION
    assert parse_player_message_source("unity") is PlayerMessageSource.GAME
    assert parse_player_message_source("game") is PlayerMessageSource.GAME
    assert parse_player_message_source(None) is PlayerMessageSource.NONE


def test_first_source_establishes_baseline_without_change_marker():
    current, previous = _controller()._resolve_player_message_source_transition("application")

    assert current is PlayerMessageSource.APPLICATION
    assert previous is PlayerMessageSource.NONE


def test_switch_between_application_and_game_is_detected_once():
    controller = _controller()

    assert controller._resolve_player_message_source_transition("application") == (
        PlayerMessageSource.APPLICATION,
        PlayerMessageSource.NONE,
    )
    assert controller._resolve_player_message_source_transition("game") == (
        PlayerMessageSource.GAME,
        PlayerMessageSource.APPLICATION,
    )
    assert controller._resolve_player_message_source_transition("game") == (
        PlayerMessageSource.GAME,
        PlayerMessageSource.NONE,
    )
    assert controller._resolve_player_message_source_transition("application") == (
        PlayerMessageSource.APPLICATION,
        PlayerMessageSource.GAME,
    )


def test_background_request_without_source_does_not_move_player_source():
    controller = _controller()
    controller._resolve_player_message_source_transition("application")

    assert controller._resolve_player_message_source_transition(None) == (
        PlayerMessageSource.NONE,
        PlayerMessageSource.NONE,
    )
    assert controller._resolve_player_message_source_transition("game") == (
        PlayerMessageSource.GAME,
        PlayerMessageSource.APPLICATION,
    )
