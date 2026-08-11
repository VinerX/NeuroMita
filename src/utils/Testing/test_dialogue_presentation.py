from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QLabel

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.contracts import (
    DialogueParticipantView,
    DialogueRuntimeSnapshot,
    DialogueRuntimeSource,
)
from ui.chat.dialogue_presentation import format_conversation_title, format_runtime_source
from ui.chat.message_renderer import _group_segments_by_target
from ui.chat.structured_panel import StructuredOutputPanel


class DialoguePresentationTests(unittest.TestCase):
    def test_segment_targets_form_separate_visible_bubble_groups(self) -> None:
        groups = _group_segments_by_target([
            {"text": "For Kind, part one.", "target": "Kind"},
            {"text": "For Kind, part two.", "target": "Kind"},
            {"text": "For Cappie.", "target": "Cappie"},
            {"text": "For Player."},
        ])

        self.assertEqual(groups, [
            ("Kind", ["For Kind, part one.", "For Kind, part two."]),
            ("Cappie", ["For Cappie."]),
            ("Player", ["For Player."]),
        ])

    def test_structured_panel_shows_target_on_each_segment(self) -> None:
        app = QApplication.instance() or QApplication([])
        panel = StructuredOutputPanel({
            "segments": [
                {"text": "For Kind.", "target": "Kind"},
                {"text": "For Cappie.", "target": "Cappie"},
            ],
        })
        labels = [label.text() for label in panel.findChildren(QLabel)]
        self.assertIn("target: Kind", labels)
        self.assertIn("target: Cappie", labels)
        panel.close()
        app.processEvents()

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
