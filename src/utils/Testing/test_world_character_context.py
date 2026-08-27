"""Tests for objective world state and character-specific world lore."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.prompt_controller import PromptController
from domain.world_character_relations import (
    WorldContextResolver,
    get_world_character_context,
    get_world_context_text,
    load_world_contexts,
    normalize_character_id,
    normalize_world_id,
)
from managers.game_state_manager import GameState


class WorldCharacterContextTests(unittest.TestCase):
    def test_world_id_aliases_match_unity_and_legacy_payloads(self):
        self.assertEqual(normalize_world_id("CrazyHouse"), "CrazyHouse")
        self.assertEqual(normalize_world_id("crazy_house"), "CrazyHouse")
        self.assertEqual(normalize_world_id("CRAZY-HOUSE"), "CrazyHouse")

    def test_crazy_and_kind_receive_different_contexts_in_same_world(self):
        crazy = get_world_context_text("Crazy", "CrazyHouse")
        kind = get_world_context_text("Kind", "crazy_house")

        self.assertIn("your home", crazy)
        self.assertIn("keep some personal things hidden", crazy)
        self.assertIn("used to belong to you", kind)
        self.assertNotEqual(crazy, kind)

    def test_character_aliases_resolve_to_canonical_home_context(self):
        self.assertEqual(normalize_character_id("crazy_mita"), "Crazy")
        self.assertEqual(get_world_character_context("crazy_mita", "CrazyHouse")["relation"], "home")

    def test_unknown_world_is_safe_and_does_not_invent_lore(self):
        self.assertEqual(get_world_context_text("Crazy", "UnknownWorld"), "")
        self.assertEqual(
            get_world_character_context("Crazy", "UnknownWorld"),
            {"relation": "visitor", "facts": []},
        )

    def test_all_bundled_worlds_are_valid_utf8_json(self):
        worlds = load_world_contexts()
        self.assertGreaterEqual(len(worlds), 7)
        for payload in worlds.values():
            json.dumps(payload, ensure_ascii=False)

    def test_custom_resolver_supports_owner_and_fallback(self):
        resolver = WorldContextResolver({
            "ExampleHouse": {
                "display_name": "Example house",
                "owner": "Kind",
                "former_owners": ["Crazy"],
                "default_context": "This is a temporary visitor context.",
                "character_contexts": {},
            }
        })
        self.assertIn("your own home", resolver.resolve("example_house", "Kind"))
        self.assertIn("used to belong", resolver.resolve("ExampleHouse", "Crazy"))
        self.assertEqual(
            resolver.resolve("ExampleHouse", "Cappie"),
            "This is a temporary visitor context.",
        )

    def test_game_state_keeps_objective_ids_only(self):
        state = GameState()
        state.update_from_event_data({
            "worldPlayer": "CrazyHouse",
            "worldMita": "KindHouse",
        })
        prompt_state = state.to_prompt_dict()
        self.assertEqual(prompt_state["worldPlayer"], "CrazyHouse")
        self.assertEqual(prompt_state["worldMita"], "KindHouse")
        self.assertNotIn("character_world_context", prompt_state)

    def test_game_master_task_requires_a_targeted_directive(self):
        message = PromptController._build_game_master_task_message(
            "Ask the Mitas to meow."
        )

        self.assertIsNotNone(message)
        self.assertIn("[GAME_MASTER_TASK]", message["content"])
        self.assertIn("dialogue.send_system_message", message["content"])

    def test_prompt_context_is_ephemeral_system_block(self):
        message = PromptController._build_character_world_context_message({
            "character_world_context": "This is your home."
        })
        self.assertEqual(message["role"], "system")
        self.assertIn("[Character World Context]", message["content"])
        self.assertIn("This is your home.", message["content"])
        self.assertIn("temporary lore", message["content"])


if __name__ == "__main__":
    unittest.main()
