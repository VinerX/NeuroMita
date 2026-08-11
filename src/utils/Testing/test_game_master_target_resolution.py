from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from schemas.game_master_response import GameMasterResponse
from services.dialogue_transcript_service import DialogueTranscriptService
from services.game_master_action_executor import GameMasterActionExecutor
from services.game_master_context_builder import GameMasterContextBuilder
from services.game_master_directive_registry import GameMasterDirectiveRegistry


GHOST = {
    "actor_id": "actor-ghost",
    "character_id": "Ghost",
    "display_name": "Призрачная Мита",
    "can_speak": True,
    "is_active": True,
}


class GameMasterTargetResolutionTests(unittest.TestCase):
    def test_context_exposes_canonical_target_and_marks_name_display_only(self) -> None:
        registry = GameMasterDirectiveRegistry()
        builder = GameMasterContextBuilder(registry, DialogueTranscriptService())

        messages = builder.build_messages(
            dialogue={
                "conversation_id": "test:ghost",
                "participants": [GHOST],
            },
            capabilities={"gm_allow_routing": True, "gm_allow_narration": False},
        )

        context = messages[0]["content"]
        self.assertIn(
            "target=actor-ghost; actor=actor-ghost; character=Ghost; name=Призрачная Мита",
            context,
        )
        self.assertIn("name= value is display-only", context)

    def test_localized_display_name_is_repaired_to_canonical_route(self) -> None:
        executor = GameMasterActionExecutor(GameMasterDirectiveRegistry())
        response = GameMasterResponse.model_validate(
            {
                "actions": [
                    {
                        "type": "route",
                        "target": "  ПРИЗРАЧНАЯ   мита  ",
                        "instruction": "Continue the scene.",
                    }
                ]
            }
        )

        result = executor.apply(
            response,
            conversation_id="test:ghost",
            participants=[GHOST],
            turn_index=1,
            source="auto_corrector",
            allow_routing=True,
            allow_narration=False,
        )

        self.assertTrue(result.had_action)
        self.assertEqual(result.route_target_actor_id, "actor-ghost")
        self.assertEqual(result.route_target_character_id, "Ghost")

    def test_separator_variant_is_repaired_without_fuzzy_matching(self) -> None:
        executor = GameMasterActionExecutor(GameMasterDirectiveRegistry())
        response = GameMasterResponse.model_validate(
            {"actions": [{"type": "route", "target": "призрачная_мита"}]}
        )

        result = executor.apply(
            response,
            conversation_id="test:ghost",
            participants=[GHOST],
            turn_index=1,
            source="auto_corrector",
        )

        self.assertEqual(result.route_target_character_id, "Ghost")


if __name__ == "__main__":
    unittest.main()
