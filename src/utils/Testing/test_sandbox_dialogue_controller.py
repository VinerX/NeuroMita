from __future__ import annotations

import sys
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
