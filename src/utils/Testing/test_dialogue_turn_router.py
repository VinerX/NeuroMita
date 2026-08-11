from __future__ import annotations

import sys
import unittest
from pathlib import Path

from main_logger import logger as app_logger

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import services.dialogue_turn_router as router_module
from services.dialogue_turn_router import (
    DialogueTurnRouter,
    ROUTE_GAME_MASTER,
    ROUTE_GAME_MASTER_DIRECTIVE,
    ROUTE_CONTINUE,
    ROUTE_MITA_FOLLOW_UP,
)


class _Settings:
    revision = 42

    def __init__(self, **values):
        self.values = {
            "MITA_DIALOGUE_AUTO": True,
            "MITA_DIALOGUE_TARGET_ROUTING": True,
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
        {"actor_id": "actor-crazy", "character_id": "Crazy", "display_name": "Безумная Мита", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-kind", "character_id": "Kind", "display_name": "Добрая Мита", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-cappie", "character_id": "Cappie", "display_name": "Кэппи", "can_speak": True, "can_hear_speaker": True},
        {"actor_id": "actor-gm", "character_id": "GameMaster", "display_name": "GameMaster", "can_speak": True, "can_hear_speaker": True},
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
    def test_route_after_response_requires_trusted_control_plane(self):
        router = DialogueTurnRouter(_Settings())
        context = _context()
        structured = {"segments": [{"text": "one"}]}
        self.assertIsNone(router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
        ))
        self.assertIsNotNone(router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        ))

    def test_router_disabled_returns_no_turn(self):
        router = DialogueTurnRouter(_Settings(MITA_DIALOGUE_AUTO=False))
        self.assertIsNone(router.select_next_turn(_context()))

    def test_router_no_budget_returns_no_turn(self):
        router = DialogueTurnRouter(
            _Settings(
                DIALOGUE_MAX_AUTO_TURNS=0,
                DIALOGUE_AUTO_TURN_COUNT_MODE="fixed",
            )
        )
        self.assertIsNone(router.select_next_turn(_context()))

    def test_router_can_budget_one_turn_per_active_mita(self):
        router = DialogueTurnRouter(
            _Settings(
                DIALOGUE_AUTO_TURN_COUNT_MODE="per_participant",
                DIALOGUE_AUTO_TURNS_PER_PARTICIPANT=2,
            )
        )
        context = _context()
        context["auto_turns_since_player"] = 6

        authoritative = router.authoritative_context(context)

        self.assertEqual(authoritative.max_auto_turns, 6)
        self.assertIsNone(router.select_next_turn(context))

    def test_router_defaults_to_one_turn_per_active_mita(self):
        router = DialogueTurnRouter(_Settings())
        context = _context()

        authoritative = router.authoritative_context(context)

        self.assertTrue(authoritative.auto_dialogue_enabled)
        self.assertEqual(authoritative.max_auto_turns, 3)

    def test_router_selects_next_actor_in_stable_order(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-crazy", spoken=["actor-crazy"]))
        self.assertEqual(route.route_kind, ROUTE_MITA_FOLLOW_UP)
        self.assertEqual(route.target_actor_id, "actor-kind")

    def test_explicit_mita_target_overrides_the_normal_queue(self):
        router = DialogueTurnRouter(_Settings())
        route = router.route_after_response(
            _context(current="actor-cappie"),
            structured={
                "segments": [
                    {"text": "First sentence.", "target": "добрая___мита"},
                    {"text": "Second sentence for Player."},
                ]
            },
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertEqual(route.target_actor_id, "actor-kind")
        self.assertEqual(route.reason, "mita_explicit_target")

    def test_explicit_targets_use_first_mention_fifo_and_deduplicate(self):
        router = DialogueTurnRouter(_Settings())
        first = router.route_after_response(
            _context(current="actor-cappie"),
            structured={
                "segments": [
                    {"text": "Kind first.", "target": "Kind"},
                    {"text": "Crazy second.", "target": "Crazy"},
                    {"text": "Kind again.", "target": "Kind Mita"},
                ]
            },
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        second_context = _context(current="actor-kind")
        second_context["speaker_actor_id"] = "actor-cappie"
        second = router.route_after_response(
            second_context,
            structured={"segments": [{"text": "Kind replies."}]},
            character_id="Kind",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertEqual(first.target_actor_id, "actor-kind")
        self.assertEqual(second.target_actor_id, "actor-crazy")
        self.assertEqual(second.reason, "mita_explicit_target")

    def test_new_explicit_target_is_appended_after_existing_fifo_entries(self):
        router = DialogueTurnRouter(_Settings())
        first = router.route_after_response(
            _context(current="actor-cappie"),
            structured={
                "segments": [
                    {"text": "Kind first.", "target": "Kind"},
                    {"text": "Crazy second.", "target": "Crazy"},
                ]
            },
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        kind_context = _context(current="actor-kind")
        kind_context["speaker_actor_id"] = "actor-cappie"
        second = router.route_after_response(
            kind_context,
            structured={"segments": [{"text": "Cappie later.", "target": "Cappie"}]},
            character_id="Kind",
            event_type="answer",
            control_plane_trusted=True,
        )

        crazy_context = _context(current="actor-crazy")
        crazy_context["speaker_actor_id"] = "actor-kind"
        third = router.route_after_response(
            crazy_context,
            structured={"segments": [{"text": "Crazy replies."}]},
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertEqual(first.target_actor_id, "actor-kind")
        self.assertEqual(second.target_actor_id, "actor-crazy")
        self.assertEqual(third.target_actor_id, "actor-cappie")

    def test_explicit_fifo_resumes_after_same_mita_continuation(self):
        router = DialogueTurnRouter(_Settings())
        first = router.route_after_response(
            _context(current="actor-cappie"),
            structured={
                "segments": [
                    {"text": "Kind first.", "target": "Kind"},
                    {"text": "Crazy second.", "target": "Crazy"},
                ]
            },
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        continued_context = _context(current="actor-kind")
        continued_context["speaker_actor_id"] = "actor-kind"
        second = router.route_after_response(
            continued_context,
            structured={"segments": [{"text": "Continuation finished."}]},
            character_id="Kind",
            event_type="continue",
            control_plane_trusted=True,
        )

        self.assertEqual(first.target_actor_id, "actor-kind")
        self.assertEqual(second.target_actor_id, "actor-crazy")

    def test_new_player_turn_discards_stale_explicit_fifo(self):
        router = DialogueTurnRouter(_Settings())
        first = router.route_after_response(
            _context(current="actor-cappie"),
            structured={
                "segments": [
                    {"text": "Kind first.", "target": "Kind"},
                    {"text": "Crazy second.", "target": "Crazy"},
                ]
            },
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        interrupted_context = _context(current="actor-kind")
        second = router.route_after_response(
            interrupted_context,
            structured={"segments": [{"text": "New player turn."}]},
            character_id="Kind",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertEqual(first.target_actor_id, "actor-kind")
        self.assertEqual(second.target_actor_id, "actor-cappie")

    def test_disabled_target_priority_keeps_the_normal_queue(self):
        router = DialogueTurnRouter(_Settings(MITA_DIALOGUE_TARGET_ROUTING=False))
        route = router.route_after_response(
            _context(current="actor-cappie"),
            structured={"segments": [{"text": "One.", "target": "Добрая Мита"}]},
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertEqual(route.target_actor_id, "actor-crazy")

    def test_explicit_target_has_priority_over_game_master_cadence(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True, GM_REPEAT=1))
        route = router.route_after_response(
            _context(current="actor-cappie"),
            structured={"segments": [{"text": "One.", "target": "Добрая Мита"}]},
            character_id="Cappie",
            event_type="answer",
            control_plane_trusted=True,
        )

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
        first = router.route_after_response(_context(), structured={"segments": [{"text": "one"}]}, character_id="Crazy", event_type="answer", control_plane_trusted=True)
        self.assertEqual(first.route_kind, ROUTE_MITA_FOLLOW_UP)
        second_context = _context(current="actor-kind", spoken=["actor-crazy"], client=None)
        second_context["speaker_actor_id"] = "actor-crazy"
        second = router.route_after_response(second_context, structured={"segments": [{"text": "two"}]}, character_id="Kind", event_type="answer", control_plane_trusted=True)
        self.assertEqual(second.route_kind, ROUTE_GAME_MASTER)

    def test_gm_cadence_can_run_after_mita_budget_is_exhausted(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True, GM_REPEAT=1))
        context = _context()
        context["auto_turns_since_player"] = 6
        context["max_auto_turns"] = 6

        route = router.route_after_response(
            context,
            structured={"segments": [{"text": "one"}]},
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )

        self.assertIsNotNone(route)
        self.assertEqual(route.route_kind, ROUTE_GAME_MASTER)

    def test_gm_directive_is_python_validated(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True))
        context = _context(current="actor-gm")
        structured = {"segments": [{"text": "", "intents": [{"type": "dialogue.send_system_message", "payload": {"character": "Kind", "message": "Answer."}}]}]}
        route = router.route_after_response(context, structured=structured, character_id="GameMaster", event_type="game_master_observe", control_plane_trusted=True)
        self.assertEqual(route.route_kind, ROUTE_GAME_MASTER_DIRECTIVE)
        self.assertEqual(route.target_actor_id, "actor-kind")
        self.assertEqual(route.input_text, "Answer.")

    def test_game_master_target_without_text_does_not_create_directive(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True))
        route = router.route_after_response(
            _context(current=""),
            structured={
                "segments": [{
                    "intents": [{
                        "type": "dialogue.send_system_message",
                        "payload": {"character": "Kind"},
                    }],
                }],
            },
            character_id="GameMaster",
            event_type="game_master_observe",
            control_plane_trusted=True,
        )

        self.assertIsNone(route)

    def test_continue_uses_central_limit(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1))
        context = _context(current="actor-crazy")
        self.assertTrue(router.authorize_continue(context, character_id="Crazy"))
        self.assertFalse(router.authorize_continue(context, character_id="Crazy"))
    def test_continue_intent_routes_only_current_responder(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1))
        context = _context(current="actor-crazy")
        route = router.route_after_response(
            context,
            structured={"segments": [{"text": "more", "intents": [{"type": "dialogue.continue", "payload": {}}]}]},
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(route.route_kind, ROUTE_CONTINUE)
        self.assertEqual(route.event_type, "continue")
        self.assertEqual(route.target_actor_id, "actor-crazy")
        self.assertTrue(route.continue_route_reserved)
        self.assertTrue(router.consume_continue_reservation(context, character_id="Crazy"))
        self.assertFalse(router.consume_continue_reservation(context, character_id="Crazy"))

    def test_continue_limit_falls_back_to_next_mita(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1))
        context = _context(current="actor-crazy")
        structured = {"segments": [{"intents": [{"type": "dialogue.continue", "payload": {}}]}]}

        first = router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(first.route_kind, ROUTE_CONTINUE)

        fallback = router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(fallback.route_kind, ROUTE_MITA_FOLLOW_UP)
        self.assertEqual(fallback.target_actor_id, "actor-kind")

    def test_zero_continue_limit_only_disables_continuations(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=0))
        route = router.route_after_response(
            _context(current="actor-crazy"),
            structured={"segments": [{"intents": [{"type": "dialogue.continue", "payload": {}}]}]},
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(route.route_kind, ROUTE_MITA_FOLLOW_UP)
        self.assertEqual(route.target_actor_id, "actor-kind")

    def test_continue_limit_fallback_preserves_game_master_cadence(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1, GM_ON=True, GM_REPEAT=1))
        context = _context(current="actor-crazy")
        structured = {"segments": [{"intents": [{"type": "dialogue.continue", "payload": {}}]}]}

        first = router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(first.route_kind, ROUTE_CONTINUE)

        fallback = router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(fallback.route_kind, ROUTE_GAME_MASTER)

    def test_fallback_to_next_mita_starts_a_fresh_continue_streak(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=1))
        context = _context(current="actor-crazy")
        structured = {"segments": [{"intents": [{"type": "dialogue.continue", "payload": {}}]}]}

        self.assertEqual(
            router.route_after_response(
                context,
                structured=structured,
                character_id="Crazy",
                event_type="answer",
                control_plane_trusted=True,
            ).route_kind,
            ROUTE_CONTINUE,
        )
        fallback = router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(fallback.target_actor_id, "actor-kind")

        next_context = _context(current="actor-kind")
        next_context["speaker_actor_id"] = "actor-crazy"
        next_route = router.route_after_response(
            next_context,
            structured=structured,
            character_id="Kind",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(next_route.route_kind, ROUTE_CONTINUE)
        self.assertEqual(next_route.target_actor_id, "actor-kind")
    def test_continue_event_does_not_fall_through_to_round_robin(self):
        router = DialogueTurnRouter(_Settings())
        self.assertIsNone(router.route_after_response(
            _context(current="actor-crazy"),
            structured={"segments": [{"text": "continued"}]},
            character_id="Crazy",
            event_type="continue",
            control_plane_trusted=True,
        ))

    def test_continue_spends_shared_auto_turn_budget(self):
        router = DialogueTurnRouter(_Settings(DIALOGUE_MAX_CONTINUES=3))
        context = _context(current="actor-crazy")
        context["auto_turns_since_player"] = 6
        structured = {"segments": [{"text": "more", "intents": [{"type": "dialogue.continue", "payload": {}}]}]}
        self.assertIsNone(router.route_after_response(
            context,
            structured=structured,
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        ))

    def test_route_contains_freshness_and_one_shot_metadata(self):
        router = DialogueTurnRouter(_Settings())
        route = router.select_next_turn(_context(current="actor-crazy"))
        self.assertEqual(route.source_turn_index, 0)
        self.assertTrue(route.route_id)
        payload = router_module.route_to_transport(route)
        self.assertEqual(payload["source_turn_index"], 0)
        self.assertEqual(payload["route_id"], route.route_id)

    def test_game_master_without_target_resumes_round_robin(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True, GM_REPEAT=2))
        router.route_after_response(
            _context(current="actor-crazy"),
            structured={"segments": [{"text": "one"}]},
            character_id="Crazy",
            event_type="answer",
            control_plane_trusted=True,
        )
        second_context = _context(current="actor-kind", spoken=["actor-crazy"])
        second_context["speaker_actor_id"] = "actor-crazy"
        second = router.route_after_response(
            second_context,
            structured={"segments": [{"text": "two"}]},
            character_id="Kind",
            event_type="answer",
            control_plane_trusted=True,
        )
        self.assertEqual(second.route_kind, ROUTE_GAME_MASTER)
        gm_context = _context(current="", spoken=["actor-crazy", "actor-kind"])
        resumed = router.route_after_response(
            gm_context,
            structured={"segments": [{"text": "No explicit target."}]},
            character_id="GameMaster",
            event_type="game_master_observe",
            control_plane_trusted=True,
        )
        self.assertEqual(resumed.target_actor_id, "actor-cappie")

    def test_game_master_broadcast_directive_targets_resuming_mita(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True))
        route = router.route_after_response(
            _context(current="actor-kind"),
            structured={
                "segments": [{
                    "intents": [{
                        "type": "dialogue.broadcast_system_message",
                        "payload": {"message": "Meow naturally in your reply."},
                    }],
                }],
            },
            character_id="GameMaster",
            event_type="game_master_observe",
            control_plane_trusted=True,
        )

        self.assertIsNotNone(route)
        self.assertEqual(route.route_kind, ROUTE_GAME_MASTER_DIRECTIVE)
        self.assertEqual(route.target_actor_id, "actor-kind")
        self.assertEqual(route.input_text, "Meow naturally in your reply.")

    def test_game_master_target_accepts_character_alias(self):
        router = DialogueTurnRouter(_Settings(GM_ON=True))
        route = router.route_after_response(
            _context(current="actor-kind"),
            structured={"segments": [{"intents": [{"type": "dialogue.send_system_message", "payload": {"character": "crazy_mita", "message": "Answer."}}]}]},
            character_id="GameMaster",
            event_type="game_master_observe",
            control_plane_trusted=True,
        )
        self.assertEqual(route.target_actor_id, "actor-crazy")


if __name__ == "__main__":
    unittest.main()
