from __future__ import annotations

from pathlib import Path

from controllers.chat_controller import ChatController


SRC_ROOT = Path(__file__).resolve().parents[2]


def test_python_production_tree_has_no_dialogue_turn_router() -> None:
    assert not (SRC_ROOT / "services" / "dialogue_turn_router.py").exists()
    production_roots = (SRC_ROOT / "controllers", SRC_ROOT / "services", SRC_ROOT / "game_connections")
    forbidden = ("DialogueTurnRouter", "get_dialogue_turn_router", "route_to_transport")

    for root in production_roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(symbol in source for symbol in forbidden), path


def test_task_result_never_schedules_a_follow_up_turn() -> None:
    result = ChatController._build_task_result(
        "Ответ",
        "Player",
        {"segments": [{"text": "Ответ", "target": "Player", "intents": []}]},
        [],
        structured_parse_level="direct",
        control_plane_trusted=True,
    )

    assert "next_turns" not in result


def test_game_master_semantic_intent_survives_without_python_routing() -> None:
    intent = {
        "type": "dialogue.broadcast_system_message",
        "payload": {"message": "Смените тему разговора."},
    }
    result = ChatController._build_task_result(
        " ",
        "Player",
        {"segments": [{"text": " ", "target": "Player", "intents": [intent]}]},
        [],
        structured_parse_level="direct",
        control_plane_trusted=True,
    )

    assert result["segments"][0]["intents"] == [intent]
    assert "next_turns" not in result
