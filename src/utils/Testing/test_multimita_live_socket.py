"""Live socket scenario for the Unity multi-Mita dialogue pipeline.

Run only against the normal game/Python boot, never against a production server.
The request mirrors NetworkController.SendCreateTaskAsync and emulates a player
addressing Kind while Crazy is a nearby eligible participant.
"""
from __future__ import annotations

import argparse
import json
import socket
import uuid


def build_player_turn() -> dict:
    request_id = f"dialogue-test-{uuid.uuid4().hex}"
    return {
        "action": "create_task",
        "type": "answer",
        "character": "Kind",
        "sender": "Player",
        "participants": ["Kind", "Crazy"],
        "origin_message_id": None,
        "req_id": request_id,
        "data": {
            "message": "Добрая, Безумная рядом. Спроси её прямо: почему она здесь?"
        },
        "context": {
            "dialogue": {
                "conversation_id": "conv_live_multimita_test",
                "epoch": 1,
                "turn_index": 1,
                "speaker_actor_id": "Player",
                "responder_actor_id": "actor_kind_test_01",
                "world_id": "crazy_house",
                "room_id": "kitchen",
                "participants": [
                    {
                        "actor_id": "actor_kind_test_01",
                        "character_id": "Kind",
                        "display_name": "Kind Mita",
                        "world_id": "crazy_house",
                        "room_id": "kitchen",
                        "distance_to_player": 2.0,
                        "is_active": True,
                        "can_hear_player": True,
                        "can_hear_speaker": True,
                        "can_speak": True,
                        "presence_reason": "directly_addressed",
                    },
                    {
                        "actor_id": "actor_crazy_test_01",
                        "character_id": "Crazy",
                        "display_name": "Crazy Mita",
                        "world_id": "crazy_house",
                        "room_id": "kitchen",
                        "distance_to_player": 3.0,
                        "is_active": True,
                        "can_hear_player": True,
                        "can_hear_speaker": True,
                        "can_speak": True,
                        "presence_reason": "within_hearing_range",
                    },
                ],
            }
        },
    }


def build_game_master_turn(command: str) -> dict:
    """Build a three-Mita moderator task against the normal socket server."""
    payload = build_player_turn()
    payload["type"] = "game_master_observe"
    payload["character"] = "GameMaster"
    payload["sender"] = "Kind"
    payload["participants"] = ["Kind", "Crazy", "Cappie"]
    payload["data"] = {
        "message": f"[INSTRUCTION] {command.strip()}\n[/INSTRUCTION]"
    }
    dialogue = payload["context"]["dialogue"]
    dialogue["responder_actor_id"] = ""
    dialogue["participants"].append(
        {
            "actor_id": "actor_cappie_test_01",
            "character_id": "Cappie",
            "display_name": "Cappie",
            "world_id": "crazy_house",
            "room_id": "kitchen",
            "distance_to_player": 3.5,
            "is_active": True,
            "can_hear_player": True,
            "can_hear_speaker": True,
            "can_speak": True,
            "presence_reason": "within_hearing_range",
        }
    )
    return payload

def decode_messages(raw: str) -> list[dict]:
    decoder = json.JSONDecoder()
    messages: list[dict] = []
    position = 0
    while position < len(raw):
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw):
            break
        try:
            message, position = decoder.raw_decode(raw, position)
        except json.JSONDecodeError:
            break
        messages.append(message)
    return messages


def has_terminal_task_update(messages: list[dict]) -> bool:
    terminal_statuses = {"SUCCESS", "FAILED", "ABORTED", "CANCELLED"}
    return any(
        message.get("type") == "task_update"
        and str(message.get("status", "")) in terminal_statuses
        for message in messages
    )


def exchange(host: str, port: int, payload: dict, timeout: float) -> list[dict]:
    with socket.create_connection((host, port), timeout=timeout) as client:
        client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            try:
                part = client.recv(65536)
            except socket.timeout:
                break
            if not part:
                break
            chunks.append(part)
            messages = decode_messages(b"".join(chunks).decode("utf-8"))
            if has_terminal_task_update(messages):
                return messages
    return decode_messages(b"".join(chunks).decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--game-master-command", default="", help="Run a three-Mita GameMaster directive request.")
    parser.add_argument("--expect-broadcast", default="", help="Expected text in the GameMaster broadcast intent.")
    args = parser.parse_args()

    payload = build_game_master_turn(args.game_master_command) if args.game_master_command.strip() else build_player_turn()
    print("REQUEST")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    responses = exchange(args.host, args.port, payload, args.timeout)
    for index, response in enumerate(responses, start=1):
        print(f"RESPONSE {index}/{len(responses)}")
        print(json.dumps(response, ensure_ascii=False, indent=2))

    task_updates = [message for message in responses if message.get("type") == "task_update"]
    if not task_updates:
        print("TEST FAILED: server did not return task_update")
        return 2

    final = task_updates[-1]
    status = str(final.get("status", ""))
    error = str(final.get("body", {}).get("error", ""))
    if status != "SUCCESS":
        print(f"TEST FAILED: task status={status}; error={error or 'not provided'}")
        return 2

    if args.expect_broadcast:
        result = final.get("body", {}).get("result", {})
        broadcast_messages = [
            str(intent.get("payload", {}).get("message") or "")
            for segment in result.get("segments", [])
            if isinstance(segment, dict)
            for intent in segment.get("intents", [])
            if isinstance(intent, dict) and intent.get("type") == "dialogue.broadcast_system_message"
        ]
        if not any(args.expect_broadcast.casefold() in message.casefold() for message in broadcast_messages):
            print("TEST FAILED: GameMaster broadcast payload lacks the expected directive text")
            return 3
        print("TEST PASSED: GameMaster produced the expected broadcast directive")
        return 0

    print("TEST PASSED: player-like dialogue request completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





