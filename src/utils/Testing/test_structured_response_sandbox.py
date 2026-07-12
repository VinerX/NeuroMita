"""Проверки sandbox-ограничений structured response."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.model_controller import ModelController
from schemas.structured_response import StructuredResponse


class StructuredResponseSandboxTests(unittest.TestCase):
    _EXCLUDED = {"animations", "idle_animations"}

    def test_default_schema_keeps_animation_fields(self):
        schema = StructuredResponse.openai_response_format()["json_schema"]["schema"]
        segment_properties = schema["$defs"]["ResponseSegment"]["properties"]

        self.assertTrue(self._EXCLUDED.issubset(segment_properties))

    def test_openai_schema_excludes_only_selected_segment_fields(self):
        schema = StructuredResponse.openai_response_format(
            exclude_segment_fields=self._EXCLUDED,
        )["json_schema"]["schema"]
        segment_properties = schema["$defs"]["ResponseSegment"]["properties"]

        self.assertTrue(self._EXCLUDED.isdisjoint(segment_properties))
        self.assertIn("emotions", segment_properties)
        self.assertIn("commands", segment_properties)

    def test_gemini_schema_excludes_only_selected_segment_fields(self):
        schema = StructuredResponse.gemini_schema_dict(
            exclude_segment_fields=self._EXCLUDED,
        )
        segment_properties = schema["properties"]["segments"]["items"]["properties"]

        self.assertTrue(self._EXCLUDED.isdisjoint(segment_properties))
        self.assertIn("emotions", segment_properties)
        self.assertIn("commands", segment_properties)

    def test_legacy_animation_fields_are_cleared_after_parsing(self):
        structured = StructuredResponse.model_validate(json.loads(
            '{"segments": [{"text": "Привет", "animations": ["Wave"], '
            '"idle_animations": ["Idle"]}]}'
        ))

        ModelController._sanitize_structured_segment_fields(
            structured,
            {"structured_segment_exclude_fields": sorted(self._EXCLUDED)},
        )

        self.assertEqual(structured.segments[0].animations, [])
        self.assertEqual(structured.segments[0].idle_animations, [])
        self.assertEqual(structured.segments[0].text, "Привет")


if __name__ == "__main__":
    unittest.main()
