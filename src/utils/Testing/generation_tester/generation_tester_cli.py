#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from generation_tester_core import (  # noqa: E402
    GenerationScenario,
    GenerationTestRuntime,
    GenerationTurn,
    save_run_artifacts,
)


def _compact_turn_result(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return item
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    token_stats = item.get("token_stats") if isinstance(item.get("token_stats"), dict) else {}
    last_ctx = item.get("last_request_context") if isinstance(item.get("last_request_context"), dict) else {}
    usage = last_ctx.get("usage") if isinstance(last_ctx.get("usage"), dict) else {}
    return {
        "character_id": item.get("character_id"),
        "preset_id": item.get("preset_id"),
        "event_type": ((item.get("input") or {}).get("event_type") if isinstance(item.get("input"), dict) else None),
        "user_input": ((item.get("input") or {}).get("user_input") if isinstance(item.get("input"), dict) else None),
        "response_text": result.get("text"),
        "message_id": result.get("message_id"),
        "response_model": last_ctx.get("response_model"),
        "response_provider_name": last_ctx.get("response_provider_name"),
        "actual_prompt_tokens": token_stats.get("actual_prompt_tokens"),
        "actual_completion_tokens": token_stats.get("actual_completion_tokens"),
        "actual_total_tokens": token_stats.get("actual_total_tokens"),
        "actual_cached_prompt_tokens": token_stats.get("actual_cached_prompt_tokens"),
        "cache_write_tokens": usage.get("cache_write_tokens"),
        "cost": usage.get("cost"),
        "cost_source": usage.get("cost_source"),
    }


def _configure_logging(verbose: bool) -> None:
    if verbose:
        return
    try:
        from main_logger import logger as app_logger
        app_logger.setLevel(logging.ERROR)
        for handler in list(getattr(app_logger, "handlers", []) or []):
            handler.setLevel(logging.ERROR)
    except Exception:
        pass
    try:
        logging.getLogger().setLevel(logging.ERROR)
    except Exception:
        pass


def _print_json(data, output: str | None = None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written to {output}", file=sys.stderr)
        return
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def _default_output_dir(name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / ".generation_tester_runs" / f"{stamp}_{name}"


def _runtime_from_args(args, *, character_id: str | None = None) -> GenerationTestRuntime:
    if not getattr(args, "base_dir", None):
        raise ValueError("--base-dir is required for this command")
    return GenerationTestRuntime(
        source_base_dir=args.base_dir,
        live_mode=bool(args.live),
        sandbox_dir=args.sandbox_dir,
        prompts_dir=args.prompts_dir,
        histories_dir=args.histories_dir,
        character_id=character_id,
    )


def cmd_template(args) -> None:
    scenario = GenerationScenario.template()
    sys.stdout.buffer.write(scenario.to_pretty_json().encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def cmd_inspect_last(args) -> None:
    runtime = _runtime_from_args(args)
    try:
        payload = runtime.read_last_request_context()
        _print_json(payload, args.output)
    finally:
        runtime.close()


def cmd_inspect_input(args) -> None:
    runtime = _runtime_from_args(args)
    try:
        payload = runtime.read_last_generation_input()
        _print_json(payload, args.output)
    finally:
        runtime.close()


def cmd_replay_last(args) -> None:
    runtime = _runtime_from_args(args, character_id=args.character)
    try:
        result = runtime.replay_last_request(
            preset=args.preset,
            character_id=args.character,
        )
        output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir("replay_last")
        save_run_artifacts(output_dir=output_dir, summary=result, turn_results=[result])
        summary = {
            "mode": "replay-last",
            "character_id": result.get("character_id"),
            "preset_id": result.get("preset_id"),
            "message_count": result.get("message_count"),
            "response_model": result.get("response_model"),
            "response_provider": result.get("response_provider"),
            "usage": result.get("usage"),
            "artifacts_dir": str(output_dir),
            "runtime_base_dir": str(runtime.runtime_base_dir),
        }
        _print_json(summary, args.output)
    finally:
        runtime.close()


def cmd_replay_input(args) -> None:
    runtime = _runtime_from_args(args)
    try:
        result = runtime.replay_last_generation_input(timeout=float(args.timeout))
        output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir("replay_input")
        save_run_artifacts(output_dir=output_dir, summary=result, turn_results=[result])
        summary = {
            "mode": "replay-input",
            "character_id": result.get("character_id"),
            "preset_id": result.get("preset_id"),
            "response_model": ((result.get("last_request_context") or {}).get("response_model") if isinstance(result.get("last_request_context"), dict) else None),
            "response_provider": ((result.get("last_request_context") or {}).get("response_provider_name") if isinstance(result.get("last_request_context"), dict) else None),
            "usage": ((result.get("last_request_context") or {}).get("usage") if isinstance(result.get("last_request_context"), dict) else None),
            "artifacts_dir": str(output_dir),
            "runtime_base_dir": str(runtime.runtime_base_dir),
        }
        _print_json(summary, args.output)
    finally:
        runtime.close()


def cmd_chat(args) -> None:
    runtime = _runtime_from_args(args, character_id=args.character)
    try:
        participants = []
        if args.participants:
            participants = [p.strip() for p in args.participants.split(",") if p.strip()]
        turn = GenerationTurn(
            user_input=args.message,
            system_input=args.system_input or "",
            event_type=args.event_type,
            sender=args.sender,
            participants=participants,
            preset=args.preset,
            character_id=args.character,
            disable_history_compression=bool(args.disable_history_compression),
        )

        turn_results = []
        for _ in range(max(1, int(args.repeat))):
            item = runtime.generate_turn(
                turn,
                default_character_id=args.character,
                default_preset=args.preset,
                timeout=float(args.timeout),
            )
            turn_results.append(item)

        output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir("chat")
        summary = {
            "mode": "chat",
            "character_id": args.character,
            "preset": args.preset,
            "repeat": int(args.repeat),
            "runtime_base_dir": str(runtime.runtime_base_dir),
            "artifacts_dir": str(output_dir),
            "last_turn": _compact_turn_result(turn_results[-1]) if turn_results else None,
        }
        save_run_artifacts(output_dir=output_dir, summary=summary, turn_results=turn_results)
        _print_json(summary, args.output)
    finally:
        runtime.close()


def cmd_scenario(args) -> None:
    with open(args.scenario, "r", encoding="utf-8") as f:
        scenario = GenerationScenario.from_dict(json.load(f))

    runtime = _runtime_from_args(args, character_id=scenario.character_id)
    try:
        turn_results = []
        for turn in scenario.turns:
            item = runtime.generate_turn(
                turn,
                default_character_id=scenario.character_id,
                default_preset=scenario.preset,
                timeout=float(args.timeout),
            )
            turn_results.append(item)

        output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(scenario.name)
        summary = {
            "mode": "scenario",
            "scenario_name": scenario.name,
            "character_id": scenario.character_id,
            "preset": scenario.preset,
            "turn_count": len(turn_results),
            "runtime_base_dir": str(runtime.runtime_base_dir),
            "artifacts_dir": str(output_dir),
            "last_turn": _compact_turn_result(turn_results[-1]) if turn_results else None,
        }
        save_run_artifacts(output_dir=output_dir, summary=summary, turn_results=turn_results)
        _print_json(summary, args.output)
    finally:
        runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Headless generation tester for NeuroMita runtime pipeline",
    )
    parser.add_argument("--base-dir", default=None, help="Path to NeuroMita base directory")
    parser.add_argument("--live", action="store_true", help="Run directly on live data instead of sandbox copy")
    parser.add_argument("--sandbox-dir", default=None, help="Optional explicit sandbox directory")
    parser.add_argument("--prompts-dir", default=None, help="Optional prompts directory override")
    parser.add_argument("--histories-dir", default=None, help="Optional histories directory override")
    parser.add_argument("--output", default=None, help="Write final JSON summary to file")
    parser.add_argument("--output-dir", default=None, help="Directory for detailed run artifacts")
    parser.add_argument("--verbose", action="store_true", help="Keep runtime logs enabled")

    sub = parser.add_subparsers(dest="command", required=True)

    p_template = sub.add_parser("template", help="Print example scenario JSON")
    p_template.set_defaults(func=cmd_template)

    p_inspect = sub.add_parser("inspect-last", help="Print last_request_context.json from runtime base")
    p_inspect.set_defaults(func=cmd_inspect_last)

    p_inspect_input = sub.add_parser("inspect-input", help="Print last_generation_input.json from runtime base")
    p_inspect_input.set_defaults(func=cmd_inspect_input)

    p_replay = sub.add_parser("replay-last", help="Replay messages from last_request_context.json via current preset")
    p_replay.add_argument("--character", default=None, help="Optional character id override")
    p_replay.add_argument("--preset", default=None, help="Optional preset id or preset name override")
    p_replay.set_defaults(func=cmd_replay_last)

    p_replay_input = sub.add_parser("replay-input", help="Replay saved GENERATE_RESPONSE ingress via current runtime")
    p_replay_input.add_argument("--timeout", type=float, default=600.0, help="Replay timeout in seconds")
    p_replay_input.set_defaults(func=cmd_replay_input)

    p_chat = sub.add_parser("chat", help="Run one repeated chat turn through real GENERATE_RESPONSE pipeline")
    p_chat.add_argument("--character", required=True, help="Character id")
    p_chat.add_argument("--message", required=True, help="User message text")
    p_chat.add_argument("--system-input", default="", help="Extra system_input block")
    p_chat.add_argument("--event-type", default="chat", help="Model event type")
    p_chat.add_argument("--sender", default="Player", help="Sender name")
    p_chat.add_argument("--participants", default="", help="Comma-separated participants list")
    p_chat.add_argument("--preset", default=None, help="Preset id or preset name")
    p_chat.add_argument("--repeat", type=int, default=1, help="Repeat the same turn N times")
    p_chat.add_argument("--timeout", type=float, default=600.0, help="Per-turn timeout in seconds")
    p_chat.add_argument("--disable-history-compression", action="store_true", help="Disable history compression for this turn")
    p_chat.set_defaults(func=cmd_chat)

    p_scenario = sub.add_parser("scenario", help="Run a multi-turn scenario JSON")
    p_scenario.add_argument("--scenario", required=True, help="Path to scenario JSON file")
    p_scenario.add_argument("--timeout", type=float, default=600.0, help="Per-turn timeout in seconds")
    p_scenario.set_defaults(func=cmd_scenario)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _configure_logging(bool(getattr(args, "verbose", False)))
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
