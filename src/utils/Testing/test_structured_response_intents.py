from __future__ import annotations

import json
import logging
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from main_logger import logger as app_logger
from schemas.structured_response import (
    RESPONSE_PROTOCOL_VERSION,
    StructuredResponse,
)
from utils.structured_response_parser import (
    parse_structured_response,
    structured_response_to_result_dict,
)


def _segment_excl_for_caps(caps: dict) -> set:
    """Reproduce the provider decision: intents hidden unless schema_intents."""
    seg = set(caps.get("structured_segment_exclude_fields") or ())
    if not caps.get("schema_intents", False):
        seg.add("intents")
    return seg


def _openai_segment_props(schema_payload: dict) -> dict:
    schema = schema_payload["json_schema"]["schema"]
    defs = schema.get("$defs", {})
    if "ResponseSegment" in defs:
        return defs["ResponseSegment"].get("properties", {})
    items = schema["properties"]["segments"]["items"]
    return items.get("properties", {})


def _gemini_segment_props(schema: dict) -> dict:
    items = schema["properties"]["segments"]["items"]
    return items.get("properties", {})


class IntentsPassthroughTests(unittest.TestCase):
    def test_intents_not_lost_by_parser(self) -> None:
        payload = {
            "segments": [
                {
                    "text": "Держи яблоко.",
                    "intents": [
                        {"type": "inventory.collect", "payload": {"object": "Apple"}}
                    ],
                }
            ],
            "attitude_change": 0,
            "boredom_change": 0,
            "stress_change": 0,
        }
        response = parse_structured_response(json.dumps(payload, ensure_ascii=False))
        seg = response.segments[0]
        self.assertEqual(len(seg.intents), 1)
        self.assertEqual(seg.intents[0].type, "inventory.collect")
        self.assertEqual(seg.intents[0].payload, {"object": "Apple"})

        result = structured_response_to_result_dict(response)
        self.assertEqual(
            result["segments"][0]["intents"],
            [{"type": "inventory.collect", "payload": {"object": "Apple"}}],
        )

    def test_intents_default_payload_when_missing(self) -> None:
        payload = {"segments": [{"text": "hi", "intents": [{"type": "door.open"}]}]}
        response = parse_structured_response(json.dumps(payload))
        self.assertEqual(response.segments[0].intents[0].payload, {})

    def test_invalid_intent_dropped_with_warning(self) -> None:
        payload = {
            "segments": [
                {
                    "text": "hi",
                    "intents": [
                        {"type": "", "payload": {"a": 1}},       # empty type
                        {"payload": {"a": 1}},                     # missing type
                        "not-an-object",                            # not a dict
                        {"type": "ok.intent", "payload": "bad"},   # bad payload -> {}
                    ],
                }
            ]
        }
        with self.assertLogs(app_logger, level="WARNING") as captured:
            response = parse_structured_response(json.dumps(payload))
        intents = response.segments[0].intents
        self.assertEqual([i.type for i in intents], ["ok.intent"])
        self.assertEqual(intents[0].payload, {})
        self.assertTrue(any("intent" in m.lower() for m in captured.output))

    def test_unknown_intent_type_not_blocked(self) -> None:
        payload = {
            "segments": [
                {"text": "hi", "intents": [{"type": "totally.new.unity.thing", "payload": {"x": 5}}]}
            ]
        }
        response = parse_structured_response(json.dumps(payload))
        self.assertEqual(response.segments[0].intents[0].type, "totally.new.unity.thing")

    def test_commands_and_interactions_still_work(self) -> None:
        payload = {
            "segments": [
                {
                    "text": "sit",
                    "commands": ["walktoplayernear"],
                    "interactions": ["Chair_1"],
                }
            ]
        }
        response = parse_structured_response(json.dumps(payload))
        result = structured_response_to_result_dict(response)
        seg = result["segments"][0]
        self.assertEqual(seg["commands"], ["walktoplayernear"])
        self.assertEqual(seg["interactions"], ["Chair_1"])
        # intents omitted from wire dict when empty
        self.assertNotIn("intents", seg)


class ProtocolVersionTests(unittest.TestCase):
    def test_protocol_version_stamped(self) -> None:
        response = parse_structured_response(json.dumps({"segments": [{"text": "hi"}]}))
        result = structured_response_to_result_dict(response)
        self.assertEqual(result["response_protocol_version"], RESPONSE_PROTOCOL_VERSION)


class SchemaVisibilityTests(unittest.TestCase):
    def test_intents_hidden_from_schema_by_default(self) -> None:
        caps: dict = {}  # selected DSL template did not opt in
        seg_excl = _segment_excl_for_caps(caps)
        openai = StructuredResponse.openai_response_format(exclude_segment_fields=seg_excl)
        self.assertNotIn("intents", _openai_segment_props(openai))
        gemini = StructuredResponse.gemini_schema_dict(exclude_segment_fields=seg_excl)
        self.assertNotIn("intents", _gemini_segment_props(gemini))

    def test_intents_present_when_enabled(self) -> None:
        caps = {"schema_intents": True}
        seg_excl = _segment_excl_for_caps(caps)  # -> empty
        openai = StructuredResponse.openai_response_format(
            exclude_segment_fields=seg_excl or None
        )
        self.assertIn("intents", _openai_segment_props(openai))
        gemini = StructuredResponse.gemini_schema_dict(
            exclude_segment_fields=seg_excl or None
        )
        self.assertIn("intents", _gemini_segment_props(gemini))

    def test_reasoning_hidden_from_native_schema_when_disabled(self) -> None:
        # provider adds "reasoning" to exclude_fields when schema_reasoning is off
        openai = StructuredResponse.openai_response_format(exclude_fields={"reasoning"})
        self.assertNotIn("reasoning", openai["json_schema"]["schema"]["properties"])
        gemini = StructuredResponse.gemini_schema_dict(exclude_fields={"reasoning"})
        self.assertNotIn("reasoning", gemini["properties"])

    def test_reasoning_present_when_enabled(self) -> None:
        openai = StructuredResponse.openai_response_format()
        self.assertIn("reasoning", openai["json_schema"]["schema"]["properties"])


class StatSanitizeTests(unittest.TestCase):
    def test_non_finite_stats_collapse_to_zero(self) -> None:
        model = StructuredResponse(
            segments=[{"text": "hi"}],
            attitude_change=float("inf"),
            boredom_change=float("nan"),
            stress_change=1.0,
        )
        self.assertEqual(model.attitude_change, 0.0)
        self.assertEqual(model.boredom_change, 0.0)
        self.assertEqual(model.stress_change, 1.0)


if __name__ == "__main__":
    unittest.main()
