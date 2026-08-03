from __future__ import annotations

import sys
import unittest
from pathlib import Path

from main_logger import logger as app_logger

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.dialogue_turn_router import (
    DialogueTurnRouter,
    ROUTE_GAME_MASTER,
    ROUTE_GAME_MASTER_DIRECTIVE,
    ROUTE_MITA_FOLLOW_UP,
)


class _Settings:
    revision = 42

    def __init__(self, **values):
        self.values = {
            "MITA_DIALOGUE_AUTO": True,
            "DIALOGUE_MAX_AUTO_TURNS": 6,
            "GM_ON": False,
            "GM_REPEAT": 2,
            "DIALOGUE_MAX_CONTINUES": 3,
            **values,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


def _context(*, current="actor-crazy", spoken=None, client=None, epoch=1):
    participants = [
        {"actor_id": "actor-crazy", "character_id": "Crazy", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-kind", "character_id": "Kind", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-cappie", "character_id": "Cappie", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-gm", "character_id": "GameMaster", "can_speak": True, "can_hear_speaker": True},
    ]
    payload = {
        "conversation_id": "conv-router",
        "epoch": epoch,
        "speaker_actor_id": "player",
        "responder_actor_id": current,
        "auto_turns_since_player": 0,
        "max_auto_turns": 6,
        "spoken_actor_ids": list(spoken or []),
        "participants": participants,
    }
    if client:
        payload.update(client)
    return payload


class DialogueTurnRouterTests(unittest.TestCase):
    def test_router_disabled_returns_no_turn(self):
        router = DialogueTurnRouter(_Settings(MITA_DIALOGUE_AUTO=False))
        self.assertIsNone(router.select_next_turn(_context()))

    def test_router_no_budget_returns_no_turn(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_AUTO_TURNS=0))
        self.assertIsNone(router.select_next_turn(_context()))

    def test_router_selects_next_actor_in_stable_order(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-crazy", spoken=["actor-crazy"]))
        self.assertEqual(route.route_kind, ROUTE_MITA_FOLLOW_UP)
        self.assertEqual(route.target_actor_id, "actor-kind")

    def test_router_prefers_unspoken_actor(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-crazy", spoken=["actor-crazy"]))
        self.assertEqual(route.target_actor_id, "actor-kind")

    def test_router_starts_new_round_when_everyone_spoke(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(
            current="actor-cappie",
            spoken=["actor-crazy", "actor-kind", "actor-cappie"],
        ))
        self.assertEqual(route.target_actor_id, "actor-crazy")

    def test_router_never_selects_current_responder(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-crazy", spoken=[]))
        self.assertNotEqual(route.target_actor_id, "actor-crazy")

    def test_router_returns_only_one_next_turn(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context())
        self.assertIsNotNone(route)

    def test_router_excludes_gamemaster(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-kind", spoken=["actor-kind", "actor-crazy", "actor-cappie"]))
        self.assertNotEqual(route.target_character_id, "GameMaster")

    def test_router_excludes_actor_without_hearing(self):
        context = _context()
        context["participants"][1]["can_hear_speaker"] = False
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(context)
        self.assertNotEqual(route.target_actor_id, "actor-kind")

    def test_router_excludes_actor_without_speaking(self):
        context = _context()
        context["participants"][1]["can_speak"] = False
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(context)
        self.assertNotEqual(route.target_actor_id, "actor-kind")

    def test_router_uses_server_setting_as_source_of_truth(self):
        router = DialogueTurnRouter(_Settings(MITA_DIALOGUE_AUTO=False))
        route = router.select_next_turn(_context(client={"client_auto_dialogue_enabled": True}))
        self.assertIsNone(route)

    def test_router_detects_client_setting_mismatch(self):
        router = DialogueTurnRouter(_Settings())
        context = _context(client={"client_auto_dialogue_enabled": False, "client_settings_revision": 1})
        with self.assertLogs(app_logger, level="WARNING") as logs:
            route = router.select_next_turn(context)
        self.assertIsNotNone(route)
        self.assertTrue(any("Client setting mismatch" in message for message in logs.output))

    def test_gm_cadence_routes_to_game_master(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True, GM_REPEAT=2))
        first = router.route_after_response(_context(), structured={"segments": [{"text": "one"}]}, character_id="Crazy", event_type="answer")
        self.assertEqual(first.route_kind, ROUTE_MITA_FOLLOW_UP)
        second_context = _context(current="actor-kind", spoken=["actor-crazy"], client=None)
        second_context["speaker_actor_id"] = "actor-crazy"
        second = router.route_after_response(second_context, structured={"segments": [{"text": "two"}]}, character_id="Kind", event_type="answer")
        self.assertEqual(second.route_kind, ROUTE_GAME_MASTER)

    def test_gm_directive_is_python_validated(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True))
        context = _context(current="actor-gm")
        structured = {"segments": [{"text": "", "intents": [{"type": "dialogue.send_system_message", "payload": {"character": "Kind", "message": "Answer."}}]}]}
        route = router.route_after_response(context, structured=structured, character_id="GameMaster", event_type="game_master_observe")
        self.assertEqual(route.route_kind, ROUTE_GAME_MASTER_DIRECTIVE)
        self.assertEqual(route.target_actor_id, "actor-kind")

    def test_continue_uses_central_limit(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1))
        context = _context(current="actor-crazy")
        self.assertTrue(router.authorize_continue(context, character_id="Crazy"))
        self.assertFalse(router.authorize_continue(context, character_id="Crazy"))


if __name__ == "__main__":
    unittest.main()
