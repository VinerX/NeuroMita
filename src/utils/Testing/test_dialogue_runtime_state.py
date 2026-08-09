from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.events import EventBus
from services.contracts import DialogueRuntimeSource
from services.dialogue_runtime_state import DialogueRuntimeStateService


class DialogueRuntimeStateTests(unittest.TestCase):
    def test_unity_source_has_priority_over_sandbox(self) -> None:
        bus = EventBus()
        service = DialogueRuntimeStateService(bus)
        try:
            sandbox = {
                "conversation_id": "sandbox:one",
                "epoch": 1,
                "turn_index": 0,
                "participants": [
                    {"actor_id": "sandbox:a:0", "character_id": "A", "display_name": "A"},
                    {"actor_id": "sandbox:b:0", "character_id": "B", "display_name": "B"},
                ],
            }
            unity = dict(sandbox, conversation_id="unity:one", turn_index=4)
            service.update_from_context(sandbox, DialogueRuntimeSource.SANDBOX)
            service.update_from_context(unity, DialogueRuntimeSource.UNITY)
            service.update_from_context(sandbox, DialogueRuntimeSource.SANDBOX)
            snapshot = service.snapshot()
            self.assertIs(snapshot.source, DialogueRuntimeSource.UNITY)
            self.assertEqual(snapshot.conversation_id, "unity:one")
            self.assertEqual(snapshot.turn_index, 4)
        finally:
            bus.shutdown()

    def test_pending_route_scope_rejects_stale_generation(self) -> None:
        bus = EventBus()
        service = DialogueRuntimeStateService(bus)
        try:
            first = {
                "conversation_id": "sandbox:one",
                "epoch": 1,
                "turn_index": 2,
                "participants": [],
            }
            second = dict(first, turn_index=3)
            service.update_from_context(first, DialogueRuntimeSource.SANDBOX)
            service.set_pending_route(
                {"route_kind": "mita_follow_up", "route_id": "route-a", "source_turn_index": 2},
                source=DialogueRuntimeSource.SANDBOX,
                conversation_id="sandbox:one",
                epoch=1,
                source_turn_index=2,
            )
            service.update_from_context(second, DialogueRuntimeSource.SANDBOX)
            service.set_pending_route(
                {"route_kind": "mita_follow_up", "route_id": "route-stale", "source_turn_index": 2},
                source=DialogueRuntimeSource.SANDBOX,
                conversation_id="sandbox:one",
                epoch=1,
                source_turn_index=2,
            )
            self.assertEqual(service.snapshot().pending_route_id, "")
            service.set_pending_route(
                {"route_kind": "mita_follow_up", "route_id": "route-b", "source_turn_index": 3},
                source=DialogueRuntimeSource.SANDBOX,
                conversation_id="sandbox:one",
                epoch=1,
                source_turn_index=3,
            )
            service.clear_pending_route(
                source=DialogueRuntimeSource.SANDBOX,
                conversation_id="sandbox:one",
                epoch=1,
                source_turn_index=2,
            )
            self.assertEqual(service.snapshot().pending_route_id, "route-b")
        finally:
            bus.shutdown()

    def test_pending_route_is_observable_and_reset_is_scoped(self) -> None:
        bus = EventBus()
        service = DialogueRuntimeStateService(bus)
        try:
            context = {
                "conversation_id": "sandbox:one",
                "epoch": 2,
                "turn_index": 3,
                "participants": [],
            }
            service.update_from_context(context, DialogueRuntimeSource.SANDBOX)
            service.set_pending_route(
                {
                    "route_kind": "mita_follow_up",
                    "target_actor_id": "sandbox:b:0",
                    "route_id": "route-1",
                    "source_turn_index": 3,
                },
                control_plane_trusted=True,
            )
            snapshot = service.snapshot()
            self.assertEqual(snapshot.pending_route_id, "route-1")
            self.assertTrue(snapshot.control_plane_trusted)
            self.assertEqual(snapshot.auto_turns_remaining, 0)
            service.reset(DialogueRuntimeSource.UNITY)
            self.assertEqual(service.snapshot().conversation_id, "sandbox:one")
            service.reset(DialogueRuntimeSource.SANDBOX)
            self.assertFalse(service.snapshot().is_active)
        finally:
            bus.shutdown()


if __name__ == "__main__":
    unittest.main()
