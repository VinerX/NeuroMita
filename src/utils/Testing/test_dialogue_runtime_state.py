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
    def test_unity_context_is_projected_for_observation(self) -> None:
        bus = EventBus()
        service = DialogueRuntimeStateService(bus)
        try:
            context = {
                "conversation_id": "unity:one",
                "epoch": 1,
                "turn_index": 4,
                "speaker_actor_id": "player",
                "responder_actor_id": "actor:a",
                "auto_turns_since_player": 2,
                "max_auto_turns": 4,
                "participants": [
                    {"actor_id": "actor:a", "character_id": "A", "display_name": "A"},
                    {"actor_id": "actor:b", "character_id": "B", "display_name": "B"},
                ],
            }
            service.update_from_context(context, DialogueRuntimeSource.UNITY)
            snapshot = service.snapshot()
            self.assertIs(snapshot.source, DialogueRuntimeSource.UNITY)
            self.assertEqual(snapshot.conversation_id, "unity:one")
            self.assertEqual(snapshot.turn_index, 4)
            self.assertEqual(snapshot.auto_turns_remaining, 2)
            self.assertEqual([item.actor_id for item in snapshot.participants], ["actor:a", "actor:b"])
        finally:
            bus.shutdown()

    def test_reset_is_scoped_to_unity(self) -> None:
        bus = EventBus()
        service = DialogueRuntimeStateService(bus)
        try:
            context = {
                "conversation_id": "unity:one",
                "epoch": 1,
                "turn_index": 2,
                "participants": [],
            }
            service.update_from_context(context, DialogueRuntimeSource.UNITY)
            service.reset(DialogueRuntimeSource.NONE)
            self.assertTrue(service.snapshot().is_active)
            service.reset(DialogueRuntimeSource.UNITY)
            self.assertFalse(service.snapshot().is_active)
        finally:
            bus.shutdown()


if __name__ == "__main__":
    unittest.main()
