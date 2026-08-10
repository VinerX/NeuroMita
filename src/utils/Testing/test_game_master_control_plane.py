from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from domain.game_master import GameMasterDirective
from schemas.game_master_response import GameMasterResponse
from services.dialogue_transcript_service import DialogueTranscriptService
from services.game_master_action_executor import GameMasterActionExecutor
from services.game_master_directive_registry import GameMasterDirectiveRegistry
from services.game_master_scheduler import GameMasterScheduler


class GameMasterControlPlaneTests(unittest.TestCase):
    def _rule(self, *, source="user_director", lifetime="scene", remaining=None, target="Mita", key="task", instruction="Meow"):
        return GameMasterDirective(
            directive_id="",
            key=key,
            target_scope=target,
            target_character_id=target,
            instruction=instruction,
            source=source,
            lifetime=lifetime,
            remaining_uses=remaining,
            created_turn_index=1,
        )

    def test_registry_assigns_id_and_user_rule_wins_over_auto(self):
        registry = GameMasterDirectiveRegistry()
        first = registry.upsert("conv", self._rule(source="auto_corrector"))
        self.assertTrue(first.directive_id)
        user = registry.upsert("conv", self._rule(source="user_director"))
        self.assertIsNotNone(user)
        rejected = registry.upsert("conv", self._rule(source="auto_corrector", instruction="Do not meow"))
        self.assertIsNone(rejected)
        self.assertEqual(registry.snapshot("conv")[0].instruction, "Meow")

    def test_ttl_is_consumed_only_for_target_reply(self):
        registry = GameMasterDirectiveRegistry()
        once = registry.upsert("conv", self._rule(lifetime="next_reply", remaining=1))
        repeated = registry.upsert("conv", self._rule(key="style", lifetime="replies", remaining=2))
        registry.upsert("conv", self._rule(target="Other", key="other", lifetime="next_reply", remaining=1))
        registry.consume_after_reply("conv", "Other")
        self.assertEqual(len(registry.active_for_character("conv", "Mita")), 2)
        registry.consume_after_reply("conv", "Mita")
        active = registry.active_for_character("conv", "Mita")
        self.assertEqual({item.directive_id for item in active}, {repeated.directive_id})
        registry.consume_after_reply("conv", "Mita")
        self.assertEqual(registry.active_for_character("conv", "Mita"), ())

    def test_auto_corrector_cannot_remove_user_rule(self):
        registry = GameMasterDirectiveRegistry()
        user_rule = registry.upsert("conv", self._rule(source="user_director"))
        executor = GameMasterActionExecutor(registry)
        response = GameMasterResponse.model_validate({"actions": [{"type": "remove_rule", "rule_id": user_rule.directive_id}]})
        result = executor.apply(
            response,
            conversation_id="conv",
            participants=[],
            turn_index=2,
            source="auto_corrector",
        )
        self.assertFalse(result.had_action)
        self.assertEqual(len(registry.snapshot("conv")), 1)
    def test_wildcard_scene_rule_is_not_consumed(self):
        registry = GameMasterDirectiveRegistry()
        rule = registry.upsert("conv", self._rule(target="*", lifetime="scene"))
        registry.consume_after_reply("conv", "Mita")
        self.assertEqual(registry.snapshot("conv")[0].directive_id, rule.directive_id)

    def test_transcript_excludes_game_master_and_is_bounded(self):
        transcript = DialogueTranscriptService(max_entries_per_conversation=2)
        transcript.record("conv", turn_index=1, speaker_character_id="GameMaster", text="hidden", event_type="gm")
        for index in range(3):
            transcript.record("conv", turn_index=index, speaker_character_id="Mita", text=str(index), event_type="mita_reply")
        self.assertEqual([entry.text for entry in transcript.recent("conv")], ["1", "2"])

    def test_empty_director_task_is_not_added_to_context(self):
        from services.game_master_context_builder import GameMasterContextBuilder

        context = GameMasterContextBuilder(
            GameMasterDirectiveRegistry(),
            DialogueTranscriptService(),
        )
        messages = context.build_messages(dialogue={"conversation_id": "conv", "participants": []})
        self.assertNotIn("[DIRECTOR_TASK]", messages[0]["content"])

    def test_game_master_context_does_not_include_character_side_context(self):
        from services.game_master_context_builder import GameMasterContextBuilder

        context = GameMasterContextBuilder(
            GameMasterDirectiveRegistry(),
            DialogueTranscriptService(),
        )
        messages = context.build_messages(
            dialogue={
                "conversation_id": "conv",
                "participants": [
                    {"actor_id": "mita-1", "character_id": "Mita", "display_name": "Mita"},
                ],
            },
            task="Director task",
        )
        content = messages[0]["content"]
        self.assertNotIn("Character history", content)
        self.assertNotIn("[Hidden image context]", content)
        self.assertIn("[GAME_MASTER_CONTROL_PLANE]", content)
        self.assertIn("[DIRECTOR_TASK]", content)
    def test_scheduler_triggers_after_interval(self):
        scheduler = GameMasterScheduler()
        self.assertFalse(scheduler.note_mita_reply("conv", interval=2))
        self.assertTrue(scheduler.note_mita_reply("conv", interval=2))

    def test_action_executor_targets_one_present_mita_and_rejects_unknown(self):
        registry = GameMasterDirectiveRegistry()
        executor = GameMasterActionExecutor(registry)
        response = GameMasterResponse.model_validate({"actions": [
            {"type": "upsert_rule", "target": "Mita", "key": "task", "instruction": "Meow", "lifetime": "scene"},
            {"type": "route", "target": "actor-mita", "instruction": "Meow now."},
            {"type": "route", "target": "Unknown", "instruction": "Never run."},
        ]})
        result = executor.apply(
            response,
            conversation_id="conv",
            participants=[{"actor_id": "actor-mita", "character_id": "Mita", "can_speak": True, "is_active": True}],
            turn_index=3,
            source="user_director",
        )
        self.assertTrue(result.had_action)
        self.assertEqual(result.route_target_actor_id, "actor-mita")
        self.assertEqual(len(registry.snapshot("conv")), 1)


if __name__ == "__main__":
    unittest.main()