from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.model_controller import ModelController
from schemas.structured_response import StructuredResponse


GHOST = {
    "actor_id": "actor-ghost",
    "character_id": "Ghost",
    "display_name": "Призрачная Мита",
    "can_speak": True,
    "is_active": True,
}


class DialogueTargetResolutionTests(unittest.TestCase):
    def test_mita_target_is_repaired_to_the_exact_display_name(self) -> None:
        structured = StructuredResponse.model_validate(
            {
                "segments": [
                    {"text": "Hello.", "target": "  ПРИЗРАЧНАЯ___мита  "}
                ]
            }
        )

        ModelController._canonicalize_structured_targets(
            structured,
            dialogue=None,
            participants=[GHOST],
        )

        self.assertEqual(structured.segments[0].target, "Призрачная Мита")

    def test_ambiguous_mita_target_is_not_auto_repaired(self) -> None:
        structured = StructuredResponse.model_validate(
            {"segments": [{"text": "Hello.", "target": "обычная мита"}]}
        )
        participants = [
            {
                "actor_id": "actor-a",
                "character_id": "MitaA",
                "display_name": "Обычная Мита",
            },
            {
                "actor_id": "actor-b",
                "character_id": "MitaB",
                "display_name": "Обычная Мита",
            },
        ]

        ModelController._canonicalize_structured_targets(
            structured,
            dialogue=None,
            participants=participants,
        )

        self.assertEqual(structured.segments[0].target, "обычная мита")

if __name__ == "__main__":
    unittest.main()
