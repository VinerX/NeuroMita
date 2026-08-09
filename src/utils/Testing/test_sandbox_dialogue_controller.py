from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.sandbox_dialogue_controller import SandboxDialogueController
from services.contracts import DialogueParticipant, SandboxDialogueConfig


class SandboxDialogueControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = SandboxDialogueController()
        self.controller._config = SandboxDialogueConfig(
            participant_character_ids=("A", "B"),
            auto_dialogue_enabled=True,
            max_auto_turns=1,
        )
        self.controller._participants = (
            DialogueParticipant("sandbox:A:0", "A", "A"),
            DialogueParticipant("sandbox:B:0", "B", "B"),
        )
        self.controller._conversation_id = "sandbox:test"
        self.controller._epoch = 1
        self.controller._turn_index = 0
        self.controller._auto_turns_used = 0
        self.controller._speaker_actor_id = "player"
        self.controller._responder_actor_id = "sandbox:A:0"
        self.controller._spoken_actor_ids = []
        self.controller._pending_task_uid = ""
        self.controller._pending_route = None
        self.controller._consumed_route_ids.clear()
        self.controller._active = True

    def tearDown(self) -> None:
        self.controller.stop_session()

    def _route(self, **overrides):
        route = {
            "route_kind": "mita_follow_up",
            "event_type": "answer",
            "target_actor_id": "sandbox:B:0",
            "target_character_id": "B",
            "input_text": "Answer now.",
            "conversation_id": "sandbox:test",
            "epoch": 1,
            "source_turn_index": 0,
            "route_id": "route-1",
        }
        route.update(overrides)
        return route

    def test_sandbox_defaults_to_one_turn_per_participant(self) -> None:
        config = SandboxDialogueConfig()

        self.assertTrue(config.auto_dialogue_enabled)
        self.assertEqual(config.auto_turn_count_mode, "per_participant")
        self.assertEqual(config.auto_turns_per_participant, 1)

    def test_active_session_can_update_gm_instruction(self) -> None:
        self.assertTrue(
            self.controller.update_gm_instruction("Prioritize the player vote.")
        )
        self.assertEqual(
            self.controller._config.gm_instruction,
            "Prioritize the player vote.",
        )

    def test_valid_route_advances_exactly_one_turn(self) -> None:
        with patch.object(self.controller, "_emit_request", return_value=True):
            self.assertTrue(self.controller.execute_route(self._route()))
        self.assertEqual(self.controller._turn_index, 1)
        self.assertEqual(self.controller._auto_turns_used, 1)
        self.assertEqual(self.controller._responder_actor_id, "sandbox:B:0")

    def test_stale_route_is_rejected(self) -> None:
        with patch.object(self.controller, "_emit_request", return_value=True):
            self.assertTrue(self.controller.execute_route(self._route()))
        stale = self._route(route_id="route-stale")
        self.assertFalse(self.controller.execute_route(stale))

    def test_continue_requires_router_reservation(self) -> None:
        self.assertFalse(
            self.controller.execute_route(self._route(route_kind="continue"))
        )
        self.assertEqual(self.controller._turn_index, 0)

    def test_auto_budget_is_shared_with_follow_up_routes(self) -> None:
        self.controller._auto_turns_used = 1
        self.assertFalse(self.controller.execute_route(self._route(route_id="route-2")))

    def test_game_master_check_does_not_spend_auto_budget(self) -> None:
        self.controller._config = SandboxDialogueConfig(
            participant_character_ids=("A", "B"),
            auto_dialogue_enabled=True,
            max_auto_turns=1,
            game_master_enabled=True,
        )
        self.controller._auto_turns_used = 1

        with patch.object(self.controller, "_emit_request", return_value=True):
            self.assertTrue(
                self.controller.execute_route(
                    self._route(
                        route_kind="game_master",
                        event_type="game_master_observe",
                        target_actor_id="",
                        target_character_id="GameMaster",
                        route_id="gm-route-1",
                    )
                )
            )

        self.assertEqual(self.controller._auto_turns_used, 1)
        self.assertEqual(self.controller._turn_index, 1)
        self.assertEqual(self.controller._spoken_actor_ids, [])

    def test_participant_budget_uses_selected_mitas(self) -> None:
        self.controller._config = SandboxDialogueConfig(
            participant_character_ids=("A", "B"),
            auto_dialogue_enabled=True,
            max_auto_turns=1,
            auto_turn_count_mode="per_participant",
            auto_turns_per_participant=3,
        )

        self.assertEqual(self.controller._effective_auto_turn_limit_locked(), 6)

    def test_route_target_character_must_match_participant(self) -> None:
        self.assertFalse(
            self.controller.execute_route(self._route(target_character_id="A"))
        )
        self.assertNotIn("route-1", self.controller._consumed_route_ids)

    def test_game_master_directive_target_must_be_participant(self) -> None:
        self.assertFalse(
            self.controller.execute_route(
                self._route(
                    route_kind="game_master_directive",
                    target_actor_id="sandbox:unknown:0",
                    target_character_id="Unknown",
                )
            )
        )

    def test_continue_target_must_be_current_responder(self) -> None:
        self.assertFalse(
            self.controller.execute_route(
                self._route(
                    route_kind="continue",
                    continue_route_reserved=True,
                )
            )
        )

    def test_player_message_starts_new_turn(self) -> None:
        with patch.object(self.controller, "_emit_request", return_value=True):
            self.assertTrue(self.controller.send_player_message("Hello"))
        self.assertEqual(self.controller._epoch, 2)
        self.assertEqual(self.controller._turn_index, 1)
        self.assertEqual(self.controller._auto_turns_used, 0)
        self.assertEqual(self.controller._speaker_actor_id, "player")
        self.assertEqual(self.controller._spoken_actor_ids, [])

    def test_ui_state_reports_pending_route_and_busy_task(self) -> None:
        self.controller._config = SandboxDialogueConfig(
            participant_character_ids=("A", "B"),
            auto_dialogue_enabled=True,
            max_auto_turns=1,
            manual_step_mode=True,
        )
        self.controller._ui_status_code = "manual_route_ready"
        self.controller._pending_route = self._route()
        state = self.controller.ui_state()
        self.assertTrue(state.active)
        self.assertTrue(state.manual_step_mode)
        self.assertTrue(state.has_pending_route)
        self.assertEqual(state.pending_route_kind, "mita_follow_up")
        self.assertEqual(state.pending_target_actor_id, "sandbox:B:0")
        self.assertFalse(state.busy)

        self.controller._pending_task_uid = "task-1"
        self.assertTrue(self.controller.ui_state().busy)

    def test_player_message_resets_ui_status_and_budget(self) -> None:
        self.controller._auto_turns_used = 1
        self.controller._ui_status_code = "budget_exhausted"
        with patch.object(self.controller, "_emit_request", return_value=True):
            self.assertTrue(self.controller.send_player_message("Hello"))
        state = self.controller.ui_state()
        self.assertEqual(state.status_code, "waiting_model")
        self.assertFalse(state.has_pending_route)
    def test_intermediate_task_status_keeps_request_pending(self) -> None:
        self.controller._pending_task_uid = "task-1"
        event = SimpleNamespace(
            data={
                "task": SimpleNamespace(
                    uid="task-1",
                    status=SimpleNamespace(value="RUNNING"),
                    result=None,
                )
            }
        )
        self.controller._on_task_status(event)
        self.assertEqual(self.controller._pending_task_uid, "task-1")

    def test_manual_step_executes_pending_route(self) -> None:
        self.controller._config = SandboxDialogueConfig(
            participant_character_ids=("A", "B"),
            auto_dialogue_enabled=True,
            max_auto_turns=1,
            manual_step_mode=True,
        )
        self.controller._pending_route = self._route()
        with patch.object(self.controller, "execute_route", return_value=True) as execute:
            self.assertTrue(self.controller.step_once())
        execute.assert_called_once_with(self._route())


if __name__ == "__main__":
    unittest.main()
