from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.history_controller import HistoryController
from managers.action_memory import requested_actions_from_structured, render_requested_actions
from managers.working_state_manager import WorkingStateManager
from schemas.structured_response import StructuredResponse, WorkingState


class _Character:
    def __init__(self) -> None:
        self.variables: dict[str, object] = {}

    def get_variable(self, key, default=None):
        return self.variables.get(key, default)


class WorkingStateAndActionMemoryTests(unittest.TestCase):
    def test_working_state_is_bounded_and_rendered_separately(self):
        manager = WorkingStateManager().bind("Mita", "Mita")
        manager.update(
            WorkingState(
                focus="Follow the dance test",
                situation=["Dance_07 was requested", "The player is testing continuity"],
                assumptions=["The player may want a practical answer"],
                open_loops=["Check whether the music matters"],
                next_steps=["Respond from the active test"],
            ),
            max_chars=400,
        )
        prompt = manager.format_for_prompt()
        self.assertIn("[WORKING STATE]", prompt)
        self.assertIn("Focus: Follow the dance test", prompt)
        self.assertNotIn("chain-of-thought", prompt)
        manager.clear()
        self.assertEqual(manager.format_for_prompt(), "")

    def test_action_projection_uses_requested_structured_actions_only(self):
        records = requested_actions_from_structured({
            "segments": [{
                "text": "Смотри!",
                "animations": ["Dance_07"],
                "commands": ["music:track_3"],
                "intents": [{"type": "inventory.collect", "payload": {"id": "key"}}],
            }],
            "memory_add": ["normal|not an action"],
        })
        self.assertEqual(records, [
            "animation: Dance_07",
            "command: music:track_3",
            'intent: inventory.collect {"id":"key"}',
        ])
        rendered = render_requested_actions(records)
        self.assertIn("[REQUESTED ACTIONS BY YOU]", rendered)
        self.assertNotIn("performed", rendered.lower())

    def test_action_tail_changes_only_when_summary_commits(self):
        controller = HistoryController.__new__(HistoryController)
        controller._get_setting = lambda key, default=None: {
            "ENABLE_ACTION_MEMORY": True,
            "ACTION_MEMORY_RETAIN_LAST": 2,
        }.get(key, default)
        character = _Character()
        character.variables[controller._ACTION_MEMORY_RETAINED_VAR] = '["animation: Old"]'
        compressed = [
            {"role": "assistant", "structured_data": {"segments": [{"animations": ["Dance_01"]}]}},
            {"role": "assistant", "structured_data": {"segments": [{"animations": ["Dance_02"]}]}},
        ]
        retained = controller._next_retained_action_requests(character, compressed)
        self.assertEqual(retained, ["animation: Dance_01", "animation: Dance_02"])
        character.variables[controller._ACTION_MEMORY_RETAINED_VAR] = retained
        context = controller._build_action_memory_context(
            character,
            [{"role": "assistant", "structured_data": {"segments": [{"animations": ["Dance_03"]}]}}],
        )
        self.assertIn("Dance_01", context)
        self.assertIn("Dance_02", context)
        self.assertIn("Dance_03", context)

    def test_working_state_can_be_removed_from_provider_schema(self):
        full = StructuredResponse.openai_response_format()["json_schema"]["schema"]
        without = StructuredResponse.openai_response_format(
            exclude_fields={"working_state"},
        )["json_schema"]["schema"]
        self.assertIn("working_state", full["properties"])
        self.assertNotIn("working_state", without["properties"])


if __name__ == "__main__":
    unittest.main()
