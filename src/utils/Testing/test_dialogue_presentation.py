from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.contracts import (
    DialogueParticipantView,
    DialogueRuntimeSnapshot,
    DialogueRuntimeSource,
)
from ui.chat.dialogue_presentation import format_conversation_title, format_runtime_source


class DialoguePresentationTests(unittest.TestCase):
    def test_title_keeps_single_character_fallback(self) -> None:
        self.assertEqual(
            format_conversation_title(None, "Crazy"),
            "Conversation with Crazy",
        )

    def test_title_lists_multi_mita_participants_and_hides_gm(self) -> None:
        snapshot = DialogueRuntimeSnapshot(
            source=DialogueRuntimeSource.UNITY,
            conversation_id="unity:one",
            participants=(
                DialogueParticipantView("a", "A", "Alpha"),
                DialogueParticipantView("b", "B", "Beta"),
                DialogueParticipantView("gm", "GameMaster", "Game Master"),
            ),
        )
        self.assertEqual(format_conversation_title(snapshot), "Conversation: Alpha, Beta")
        self.assertEqual(format_runtime_source(snapshot), "Game")

    def test_title_collapses_large_sessions(self) -> None:
        participants = tuple(
            DialogueParticipantView(str(i), f"Mita{i}", f"Mita {i}")
            for i in range(4)
        )
        snapshot = DialogueRuntimeSnapshot(
            source=DialogueRuntimeSource.UNITY,
            conversation_id="unity:one",
            participants=participants,
        )
        self.assertEqual(format_conversation_title(snapshot), "Conversation with Mitas (4)")
        self.assertEqual(format_runtime_source(snapshot), "Game")


if __name__ == "__main__":
    unittest.main()
