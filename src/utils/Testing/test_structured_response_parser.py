from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from utils.structured_response_parser import parse_structured_response


class StructuredResponseParserCoerceTests(unittest.TestCase):
    def test_scalar_segment_fields_are_coerced_to_lists(self) -> None:
        payload = {
            "segments": [
                {
                    "text": "Привет",
                    "emotions": "smileobvi",
                    "animations": "Жест пальцами",
                    "music": "Music 3 Tamagochi",
                    "movement_modes": "Стоять на месте",
                    "hint": "Не зли Миту",
                }
            ],
            "attitude_change": 1.0,
            "boredom_change": 0.5,
            "stress_change": -0.2,
        }

        response = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        segment = response.segments[0]

        self.assertEqual(segment.emotions, ["smileobvi"])
        self.assertEqual(segment.animations, ["Жест пальцами"])
        self.assertEqual(segment.music, ["Music 3 Tamagochi"])
        self.assertEqual(segment.movement_modes, ["Стоять на месте"])
        self.assertEqual(segment.hint, "Не зли Миту")

    def test_scalar_text_and_allow_sleep_are_coerced(self) -> None:
        payload = {
            "segments": [
                {
                    "text": 123,
                    "commands": "Continue",
                    "allow_sleep": "true",
                    "target": 77,
                }
            ],
            "attitude_change": "1.25",
            "boredom_change": "0.5",
            "stress_change": "-0.75",
        }

        response = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        segment = response.segments[0]

        self.assertEqual(segment.text, "123")
        self.assertEqual(segment.commands, ["Continue"])
        self.assertTrue(segment.allow_sleep)
        self.assertEqual(segment.target, "77")
        self.assertEqual(response.attitude_change, 1.25)
        self.assertEqual(response.boredom_change, 0.5)
        self.assertEqual(response.stress_change, -0.75)


if __name__ == "__main__":
    unittest.main()
