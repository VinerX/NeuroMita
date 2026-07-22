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
            react_level=2,
        )

        self.assertEqual(reason, "Player entered the room")
        self.assertEqual(duration, 3.5)
        self.assertEqual(events, [])
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
            react_level=2,
        )

        rendered = "\n".join(lines)
        self.assertEqual(reason, "Player stood up")
        self.assertEqual(duration, 2.0)
        self.assertEqual(len(events), 2)
        self.assertIn("current Unity world state is authoritative", rendered)
        self.assertIn("1. [Generic] Player sat down", rendered)
        self.assertIn("2. [Generic] Player stood up; occurrences: 3", rendered)

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
