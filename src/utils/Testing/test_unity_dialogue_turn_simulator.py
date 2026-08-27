from __future__ import annotations

import json
import socket
import threading

from utils.Testing.dialogue_turn_simulator import (
    DialoguePolicy,
    DialogueSimulation,
    MitaMode,
    SimulatedMita,
    UNITY_DIALOGUE_CHARACTER_IDS,
    UnityClientEndpoint,
    UnityLikeDialogueSession,
    UnityProtocolClient,
    create_default_simulation,
)
from utils.Testing.dialogue_turn_simulator.protocol import wait_until
from utils.Testing.dialogue_turn_simulator.cli import probe_server, run_self_test


class _FakeTransport:
    connected = True

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, payload: dict) -> None:
        self.sent.append(payload)


def _simulation() -> DialogueSimulation:
    return DialogueSimulation(
        [
            SimulatedMita("Crazy", "Crazy", order_points=30),
            SimulatedMita("Kind", "Kind", order_points=20),
            SimulatedMita("Cappie", "Cappie", order_points=10),
        ],
        seed=3,
    )


def _success(request: dict, response: str, segments: list[dict] | None = None) -> dict:
    return {
        "type": "task_update",
        "status": "SUCCESS",
        "uid": f"task-{request['req_id']}",
        "body": {
            "uid": f"task-{request['req_id']}",
            "status": "SUCCESS",
            "data": {"req_id": request["req_id"]},
            "result": {
                "response_protocol_version": 3,
                "response": response,
                "segments": segments or [{"text": response, "intents": []}],
            },
        },
    }


def test_default_roster_contains_every_unity_dialogue_mita() -> None:
    simulation = create_default_simulation()

    assert tuple(mita.character_id for mita in simulation.mitas) == UNITY_DIALOGUE_CHARACTER_IDS
    assert all(mita.enabled for mita in simulation.mitas)


def test_cli_self_test_covers_addressed_order_and_disabled_auto_dialogue(capsys) -> None:
    assert run_self_test() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["expected_addressed_order"] == ["Kind", "Cappie"]
    assert all(report["checks"].values())


def test_cli_probe_verifies_handshake_and_loaded_settings(capsys) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            stream = connection.makefile("r", encoding="utf-8", newline="\n")
            json.loads(stream.readline())
            json.loads(stream.readline())
            connection.sendall(
                b'{"type":"loaded_settings","body":{"settings":{},"settings_revision":1}}\n'
            )
            while connection.recv(1024):
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert probe_server("127.0.0.1", port, 2.0) == 0
    finally:
        listener.close()
        thread.join(timeout=2.0)

    report = json.loads(capsys.readouterr().out)
    assert report["connected"] is True
    assert report["loaded_settings_received"] is True


def test_roster_excludes_disabled_and_distant_mitas() -> None:
    simulation = _simulation()
    simulation.get_mita("Kind").enabled = False
    simulation.get_mita("Cappie").distance = 26.0

    assert [item.character_id for item in simulation.active_mitas()] == ["Crazy"]


def test_policy_uses_real_server_settings() -> None:
    policy = DialoguePolicy()
    policy.apply_server_payload({
        "body": {
            "settings_revision": 42,
            "settings": {
                "MITA_DIALOGUE_AUTO": True,
                "DIALOGUE_MAX_CHAIN_TURNS": 4,
                "DIALOGUE_MAX_CONTINUES": 5,
                "GM_ON": True,
                "GM_REPEAT": 7,
            },
        }
    })

    assert policy.max_chain_turns == 4
    assert policy.chain_turn_limit() == 4
    assert policy.max_continues == 5
    assert policy.game_master_enabled is True
    assert policy.game_master_repeat == 7
    assert policy.settings_revision == 42


def test_unaddressed_response_is_a_leaf_even_when_other_mitas_are_active() -> None:
    simulation = _simulation()
    first = simulation.prepare_player_turn("Начинаем")
    simulation.complete_turn(first, "Ответ Crazy")

    assert first.speaker_id == "Crazy"
    assert simulation.pending_speaker_id == ""
    assert simulation.stop_reason == "Нет адресованных сегментов — цепочка завершена"


def test_player_mention_selects_target_and_autosolver_is_the_fallback() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("@Cappie Ответь первой")
    mentioned = transport.sent[-1]

    assert mentioned["character"] == "Cappie"
    assert mentioned["data"]["message"] == "Ответь первой"

    session.reset()
    session.submit_player_message("Ответь та, кого выберет автосолвер")
    assert transport.sent[-1]["character"] == "Crazy"


def test_chain_limit_one_allows_only_the_initial_mita_reply() -> None:
    simulation = _simulation()
    simulation.policy.max_chain_turns = 1

    first = simulation.prepare_player_turn("Один ответ")
    simulation.enqueue_addressed_segments(
        [("Kind", "Ответь")],
        source_id="Crazy",
        full_response="Kind, ответь",
        address_map=(("Kind", "Ответь"),),
        reset_pending=True,
    )
    simulation.complete_turn(first, "Готово")

    assert simulation.pending_speaker_id == ""
    assert simulation.stop_reason == "Достигнут максимум ходов в цепочке: 1"


def test_session_sends_real_create_task_and_owns_follow_up() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    events = []
    session = UnityLikeDialogueSession(simulation, transport, on_event=events.append)

    session.submit_player_message("Привет")
    player_request = transport.sent[-1]
    session.handle_server_message(_success(player_request, "Kind, привет", [{
        "text": "Kind, привет",
        "target": "Kind",
        "intents": [],
    }]))

    auto_request = transport.sent[-1]
    assert player_request["action"] == "create_task"
    assert player_request["type"] == "answer"
    assert player_request["character"] == "Crazy"
    assert player_request["origin_message_id"] is None
    assert "client_role" not in player_request
    assert "dialogue" not in player_request["context"]
    assert set(player_request["context"]) == {
        "distance",
        "roomPlayer",
        "roomMita",
        "world_state",
        "runtime_rules",
        "runtime_static_catalog",
        "runtime_capabilities",
        "intent_rules",
        "runtime_events",
        "image_base64_list",
    }
    assert auto_request["type"] == "react"
    assert auto_request["character"] == "Kind"
    assert "reason_content" in auto_request["data"]


def test_addressed_mitas_are_answered_in_model_order_by_client_router() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Вопрос всем")
    first = transport.sent[-1]
    first_success = _success(first, "Kind и Cappie, ответьте", [
        {"text": "Kind, что ты думаешь?", "target": "Kind", "intents": []},
        {"text": "Cappie, а ты согласна?", "target": "Cappie", "intents": []},
    ])
    session.handle_server_message(first_success)

    kind_request = transport.sent[-1]
    assert kind_request["character"] == "Kind"
    kind_reason = kind_request["data"]["reason_content"]
    assert "<FULL_REPLY>Kind, что ты думаешь? Cappie, а ты согласна?</FULL_REPLY>" in kind_reason
    assert "- Segment 1 to Kind:" in kind_reason
    assert "- Segment 2 to Cappie:" in kind_reason
    assert "The segment addressed specifically to you is: <Kind, что ты думаешь?>" in kind_reason
    assert "Segments addressed to other recipients are context only" in kind_reason

    session.handle_server_message(_success(kind_request, "Ответ Kind"))
    cappie_request = transport.sent[-1]
    assert cappie_request["character"] == "Cappie"
    cappie_reason = cappie_request["data"]["reason_content"]
    assert "<FULL_REPLY>Kind, что ты думаешь? Cappie, а ты согласна?</FULL_REPLY>" in cappie_reason
    assert "The segment addressed specifically to you is: <Cappie, а ты согласна?>" in cappie_reason


def test_repeated_target_segments_collapse_to_one_turn_in_original_target_order() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Question")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Two questions for Kind", [
        {"text": "First question", "target": "Kind", "intents": []},
        {"text": "Second question", "target": "Kind", "intents": []},
        {"text": "Question for Cappie", "target": "Cappie", "intents": []},
    ]))

    first_kind = transport.sent[-1]
    assert first_kind["character"] == "Kind"
    assert "specifically to you is: <First question Second question>" in first_kind["data"]["reason_content"]

    session.handle_server_message(_success(first_kind, "First answer"))
    assert transport.sent[-1]["character"] == "Cappie"


def test_simulated_modes_change_only_unity_runtime_context() -> None:
    simulation = _simulation()
    crazy = simulation.get_mita("Crazy")
    crazy.mode = MitaMode.HUNT
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Where are you?")
    context = transport.sent[-1]["context"]

    assert crazy.is_available is True
    assert "hunting" in context["world_state"]
    assert context["runtime_events"] == ["Simulator character mode: hunt."]


def test_session_rejects_missing_response_protocol_version() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    events = []
    session = UnityLikeDialogueSession(simulation, transport, on_event=events.append)

    session.submit_player_message("Hello")
    request = transport.sent[-1]
    update = _success(request, "Answer")
    del update["body"]["result"]["response_protocol_version"]
    session.handle_server_message(update)

    assert len(transport.sent) == 1
    assert events[-1].kind == "error"
    assert "expected 3" in events[-1].message


def test_addressed_turns_take_priority_over_game_master_observation() -> None:
    simulation = _simulation()
    simulation.policy.game_master_enabled = True
    simulation.policy.game_master_repeat = 1
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Вопрос")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Kind, ответь", [{
        "text": "Kind, ответь",
        "target": "Kind",
        "intents": [],
    }]))

    assert transport.sent[-1]["type"] == "react"
    assert transport.sent[-1]["character"] == "Kind"


def test_legacy_top_level_targets_do_not_route_a_turn() -> None:
    simulation = _simulation()
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Привет")
    first = transport.sent[-1]
    success = _success(first, "Ответ без адресата")
    success["body"]["result"]["target"] = "Cappie"
    success["body"]["result"]["targets"] = ["Cappie"]
    session.handle_server_message(success)

    assert len(transport.sent) == 1
    assert simulation.pending_speaker_id == ""


def test_segment_target_does_not_override_disabled_auto_dialogue() -> None:
    simulation = _simulation()
    simulation.policy.auto_dialogue_enabled = False
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Привет")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Обращение", [{
        "text": "Cappie, ответь",
        "target": "Cappie",
        "intents": [],
    }]))

    assert len(transport.sent) == 1
    assert simulation.pending_speaker_id == ""


def test_segment_target_does_not_override_single_turn_chain_limit() -> None:
    simulation = _simulation()
    simulation.policy.max_chain_turns = 1
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Привет")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Обращение", [{
        "text": "Cappie, ответь",
        "target": "Cappie",
        "intents": [],
    }]))

    assert len(transport.sent) == 1
    assert simulation.pending_speaker_id == ""


def test_session_executes_continue_as_unity_intent_with_budget() -> None:
    simulation = _simulation()
    simulation.policy.max_continues = 1
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Продолжай")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Часть один", [{
        "text": "Часть один",
        "intents": [{"type": "dialogue.continue", "payload": {}}],
    }]))

    continuation = transport.sent[-1]
    assert continuation["type"] == "continue"
    assert continuation["character"] == "Crazy"

    session.handle_server_message(_success(continuation, "Kind, отвечай", [{
        "text": "Kind, отвечай",
        "target": "Kind",
        "intents": [],
    }]))
    assert transport.sent[-1]["type"] == "react"
    assert transport.sent[-1]["character"] == "Kind"


def test_session_schedules_game_master_before_next_mita() -> None:
    simulation = _simulation()
    simulation.policy.game_master_enabled = True
    simulation.policy.game_master_repeat = 1
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Начинай")
    first = transport.sent[-1]
    session.handle_server_message(_success(first, "Ответ"))
    game_master = transport.sent[-1]

    assert game_master["type"] == "game_master_observe"
    assert game_master["character"] == "GameMaster"

    sent_before_game_master_result = len(transport.sent)
    session.handle_server_message(_success(game_master, " ", [{
        "text": " ",
        "intents": [{
            "type": "dialogue.broadcast_system_message",
            "payload": {"message": "Смените тему"},
        }],
    }]))
    assert len(transport.sent) == sent_before_game_master_result
    assert simulation.pending_speaker_id == ""


def test_max_three_chain_uses_fifo_breadth_first_order() -> None:
    simulation = _simulation()
    simulation.policy.max_chain_turns = 3
    transport = _FakeTransport()
    session = UnityLikeDialogueSession(simulation, transport, on_event=lambda _event: None)

    session.submit_player_message("Crazy, спроси остальных")
    crazy = transport.sent[-1]
    session.handle_server_message(_success(crazy, "Сначала Cappie, затем Kind", [
        {"text": "Cappie, ответь", "target": "Cappie", "intents": []},
        {"text": "Kind, затем ты", "target": "Kind", "intents": []},
    ]))

    cappie = transport.sent[-1]
    assert cappie["character"] == "Cappie"
    session.handle_server_message(_success(cappie, "Crazy, подключись", [
        {"text": "Crazy, подключись", "target": "Crazy", "intents": []},
    ]))

    kind = transport.sent[-1]
    assert kind["character"] == "Kind"
    session.handle_server_message(_success(kind, "Crazy, теперь ты", [
        {"text": "Crazy, теперь ты", "target": "Crazy", "intents": []},
    ]))

    assert [request["character"] for request in transport.sent] == ["Crazy", "Cappie", "Kind"]
    assert simulation.chain_turn_count == 3
    assert simulation.stop_reason == "Достигнут максимум ходов в цепочке: 3"


def test_protocol_client_handshake_matches_server_wire_format() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    received: list[dict] = []
    messages: list[dict] = []

    def server() -> None:
        connection, _address = listener.accept()
        with connection, connection.makefile("rb") as stream:
            for _ in range(2):
                received.append(json.loads(stream.readline().decode("utf-8")))
            connection.sendall(b'{"type":"hello_ack","client_role":"game","owns_player_input":true}\n')
        listener.close()

    server_thread = threading.Thread(target=server, daemon=True)
    server_thread.start()
    client = UnityProtocolClient(
        UnityClientEndpoint(port=port, reconnect_delay_seconds=10),
        on_message=messages.append,
        on_state=lambda _connected, _message: None,
    )
    client.start()
    try:
        assert wait_until(lambda: len(messages) == 1)
    finally:
        client.stop()
        server_thread.join(timeout=2)

    assert received[0] == {"action": "hello", "client_role": "game"}
    assert received[1]["action"] == "get_settings"
    assert messages[0]["type"] == "hello_ack"
