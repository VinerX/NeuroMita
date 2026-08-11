from __future__ import annotations

from utils.Testing.dialogue_turn_simulator import (
    DialogueSimulation,
    MitaMode,
    SimulatedMita,
    UNITY_DIALOGUE_CHARACTER_IDS,
    create_default_simulation,
)


def _simulation() -> DialogueSimulation:
    return DialogueSimulation(
        [
            SimulatedMita("Crazy", "Crazy", order_points=30),
            SimulatedMita("Kind", "Kind", order_points=20),
            SimulatedMita("Cappie", "Cappie", order_points=10),
        ],
        seed=3,
    )


def test_default_roster_contains_every_unity_dialogue_mita() -> None:
    simulation = create_default_simulation()

    assert tuple(mita.character_id for mita in simulation.mitas) == UNITY_DIALOGUE_CHARACTER_IDS
    assert all(mita.enabled for mita in simulation.mitas)


def test_roster_excludes_disabled_and_distant_mitas() -> None:
    simulation = _simulation()
    simulation.get_mita("Kind").enabled = False
    simulation.get_mita("Cappie").distance = 26.0

    assert [item.character_id for item in simulation.active_mitas()] == ["Crazy"]


def test_player_turn_uses_highest_priority_and_builds_automatic_chain() -> None:
    simulation = _simulation()

    first = simulation.begin_player_turn("Начинаем")
    automatic = simulation.run_until_stop()

    assert first.speaker_id == "Crazy"
    assert [turn.speaker_id for turn in automatic] == ["Kind", "Cappie", "Crazy"]
    assert simulation.pending_speaker_id == ""
    assert simulation.stop_reason == "Лимит автоматических ходов исчерпан"


def test_disabled_auto_dialogue_stops_after_player_response() -> None:
    simulation = _simulation()
    simulation.auto_dialogue_enabled = False

    simulation.begin_player_turn("Только один ответ")

    assert simulation.pending_speaker_id == ""
    assert simulation.stop_reason == "Автодиалог выключен"


def test_set_next_speaker_promotes_available_mita() -> None:
    simulation = _simulation()

    simulation.set_next_speaker("Cappie")

    assert simulation.ordered_active_mitas()[0].character_id == "Cappie"


def test_mode_changes_simulated_response() -> None:
    simulation = _simulation()
    simulation.get_mita("Crazy").mode = MitaMode.HUNT

    result = simulation.begin_player_turn("Где игрок?")

    assert result.mode is MitaMode.HUNT
    assert "охот" in result.response


def test_single_mita_does_not_loop_into_itself() -> None:
    simulation = _simulation()
    simulation.get_mita("Kind").enabled = False
    simulation.get_mita("Cappie").enabled = False

    simulation.begin_player_turn("Ответь")

    assert simulation.pending_speaker_id == ""
    assert simulation.stop_reason == "Подходящий следующий собеседник не найден"
