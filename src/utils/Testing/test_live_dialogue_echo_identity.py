from __future__ import annotations

from characters import (
    Cappie,
    CrazyMita,
    CreepyMita,
    GameMaster,
    GhostMita,
    KindMita,
    MilaMita,
    ShortHairMita,
    SleepyMita,
)
from controllers.server_controller import ServerController
from core.events import Event, Events
from domain.dialogue_identity import DialogueActorKind


class _EventBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, name: str, data: dict) -> None:
        self.emitted.append((name, dict(data)))


class _EchoSuppressor:
    def should_echo_incoming(self, **kwargs) -> bool:
        return True


def _controller() -> tuple[ServerController, _EventBus]:
    controller = object.__new__(ServerController)
    controller._destroyed = False
    controller.echo_suppressor = _EchoSuppressor()
    controller.event_bus = _EventBus()
    return controller, controller.event_bus


def test_character_classes_expose_dialogue_kind_without_per_mita_duplication() -> None:
    for character_cls in (
        Cappie,
        CrazyMita,
        CreepyMita,
        GhostMita,
        KindMita,
        MilaMita,
        ShortHairMita,
        SleepyMita,
    ):
        assert character_cls.dialogue_actor_kind is DialogueActorKind.CHARACTER

    assert GameMaster.dialogue_actor_kind is DialogueActorKind.GAME_MASTER


def test_live_echo_boundary_accepts_only_resolved_player_kind() -> None:
    controller, event_bus = _controller()

    controller._on_echo_chat_message_requested(
        Event(
            Events.Server.ECHO_CHAT_MESSAGE_REQUESTED,
            {
                "client_id": "client-1",
                "sender": "Player",
                "sender_kind": DialogueActorKind.UNKNOWN,
                "text": "Mita relay incorrectly carrying Player fallback",
            },
        )
    )

    assert event_bus.emitted == []


def test_live_echo_boundary_projects_resolved_player_as_user() -> None:
    controller, event_bus = _controller()

    controller._on_echo_chat_message_requested(
        Event(
            Events.Server.ECHO_CHAT_MESSAGE_REQUESTED,
            {
                "client_id": "client-1",
                "sender": "Player",
                "sender_kind": DialogueActorKind.PLAYER,
                "text": "Actual player line",
                "message_id": "request-1",
            },
        )
    )

    assert event_bus.emitted == [
        (
            Events.GUI.UPDATE_CHAT_UI,
            {
                "role": "user",
                "response": "Actual player line",
                "is_initial": False,
                "emotion": "",
                "speaker_name": "",
            },
        )
    ]
