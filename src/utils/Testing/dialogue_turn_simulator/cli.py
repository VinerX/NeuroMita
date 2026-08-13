from __future__ import annotations

import argparse
import json
import threading
from typing import Sequence

from .core import DialogueSimulation, SimulatedMita
from .protocol import UnityClientEndpoint, UnityProtocolClient, wait_until


def run_self_test() -> int:
    simulation = DialogueSimulation([
        SimulatedMita("Crazy", "Crazy", order_points=30),
        SimulatedMita("Kind", "Kind", order_points=20),
        SimulatedMita("Cappie", "Cappie", order_points=10),
    ], seed=3)
    full_response = "Kind, what do you think? One more thing, Kind. Cappie, do you agree?"
    address_map = (
        ("Kind", "Kind, what do you think?"),
        ("Kind", "One more thing, Kind."),
        ("Cappie", "Cappie, do you agree?"),
    )

    player_turn = simulation.prepare_player_turn("Question for everyone")
    simulation.enqueue_addressed_segments(
        address_map,
        source_id=player_turn.speaker_id,
        full_response=full_response,
        address_map=address_map,
        reset_pending=True,
    )
    simulation.complete_turn(player_turn, full_response, plan_follow_up=False)
    simulation.plan_follow_up(player_turn.speaker_id, from_player=True)
    first_addressed = simulation.prepare_automatic_turn(simulation.last_response)

    simulation.complete_turn(first_addressed, "Kind answer", plan_follow_up=False)
    simulation.plan_follow_up(first_addressed.speaker_id, from_player=False)
    second_addressed = simulation.prepare_automatic_turn(simulation.last_response)
    simulation.complete_turn(second_addressed, "Cappie answer", plan_follow_up=False)
    simulation.plan_follow_up(second_addressed.speaker_id, from_player=False)

    zero_limit = DialogueSimulation([
        SimulatedMita("Crazy", "Crazy", order_points=10),
        SimulatedMita("Kind", "Kind", order_points=5),
    ])
    zero_limit.policy.auto_dialogue_enabled = False
    zero_turn = zero_limit.prepare_player_turn("One answer only")
    zero_limit.complete_turn(zero_turn, "Done")

    checks = {
        "initial_speaker": player_turn.speaker_id == "Crazy",
        "addressed_order": [first_addressed.speaker_id, second_addressed.speaker_id] == ["Kind", "Cappie"],
        "duplicate_target_collapsed": first_addressed.addressed_message == (
            "Kind, what do you think? One more thing, Kind."
        ),
        "three_turn_limit_stops": (
            simulation.chain_turn_count == 3
            and simulation.pending_speaker_id == ""
            and simulation.stop_reason == "Достигнут максимум ходов в цепочке: 3"
        ),
        "full_context_preserved": (
            first_addressed.full_response == full_response
            and second_addressed.full_response == full_response
        ),
        "address_map_preserved": (
            first_addressed.address_map == address_map
            and second_addressed.address_map == address_map
        ),
        "disabled_auto_dialogue_stops": zero_limit.pending_speaker_id == "",
    }
    passed = all(checks.values())
    print(json.dumps({
        "status": "ok" if passed else "failed",
        "checks": checks,
        "expected_addressed_order": ["Kind", "Cappie"],
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def probe_server(host: str, port: int, timeout: float) -> int:
    connected = threading.Event()
    settings_received = threading.Event()
    messages: list[dict] = []
    states: list[str] = []

    def on_message(message: dict) -> None:
        messages.append(message)
        if str(message.get("type") or "") == "loaded_settings":
            settings_received.set()

    def on_state(is_connected: bool, message: str) -> None:
        states.append(message)
        if is_connected:
            connected.set()

    client = UnityProtocolClient(
        UnityClientEndpoint(
            host=host,
            port=port,
            reconnect_delay_seconds=max(timeout, 0.1),
            connect_timeout_seconds=min(max(timeout, 0.1), 5.0),
        ),
        on_message=on_message,
        on_state=on_state,
    )
    client.start()
    try:
        connected_ok = wait_until(connected.is_set, timeout)
        settings_ok = connected_ok and wait_until(settings_received.is_set, timeout)
    finally:
        client.stop()

    print(json.dumps({
        "status": "ok" if connected_ok and settings_ok else "failed",
        "endpoint": f"{host}:{port}",
        "connected": connected_ok,
        "loaded_settings_received": settings_ok,
        "message_types": [str(message.get("type") or "") for message in messages],
        "states": states,
    }, ensure_ascii=False, indent=2))
    return 0 if connected_ok and settings_ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeuroMita headless Unity dialogue client")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("self-test", help="Run deterministic routing checks without a server")
    probe = subparsers.add_parser("probe", help="Check persistent TCP handshake and loaded settings")
    probe.add_argument("--host", default="127.0.0.1")
    probe.add_argument("--port", type=int, default=12345)
    probe.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args(argv)
    if args.command == "self-test":
        return run_self_test()
    if args.command == "probe":
        return probe_server(args.host, args.port, max(0.1, args.timeout))

    from .window import run

    return run()
