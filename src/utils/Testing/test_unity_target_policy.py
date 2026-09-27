"""Only explicit player answers may change the Unity dialogue target."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from domain.dialogue_identity import DialogueActorKind, ResolvedDialogueSpeaker
from game_connections.handlers.actions.create_task import should_update_unity_dialogue_target


class UnityTargetPolicyTests(unittest.TestCase):
    def test_only_player_answer_updates_target(self):
        player = ResolvedDialogueSpeaker("Player", "Player", DialogueActorKind.PLAYER, True)
        character = ResolvedDialogueSpeaker("Crazy", "Crazy", DialogueActorKind.CHARACTER, True)

        self.assertTrue(should_update_unity_dialogue_target("answer", player))
        for event_type in ("react", "idle", "continue", "system"):
            with self.subTest(event_type=event_type):
                self.assertFalse(should_update_unity_dialogue_target(event_type, player))
        self.assertFalse(should_update_unity_dialogue_target("answer", character))


if __name__ == "__main__":
    unittest.main()
