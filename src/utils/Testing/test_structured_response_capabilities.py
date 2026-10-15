from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.contracts import RuntimeCapabilities
from services.structured_response_capabilities import (
    resolve_structured_response_capabilities,
)


class _Settings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class StructuredResponseCapabilitiesTests(unittest.TestCase):
    def resolve(self, **kwargs):
        defaults = {
            "settings": _Settings(),
            "runtime": RuntimeCapabilities(connected=True, remote_only=False),
            "character": SimpleNamespace(secret_capable=False, secret_revealed=False),
            "structured_output": True,
            "tools_enabled": False,
            "enabled_tools": (),
            "tools_mode": "native",
            "tool_depth": 0,
            "tool_max_depth": 2,
            "images_available": False,
            "has_custom_params": False,
            "schema_reasoning": False,
        }
        defaults.update(kwargs)
        return resolve_structured_response_capabilities(**defaults)

    def test_graph_tools_reminders_timers_and_image_fields_follow_actual_availability(self):
        profile = self.resolve(
            settings=_Settings(
                RAG_ENABLED=False,
                GRAPH_EXTRACTION_ENABLED=True,
                REMINDERS_ENABLED=False,
                IMAGE_INLINE_DESCRIPTION=True,
            ),
            tools_enabled=True,
            enabled_tools=("calculator",),
            images_available=True,
        )

        self.assertTrue({"entities", "relations"}.issubset(profile.excluded_fields))
        self.assertNotIn("tool_call", profile.excluded_fields)
        self.assertTrue({"reminder_add", "reminder_delete"}.issubset(profile.excluded_fields))
        self.assertIn("timer_add", profile.excluded_fields)
        self.assertNotIn("image_description", profile.excluded_fields)

    def test_tools_off_mode_and_exhausted_depth_remove_tool_call(self):
        for kwargs in (
            {"tools_enabled": False, "enabled_tools": ("calculator",)},
            {"tools_enabled": True, "enabled_tools": ("calculator",), "tools_mode": "off"},
            {"tools_enabled": True, "enabled_tools": ("calculator",), "tool_depth": 2},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertIn("tool_call", self.resolve(**kwargs).excluded_fields)

        schema_mode = self.resolve(
            tools_enabled=True, enabled_tools=("calculator",), tools_mode="schema"
        )
        self.assertNotIn("tool_call", schema_mode.excluded_fields)
        self.assertIn(
            "tool_call",
            schema_mode.at_tool_depth(schema_mode.tool_max_depth).excluded_fields,
        )

    def test_graph_inline_mode_is_not_required_by_structured_graph_storage(self):
        profile = self.resolve(
            settings=_Settings(
                RAG_ENABLED=True,
                GRAPH_EXTRACTION_ENABLED=True,
                GRAPH_EXTRACTION_INLINE=False,
            )
        )
        self.assertNotIn("entities", profile.excluded_fields)
        self.assertNotIn("relations", profile.excluded_fields)

    def test_working_state_and_custom_fields_use_their_own_gates(self):
        enabled = self.resolve(
            settings=_Settings(ENABLE_WORKING_STATE=True),
            has_custom_params=True,
        )
        self.assertNotIn("working_state", enabled.excluded_fields)
        self.assertNotIn("custom_fields", enabled.excluded_fields)

        disabled = self.resolve(
            settings=_Settings(ENABLE_WORKING_STATE=False),
            has_custom_params=False,
        )
        self.assertIn("working_state", disabled.excluded_fields)
        self.assertIn("custom_fields", disabled.excluded_fields)

    def test_image_description_requires_image_context_and_inline_setting(self):
        without_images = self.resolve(
            settings=_Settings(IMAGE_INLINE_DESCRIPTION=True),
            images_available=False,
        )
        self.assertIn("image_description", without_images.excluded_fields)
        with_images = self.resolve(
            settings=_Settings(IMAGE_INLINE_DESCRIPTION=True),
            images_available=False,
        ).with_context_images([{"content": [{"type": "input_image", "image": "x"}]}])
        self.assertNotIn("image_description", with_images.excluded_fields)

    def test_secret_required_only_for_unresolved_secret_character(self):
        character = SimpleNamespace(secret_capable=True, secret_revealed=False)
        profile = self.resolve(character=character)
        self.assertNotIn("secret_exposed", profile.excluded_fields)
        self.assertIn("secret_exposed", profile.required_fields)

        revealed = self.resolve(
            character=SimpleNamespace(secret_capable=True, secret_revealed=True)
        )
        ordinary = self.resolve()
        self.assertIn("secret_exposed", revealed.excluded_fields)
        self.assertIn("secret_exposed", ordinary.excluded_fields)

    def test_remote_runtime_keeps_program_fields_and_prompt_intents_are_finalized(self):
        profile = self.resolve(
            runtime=RuntimeCapabilities(
                connected=False,
                remote_only=True,
                structured_segment_exclude_fields=("emotions", "intents"),
            ),
            settings=_Settings(ENABLE_GAMES=True),
            has_custom_params=True,
        ).with_prompt_intents(True)

        self.assertIn("emotions", profile.excluded_segment_fields)
        self.assertIn("intents", profile.excluded_segment_fields)
        self.assertNotIn("commands", profile.excluded_segment_fields)
        self.assertNotIn("music", profile.excluded_segment_fields)
        self.assertNotIn("start_game", profile.excluded_segment_fields)
        self.assertNotIn("end_game", profile.excluded_segment_fields)
        self.assertNotIn("custom_fields", profile.excluded_fields)

    def test_history_image_detection_scans_nested_provider_content(self):
        self.assertTrue(
            self.resolve().with_context_images(
                [
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
                    }
                ]
            ).images_available
        )

    def test_profile_snapshot_is_json_serializable_for_generation_capture(self):
        profile = self.resolve().with_prompt_intents(True)
        snapshot = profile.to_dict()
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)

    def test_non_strict_output_cannot_apply_unavailable_fields_but_keeps_memory_and_stats(self):
        profile = self.resolve(
            settings=_Settings(RAG_ENABLED=False, GRAPH_EXTRACTION_ENABLED=True),
            tools_enabled=False,
        )
        response = SimpleNamespace(
            entities=["Alice:person"],
            relations=["Alice|likes|tea"],
            tool_call=SimpleNamespace(name="calculator", args={}),
            memory_add=["normal|Player likes tea"],
            attitude_change=1.0,
            segments=[SimpleNamespace(emotions=["smile"], commands=["camera_snapshot"])],
        )

        profile.sanitize_response(response)

        self.assertIsNone(response.entities)
        self.assertIsNone(response.relations)
        self.assertIsNone(response.tool_call)
        self.assertEqual(response.memory_add, ["normal|Player likes tea"])
        self.assertEqual(response.attitude_change, 1.0)
        self.assertEqual(response.segments[0].emotions, ["smile"])
        self.assertEqual(response.segments[0].commands, ["camera_snapshot"])

    def test_provider_schema_mapping_and_full_model_defaults_are_preserved(self):
        from schemas.structured_response import StructuredResponse
        from services.structured_response_capabilities import provider_schema_options

        profile = self.resolve(
            character=SimpleNamespace(secret_capable=True, secret_revealed=False),
            settings=_Settings(RAG_ENABLED=False, GRAPH_EXTRACTION_ENABLED=True),
        ).with_prompt_intents(False)
        options = provider_schema_options({"structured_response_profile": profile})
        schema = StructuredResponse.openai_response_format(**{
            "exclude_fields": options["exclude_fields"],
            "exclude_segment_fields": options["exclude_segment_fields"],
            "require_fields": options["require_fields"],
        })["json_schema"]["schema"]
        properties = schema["properties"]

        self.assertNotIn("entities", properties)
        self.assertNotIn("tool_call", properties)
        self.assertNotIn("intents", properties["segments"]["items"]["properties"])
        self.assertIn("secret_exposed", schema["required"])
        nullable_secret = properties["secret_exposed"].get("anyOf", [])
        self.assertTrue(any(branch.get("type") == "null" for branch in nullable_secret))
        gemini_schema = StructuredResponse.gemini_schema_dict(**options)
        self.assertIn("secret_exposed", gemini_schema["required"])
        self.assertTrue(gemini_schema["properties"]["secret_exposed"].get("nullable"))
        minimal = StructuredResponse.model_validate({"segments": [{"text": "Hello"}]})
        self.assertIsNone(minimal.secret_exposed)
        self.assertIsNone(minimal.memory_add)
        self.assertEqual((minimal.attitude_change, minimal.boredom_change, minimal.stress_change), (0, 0, 0))
        from utils.structured_response_parser import (
            parse_structured_response_with_meta,
            structured_response_to_result_dict,
        )
        parsed = parse_structured_response_with_meta('{"segments":[{"text":"Hello"}]}').response
        saved_shape = structured_response_to_result_dict(parsed)
        self.assertEqual(saved_shape["memory_add"], [])
        self.assertEqual(
            (saved_shape["attitude_change"], saved_shape["boredom_change"], saved_shape["stress_change"]),
            (0, 0, 0),
        )

    def test_rendered_schema_prompt_uses_profile_and_keeps_program_contract(self):
        from DSL.dsl_engine import DslInterpreter

        script = Path(__file__).resolve().parents[3] / "extra" / "Prompts" / "Structural" / "response_format_json.script"

        class Resolver:
            def resolve_path(self, path):
                return path

            def load_text(self, path, _context):
                return "support_intents=True\n[<format.script>]" if path == "main_template.txt" else script.read_text(encoding="utf-8")

            def get_dirname(self, _path):
                return ""

        profile = self.resolve(
            settings=_Settings(RAG_ENABLED=False, GRAPH_EXTRACTION_ENABLED=True, REMINDERS_ENABLED=False),
            runtime=RuntimeCapabilities(connected=False, remote_only=True,
                structured_segment_exclude_fields=("emotions", "intents")),
        ).with_prompt_intents(False)
        self.assertTrue(profile.prompt_features()["response_segment_target"])
        self.assertTrue(profile.prompt_features()["response_segment_hint"])
        variables = {
            "SCHEMA_REASONING_ENABLED": False,
            "ENABLE_GAMES": False,
            "TOOLS_DESCRIPTION": "",
            "CUSTOM_PARAMS_SCHEMA": "",
            **profile.prompt_features(),
        }
        original_variables = dict(variables)
        character = SimpleNamespace(char_id="Test", variables=variables, app_vars={})
        rendered, _ = DslInterpreter(character, Resolver()).process_main_template(
            "main_template.txt", feature_overrides={"support_intents": True, **profile.prompt_features()}
        )
        output = "\n".join(rendered)

        self.assertIn('"commands"', output)
        self.assertIn('"target"', output)
        self.assertIn('"hint"', output)
        self.assertNotIn('"intents"', output)
        self.assertNotIn('"emotions"', output)
        self.assertNotIn('"entities"', output)
        self.assertNotIn('"tool_call"', output)
        self.assertNotIn('"reminder_add"', output)
        self.assertNotIn('"timer_add"', output)
        self.assertEqual(character.variables, original_variables)

    def test_rendered_schema_prompt_includes_enabled_graph_tools_secret_and_image_fields(self):
        from DSL.dsl_engine import DslInterpreter

        script = Path(__file__).resolve().parents[3] / "extra" / "Prompts" / "Structural" / "response_format_json.script"

        class Resolver:
            def resolve_path(self, path):
                return path

            def load_text(self, path, _context):
                return "support_intents=True\n[<format.script>]" if path == "main_template.txt" else script.read_text(encoding="utf-8")

            def get_dirname(self, _path):
                return ""

        profile = self.resolve(
            settings=_Settings(
                RAG_ENABLED=True,
                GRAPH_EXTRACTION_ENABLED=True,
                GRAPH_EXTRACTION_INLINE=False,
                REMINDERS_ENABLED=True,
                IMAGE_INLINE_DESCRIPTION=True,
                ENABLE_GAMES=True,
            ),
            character=SimpleNamespace(secret_capable=True, secret_revealed=False),
            tools_enabled=True,
            enabled_tools=("calculator",),
        ).with_context_images([{"parts": [{"inline_data": {"mime_type": "image/jpeg"}}]}])
        profile = profile.with_prompt_intents(True)
        character = SimpleNamespace(
            char_id="Test",
            variables={"SCHEMA_REASONING_ENABLED": False, "ENABLE_GAMES": True,
                "TOOLS_DESCRIPTION": "", "CUSTOM_PARAMS_SCHEMA": ""},
            app_vars={},
        )
        rendered, _messages = DslInterpreter(character, Resolver()).process_main_template(
            "main_template.txt",
            feature_overrides={"support_intents": True, **profile.prompt_features()},
        )
        output = "\n".join(rendered)

        for field in (
            '"intents"', '"start_game"', '"end_game"', '"entities"',
            '"relations"', '"tool_call"', '"reminder_add"', '"reminder_delete"',
            '"timer_add"', '"secret_exposed"', '"image_description"',
        ):
            self.assertIn(field, output)
        self.assertIn("short timer and is separate", output)
        self.assertIn("required by the active schema", output)


if __name__ == "__main__":
    unittest.main()
