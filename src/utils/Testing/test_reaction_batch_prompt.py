from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from game_connections.handlers.actions.create_task import (
    _build_react_prompt,
    _normalise_reaction_events,
)


class ReactionBatchPromptTests(unittest.TestCase):
    def test_legacy_single_reaction_is_preserved(self):
        lines, reason, duration, events = _build_react_prompt(
            {
                "reason_type": "RoomEnter",
                "reason_content": "Player entered the room",
                "duration": 3.5,
            },
        )

        self.assertEqual(reason, "Player entered the room")
        self.assertEqual(duration, 3.5)
        self.assertEqual(events, [])
        self.assertIn("React naturally to this game event:", lines)
        self.assertNotIn("React level:", "\n".join(lines))
        self.assertIn("Reason type: RoomEnter", lines)
        self.assertIn("Reason: Player entered the room", lines)

    def test_collected_reactions_are_rendered_as_one_turn(self):
        lines, reason, duration, events = _build_react_prompt(
            {
                "reaction_events": [
                    {
                        "reason_type": "Generic",
                        "reason_content": "Player sat down",
                        "duration": 1,
                    },
                    {
                        "reason_type": "Generic",
                        "reason_content": "Player stood up",
                        "duration": 2,
                        "count": 3,
                    },
                ]
            },
        )

        rendered = "\n".join(lines)
        self.assertEqual(reason, "Player stood up")
        self.assertEqual(duration, 2.0)
        self.assertEqual(len(events), 2)
        self.assertIn("React to their combined meaning as one current moment.", rendered)
        self.assertIn("Prioritize the most recent and most significant event.", rendered)
        self.assertNotIn("React level:", rendered)
        self.assertNotIn("authoritative", rendered)
        self.assertIn("1. [Generic] Player sat down", rendered)
        self.assertIn("2. [Generic] Player stood up; occurrences: 3", rendered)

    def test_single_collected_reaction_does_not_use_batch_wording(self):
        lines, _, _, events = _build_react_prompt(
            {
                "reaction_events": [
                    {
                        "reason_type": "Generic",
                        "reason_content": "Player pushed you",
                        "duration": 2.5,
                    }
                ]
            },
        )

        rendered = "\n".join(lines)
        self.assertEqual(len(events), 1)
        self.assertEqual(rendered, "React naturally to this game event:\n[Generic] Player pushed you")
        self.assertNotIn("batch", rendered.lower())
        self.assertNotIn("React level:", rendered)
        self.assertNotIn("duration", rendered.lower())

    def test_malformed_events_are_ignored_and_limits_are_applied(self):
        raw = [
            None,
            "bad",
            {"reason_content": ""},
            {
                "reason_content": "Valid",
                "duration": "bad",
                "count": 5000,
            },
        ]

        events = _normalise_reaction_events({"reaction_events": raw})

        self.assertEqual(events, [
            {
                "reason_type": "Generic",
                "reason_content": "Valid",
                "duration": 0.0,
                "count": 1000,
            }
        ])


if __name__ == "__main__":
    unittest.main()
