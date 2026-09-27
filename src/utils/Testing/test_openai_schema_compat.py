from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from schemas.game_master_response import GameMasterResponse
from schemas.structured_response import StructuredResponse, build_structured_response_model
from handlers.llm_providers.openai_http_base import _next_response_format_fallback


class OpenAISchemaCompatibilityTests(unittest.TestCase):
    def test_structured_response_schema_inlines_nested_segment_refs(self) -> None:
        payload = StructuredResponse.openai_response_format()
        schema = payload["json_schema"]["schema"]

        self.assertNotIn("$defs", schema)
        self.assertIn("text", schema["properties"]["segments"]["items"]["properties"])
        self.assertFalse(any("$ref" in str(value) for value in schema.values()))

    def test_dynamic_custom_fields_are_inlined_with_validation_metadata(self) -> None:
        model = build_structured_response_model([{
            "name": "trust",
            "type": "float",
            "required": True,
            "description": "Character trust score",
            "change_min": 0,
            "change_max": 10,
        }])

        schema = model.openai_response_format()["json_schema"]["schema"]
        custom_schema = schema["properties"]["custom_fields"]
        custom_object = next(
            branch for branch in custom_schema["anyOf"]
            if branch.get("type") == "object"
        )

        self.assertEqual(custom_object["properties"]["trust"]["type"], "number")
        self.assertEqual(custom_object["properties"]["trust"]["description"], "Character trust score")
        self.assertEqual(custom_object["properties"]["trust"]["minimum"], 0)
        self.assertEqual(custom_object["properties"]["trust"]["maximum"], 10)
        self.assertIn("trust", custom_object["required"])

    def test_game_master_schema_inlines_nested_action_refs(self) -> None:
        schema = GameMasterResponse.openai_response_format()["json_schema"]["schema"]

        self.assertNotIn("$defs", schema)
        self.assertIn("type", schema["properties"]["actions"]["items"]["properties"])

    def test_json_schema_rejection_downgrades_to_json_object(self) -> None:
        payload = {"response_format": {"type": "json_schema"}}

        self.assertEqual(
            _next_response_format_fallback(payload, "response_format json_schema is unsupported"),
            {"type": "json_object"},
        )

    def test_gemini_response_schema_error_triggers_json_object_fallback(self) -> None:
        payload = {"response_format": {"type": "json_schema"}}
        error = (
            "generation_config.response_schema.properties[segments].items "
            "is not supported by this Gemini model"
        )

        self.assertEqual(
            _next_response_format_fallback(payload, error),
            {"type": "json_object"},
        )

    def test_json_object_rejection_removes_response_format(self) -> None:
        payload = {"response_format": {"type": "json_object"}}

        self.assertEqual(
            _next_response_format_fallback(
                payload,
                "response_format json_object is unsupported",
            ),
            {},
        )

    def test_unrelated_bad_request_does_not_change_response_format(self) -> None:
        payload = {"response_format": {"type": "json_schema"}}

        self.assertIsNone(_next_response_format_fallback(payload, "invalid temperature"))
        self.assertIsNone(
            _next_response_format_fallback(payload, "database schema migration failed")
        )


if __name__ == "__main__":
    unittest.main()
