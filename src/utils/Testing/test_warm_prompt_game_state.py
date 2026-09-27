"""The warm prompt must resolve state using its requested character id."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.model_controller import ModelController
from services.contracts import PromptBuilderService


class _Settings:
    def get(self, key, default=None):
        return default


class _Builder:
    def __init__(self):
        self.request = None

    def build(self, request):
        self.request = request
        return SimpleNamespace(messages=[{"role": "system", "content": "ready"}])


class WarmPromptGameStateTests(unittest.TestCase):
    def test_warm_prompt_uses_scoped_state_for_requested_character(self):
        controller = object.__new__(ModelController)
        character = SimpleNamespace(char_id="Kind", display_name="Kind")
        controller._get_character_ref = lambda character_id: character if character_id == "Kind" else None
        controller._resolve_chat_preset_id = lambda _character_id: 1
        controller._get_game_state_for_character = lambda character_id: {
            "runtime_rules": f"rules for {character_id}"
        }
        controller.preset_resolver = SimpleNamespace(resolve=lambda _preset_id: SimpleNamespace(capabilities={}))
        controller.settings = _Settings()
        controller.model = SimpleNamespace(cfg=SimpleNamespace(memory_limit=20))
        builder = _Builder()

        with patch("controllers.model_controller.use", return_value=builder):
            result = controller._warm_base_prompt("Kind", "answer")

        self.assertIsNotNone(result)
        self.assertEqual(builder.request.game_state["runtime_rules"], "rules for Kind")


if __name__ == "__main__":
    unittest.main()
