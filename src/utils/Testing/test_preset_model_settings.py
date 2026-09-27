from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from model_settings.repository import SchemaRepository
from model_settings.schema import SchemaError, SettingsSchema, localized_text
from model_settings.service import ModelSettingsService
from presets.api_templates import API_TEMPLATES_DATA


class PresetModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.service = ModelSettingsService(SchemaRepository(self.directory / "schemas"))

    def tearDown(self):
        self.temporary.cleanup()

    def test_definition_localization_accepts_application_language_code_case(self):
        labels = {"ru": "Температура", "en": "Temperature", "de": "Temperatur"}
        for language in ("RU", "ru", "Ru"):
            self.assertEqual(localized_text(labels, language), labels["ru"])
        self.assertEqual(localized_text(labels, "DE"), labels["de"])
        self.assertEqual(localized_text({"RU": labels["ru"], "EN": labels["en"]}, "ru"), labels["ru"])
        self.assertEqual(localized_text(labels, "unknown"), labels["en"])

    def test_bundled_definitions_seed_external_files_and_compile_defaults(self):
        catalog = self.service.repository.catalog()
        self.assertGreaterEqual(len(catalog), 11)
        for identifier, schema in catalog.items():
            document = self.service.create(identifier)
            self.service.compile(document, schema.data["dialect"])
            self.assertTrue((self.directory / "schemas" / (identifier + ".json")).exists())

    def test_google_level_never_sends_budget_and_preserves_false_and_zero(self):
        document = self.service.create("google-level")
        document["enabled"] = ["thinking_level", "include_thoughts", "temperature"]
        document["values"].update(thinking_level="low", include_thoughts=False, temperature="0")
        self.assertEqual(self.service.compile(document, "gemini_generate_content"), {
            "generationConfig": {"thinkingConfig": {"thinkingLevel": "low", "includeThoughts": False}, "temperature": 0.0},
        })

    def test_budget_constraints_distinguish_disabled_dynamic_and_positive(self):
        for identifier, value, valid in [
            ("google-budget", 0, True), ("google-budget", -1, True),
            ("google-budget-pro", 0, False), ("google-budget-pro", -1, True),
            ("google-budget-lite", 0, True), ("google-budget-lite", 128, False),
            ("google-budget-lite", 512, True),
        ]:
            with self.subTest(identifier=identifier, value=value):
                document = self.service.create(identifier)
                document["enabled"] = ["thinking_budget"]
                document["values"]["thinking_budget"] = value
                if valid:
                    self.assertEqual(self.service.compile(document, "gemini_generate_content")["generationConfig"]["thinkingConfig"]["thinkingBudget"], value)
                else:
                    with self.assertRaises(SchemaError):
                        self.service.compile(document, "gemini_generate_content")

    def test_json_update_adds_native_parameter_without_python_mapping(self):
        document = self.service.create("openai-compatible")
        document["values"]["temperature"] = "0.7"
        document["enabled"] = ["temperature"]
        definition = deepcopy(self.service.repository.get("openai-compatible").data)
        definition["revision"] += 1
        definition["fields"].append({
            "id": "new_parameter", "path": ["vendor_settings", "newParameter"],
            "type": "integer", "default": 7, "minimum": 1, "maximum": 9,
            "title": {"en": "New parameter"},
        })
        update = self.directory / "update.json"
        update.write_text(json.dumps(definition), encoding="utf-8")
        self.service.import_definition(update, "openai_chat_completions")
        schema, updated = self.service.resolve(document, "openai_chat_completions")
        self.assertEqual(updated["values"]["new_parameter"], 7)
        self.assertEqual(self.service.compile(document, "openai_chat_completions"), {"temperature": 0.7})
        updated["enabled"].append("new_parameter")
        self.assertEqual(self.service.compile(updated, "openai_chat_completions"), {"temperature": 0.7, "vendor_settings": {"newParameter": 7}})

    def test_external_file_edits_reload_without_restart(self):
        original = self.service.repository.get("google-level")
        path = self.directory / "schemas" / "google-level.json"
        updated = deepcopy(original.data)
        updated["revision"] += 1
        updated["fields"][0]["maximum"] = 1
        path.write_text(json.dumps(updated), encoding="utf-8")
        self.assertEqual(self.service.repository.get("google-level").fields[0]["maximum"], 1)
        self.assertEqual(original.fields[0]["maximum"], 2)

    def test_preset_definition_override_is_isolated_from_catalog_and_other_presets(self):
        first = self.service.create("openai-compatible")
        second = self.service.create("openai-compatible")
        custom = deepcopy(self.service.repository.get("openai-compatible").data)
        custom["fields"][0]["path"] = ["sampling", "temperature"]
        first["schema_override"] = custom
        first["enabled"] = second["enabled"] = ["temperature"]
        self.assertIn("sampling", self.service.compile(first, "openai_chat_completions"))
        self.assertIn("temperature", self.service.compile(second, "openai_chat_completions"))

    def test_invalid_enabled_fields_and_conflicts_block_compilation(self):
        document = self.service.create("openrouter")
        document["enabled"] = ["temperature"]
        for value in ["", "1000", "nan", "inf", True]:
            with self.subTest(value=value), self.assertRaises(SchemaError):
                document["values"]["temperature"] = value
                self.service.compile(document, "openai_chat_completions")
        document["enabled"] = ["reasoning_effort", "reasoning_max_tokens"]
        with self.assertRaises(SchemaError):
            self.service.compile(document, "openai_chat_completions")
        document["enabled"] = ["removed_parameter"]
        with self.assertRaises(SchemaError):
            self.service.compile(document, "openai_chat_completions")

    def test_google_budget_and_level_fields_cannot_be_combined(self):
        definition = deepcopy(self.service.repository.get("google-level").data)
        schema = SettingsSchema.from_dict(definition)
        with self.assertRaises(SchemaError):
            schema.compile({"thinking_level": "low", "thinking_budget": 0}, ["thinking_level", "thinking_budget"])

    def test_customization_preserves_values_and_removes_explicitly_deleted_parameters(self):
        document = self.service.create("google-level")
        document["values"]["max_tokens"] = 4096
        document["enabled"] = ["max_tokens", "thinking_level"]
        definition = deepcopy(self.service.repository.get("google-level").data)
        definition["fields"] = [field for field in definition["fields"] if field["id"] != "thinking_level"]
        definition["fields"].append({"id": "custom_seed", "path": ["generationConfig", "vendor-settings", "seed"], "type": "integer", "default": 42})
        customized = self.service.customize(document, definition, "gemini_generate_content")
        self.assertEqual(customized["values"]["max_tokens"], 4096)
        self.assertEqual(customized["values"]["custom_seed"], 42)
        self.assertEqual(customized["enabled"], ["max_tokens"])
        customized["enabled"].append("custom_seed")
        self.assertEqual(self.service.compile(customized, "gemini_generate_content")["generationConfig"], {"maxOutputTokens": 4096, "vendor-settings": {"seed": 42}})
        with self.assertRaises(SchemaError):
            self.service.customize(document, definition, "openai_chat_completions")

    def test_migration_of_local_protocol_and_router_effort_preserves_wire_behavior(self):
        local = self.service.for_preset({"protocol_id": "lmstudio_default", "generation_overrides": {"enable_thinking": {"enabled": True, "value": False}}}, "openai_chat_completions", {})
        self.assertEqual(self.service.compile(local, "openai_chat_completions")["reasoning_effort"], "none")
        router = self.service.for_preset({"protocol_id": "openrouter_default"}, "openai_chat_completions", {"ENABLE_THINKING": True, "MODEL_REASONING_EFFORT": "high", "USE_MODEL_THINKING_BUDGET": True, "MODEL_THINKING_BUDGET": 4096})
        self.assertEqual(self.service.compile(router, "openai_chat_completions")["reasoning"], {"enabled": True, "effort": "high"})

    def test_invalid_definitions_and_wrong_dialects_are_rejected_before_installation(self):
        for path in [["messages"], ["model"], ["stream"], ["response_format"], ["generationConfig", "responseJsonSchema"]]:
            definition = deepcopy(self.service.repository.get("google-level").data)
            definition["fields"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(SchemaError):
                SettingsSchema.from_dict(definition)
        document = self.service.create("google-level")
        with self.assertRaises(SchemaError):
            self.service.compile(document, "openai_chat_completions")

    def test_migration_preserves_explicit_google_disable_as_native_level(self):
        preset = deepcopy(next(p for p in API_TEMPLATES_DATA if p["id"] == 3))
        preset["default_model"] = "gemini-3.7-flash"
        preset["generation_overrides"] = {"enable_thinking": {"enabled": True, "value": False}}
        document = self.service.for_preset(preset, "gemini_generate_content", {})
        self.assertEqual(self.service.compile(document, "gemini_generate_content")["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        preset["model_settings"] = document
        preset["default_model"] = "entirely-new-model"
        self.assertEqual(self.service.for_preset(preset, "gemini_generate_content", {}), document)

    def test_resolver_carries_native_parameters_and_preset_support_into_request_settings(self):
        from managers.api_preset_resolver import ApiPresetResolver
        from types import SimpleNamespace
        document = self.service.create("google-level")
        document["support_overrides"] = {"structured_output": False}
        resolver = ApiPresetResolver({}, Mock(), model_settings_service=self.service)
        preset = {"name": "Google", "protocol_id": "google_gemini_default", "default_model": "new-model", "model_settings": document, "url": "https://test.invalid"}
        protocol = SimpleNamespace(id="google_gemini_default", dialect="gemini_generate_content", provider="gemini", capabilities={"structured_output": True}, transforms=[])
        registry = Mock()
        registry.get.return_value = protocol
        with patch("managers.api_preset_resolver.get_protocol_registry", return_value=registry), patch.object(resolver, "_load_preset_full", return_value=preset), patch.object(resolver, "_build_http_request_via_protocols_controller", return_value=("https://test.invalid", {})):
            settings = resolver.resolve(1, model_override="another-new-model")
        self.assertEqual(settings.api_model, "another-new-model")
        self.assertEqual(settings.native_parameters, self.service.compile(document, "gemini_generate_content"))
        self.assertTrue(settings.capabilities["structured_output"])
        self.assertFalse(settings.capabilities["native_structured_output"])

    def test_startup_migration_is_persisted_and_not_repeated(self):
        from controllers.api_presets_controller import ApiPresetsController
        from presets.api_protocols import API_PROTOCOLS_DATA
        from types import SimpleNamespace
        settings_directory = self.directory / "Settings"
        settings_directory.mkdir()
        (settings_directory / "api_presets.json").write_text(json.dumps({"presets": {"1001": {"id": 1001, "name": "Old", "base": 3, "default_model": "gemini-3.7-flash", "generation_overrides": {"enable_thinking": {"enabled": True, "value": False}}}}, "order": [1001]}), encoding="utf-8")
        registry = Mock()
        registry.get.side_effect = lambda identifier: SimpleNamespace(**next(p for p in API_PROTOCOLS_DATA if p["id"] == identifier))
        with patch("core.app_paths.base_dir", return_value=self.directory), patch("managers.protocol_registry.get_protocol_registry", return_value=registry), patch.object(ApiPresetsController, "_migrate_old_api_keys"):
            controller = ApiPresetsController(model_settings_service=self.service, legacy_generation_settings={"MODEL_MAX_RESPONSE_TOKENS": 4096})
            document = controller.get_full(1001)["model_settings"]
            controller.close()
            self.assertEqual(document["values"]["max_tokens"], 4096)
            with patch("model_settings.migration.migrate_generation_settings", side_effect=AssertionError("Repeated migration")):
                controller = ApiPresetsController(model_settings_service=self.service)
                self.assertEqual(controller.get_full(1001)["model_settings"], document)
                controller.close()

    def test_native_http_payload_ignores_legacy_mapper_and_reasoning(self):
        from handlers.llm_providers.base import LLMRequest
        from handlers.llm_providers.common_provider import CommonProvider
        provider = CommonProvider()
        req = LLMRequest(model="new-model", messages=[], native_parameters={"customSampling": {"seed": 42}}, capabilities={"structured_output": False}, extra={"temperature": 1000, "enable_thinking": False})
        with patch.object(provider, "_map_unified_params", side_effect=AssertionError("Legacy mapper used")):
            payload = provider._build_payload(req, req.model, [])
        self.assertEqual(payload, {"model": "new-model", "messages": [], "customSampling": {"seed": 42}})

    def test_gemini_native_parameters_bypass_legacy_profile(self):
        from handlers.llm_providers.base import LLMRequest
        from handlers.llm_providers.gemini_provider import GeminiProvider
        provider = GeminiProvider()
        req = LLMRequest(model="new-model", messages=[], native_parameters={"generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}})
        with patch.object(provider, "_map_unified_params_to_generation_config", side_effect=AssertionError("Legacy mapper used")):
            self.assertEqual(provider._generation_config(req), {"thinkingConfig": {"thinkingLevel": "low"}})

    def test_model_support_gates_native_transport_without_disabling_application_contract(self):
        document = self.service.create("google-level")
        document["support_overrides"] = {"structured_output": False, "tools_native": True, "streaming": False}
        caps = self.service.capabilities(document, "gemini_generate_content", {"structured_output": True, "tools_native": False, "streaming": True})
        self.assertTrue(caps["structured_output"])
        self.assertFalse(caps["native_structured_output"])
        self.assertFalse(caps["tools_native"])
        self.assertFalse(caps["streaming"])
        from handlers.llm_providers.gemini_provider import GeminiProvider
        self.assertFalse(GeminiProvider._should_send_native_structured_output(caps))

    def test_sdk_sends_arbitrary_native_fields_and_respects_disabled_native_schema(self):
        import httpx
        from openai import OpenAI
        from handlers.llm_providers.openai_provider import OpenAIProvider
        from handlers.llm_providers.base import LLMRequest
        captured = []

        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": "new-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})

        client = OpenAI(api_key="test", base_url="https://test.invalid/v1", http_client=httpx.Client(transport=httpx.MockTransport(respond)))

        class Provider(OpenAIProvider):
            def is_applicable(self, req):
                return True

            def _get_client(self, req):
                return client

        provider = Provider()
        request = LLMRequest(model="new-model", messages=[{"role": "user", "content": "Hello"}], dialect_id="openai_chat_completions", native_parameters={"vendor_settings": {"budget": 0, "thinking": False}}, capabilities={"structured_output": True, "native_structured_output": False})
        response = provider.generate(request)
        self.assertEqual(response.text, "OK")
        self.assertEqual(captured[0]["vendor_settings"], {"budget": 0, "thinking": False})
        self.assertNotIn("response_format", captured[0])

    def test_presets_save_reload_and_reject_invalid_values_without_mutation(self):
        from controllers.api_presets_controller import ApiPresetsController
        from presets.api_protocols import API_PROTOCOLS_DATA
        from types import SimpleNamespace
        registry = Mock()
        registry.get.side_effect = lambda identifier: SimpleNamespace(**next(p for p in API_PROTOCOLS_DATA if p["id"] == identifier))
        registry.pick_default.return_value = SimpleNamespace(id="openai_compatible_default")
        with patch("core.app_paths.base_dir", return_value=self.directory), patch("managers.protocol_registry.get_protocol_registry", return_value=registry), patch.object(ApiPresetsController, "_migrate_old_api_keys"):
            controller = ApiPresetsController(model_settings_service=self.service)
            try:
                custom_id = controller.save_custom({"name": "Custom Router", "protocol_id": "openrouter_default"})
                self.assertEqual(controller.get_full(custom_id)["model_settings"]["schema_id"], "openrouter")
                document = self.service.create("google-level")
                identifier = controller.save_custom({"name": "Preset", "base": 3, "model_settings": document})
                exported = controller.get_full(identifier)
                self.assertEqual(exported["model_settings"], document)
                saved = json.loads(controller.presets_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["presets"][str(identifier)]["model_settings"], document)
                bad = deepcopy(document)
                bad["enabled"] = ["temperature"]
                bad["values"]["temperature"] = 1000
                with self.assertRaises(SchemaError):
                    controller.save_custom({"id": identifier, "name": "Broken", "base": 3, "model_settings": bad})
                self.assertEqual(controller.get_full(identifier)["name"], "Preset")
                controller._load_presets_only()
                self.assertEqual(controller.get_full(identifier)["model_settings"], document)
                path = self.directory / "export.json"
                self.assertTrue(controller.export_preset(identifier, str(path)))
                imported = controller.import_preset(str(path))
                new_document = controller.get_full(imported)["model_settings"]
                self.assertEqual(new_document["values"], document["values"])
                self.assertIn("schema_override", new_document)
                self.assertEqual(self.service.compile(new_document, "gemini_generate_content"), self.service.compile(document, "gemini_generate_content"))
            finally:
                controller.close()


if __name__ == "__main__":
    unittest.main()
