"""Regression coverage for declarative Gemini model capability profiles."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.gemini_provider import GeminiProvider
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase
from presets.api_templates import API_TEMPLATES_DATA
from presets.model_profiles import resolve_model_profile


def _google_profiles() -> list[dict]:
    template = next(item for item in API_TEMPLATES_DATA if item["id"] == 3)
    return template["model_profiles"]


class ModelProfileResolutionTests(unittest.TestCase):
    def test_exact_profile_wins_and_preset_override_is_deep_merged(self) -> None:
        profiles = [
            {
                "id": "gemini-3-family",
                "match": "gemini-3.*",
                "match_mode": "glob",
                "parameters": ["temperature"],
                "thinking": {"transport": "level", "default_level": "low"},
            },
            {
                "id": "gemini-3.6-flash",
                "match": "gemini-3.6-flash",
                "parameters": ["max_tokens"],
                "thinking": {
                    "transport": "level",
                    "disabled_level": "minimal",
                },
            },
        ]

        resolved = resolve_model_profile(
            "gemini-3.6-flash",
            profiles,
            {
                "parameters": ["temperature", "max_tokens"],
                "thinking": {"default_level": "high"},
            },
        )

        self.assertEqual(resolved["id"], "gemini-3.6-flash")
        self.assertEqual(resolved["parameters"], ["temperature", "max_tokens"])
        self.assertEqual(
            resolved["thinking"],
            {
                "transport": "level",
                "disabled_level": "minimal",
                "default_level": "high",
            },
        )
        self.assertNotIn("default_level", profiles[1]["thinking"])

    def test_unknown_direct_gemini_model_receives_safe_profile(self) -> None:
        resolved = resolve_model_profile(
            "gemini-4-future-preview",
            _google_profiles(),
            default_safe=True,
        )

        self.assertTrue(resolved["safe_mode"])
        self.assertEqual(resolved["parameters"], [])
        self.assertEqual(resolved["thinking"], {"transport": "none"})
        self.assertFalse(resolved["native_structured_output"])

    def test_more_specific_glob_profile_wins(self) -> None:
        profiles = [
            {"id": "family", "match": "gemini-*", "match_mode": "glob"},
            {"id": "flash", "match": "gemini-3.*-flash", "match_mode": "glob"},
        ]

        self.assertEqual(resolve_model_profile("gemini-3.7-flash", profiles)["id"], "flash")

    def test_safe_mode_override_clears_model_generation_options(self) -> None:
        resolved = resolve_model_profile(
            "gemini-3.6-flash",
            _google_profiles(),
            {"safe_mode": True},
            default_safe=True,
        )

        self.assertTrue(resolved["safe_mode"])
        self.assertEqual(resolved["parameters"], [])
        self.assertEqual(resolved["thinking"], {"transport": "none"})


class GeminiProfilePayloadTests(unittest.TestCase):
    @staticmethod
    def _generation_config(model: str, extra: dict) -> dict:
        profile = resolve_model_profile(model, _google_profiles(), default_safe=True)
        provider = GeminiProvider.__new__(GeminiProvider)
        return provider._map_unified_params_to_generation_config(extra, model, profile)

    def test_gemini_36_disabled_thinking_uses_minimal_without_legacy_budget(self) -> None:
        config = self._generation_config(
            "gemini-3.6-flash",
            {"enable_thinking": False, "gemini_thinking_budget": 0},
        )

        self.assertEqual(config, {"thinkingConfig": {"thinkingLevel": "minimal"}})
        self.assertNotIn("thinkingBudget", config["thinkingConfig"])

    def test_gemini_25_pro_clamps_budget_and_uses_minimum_when_disabled(self) -> None:
        profile = resolve_model_profile("gemini-2.5-pro", _google_profiles(), default_safe=True)
        provider = GeminiProvider.__new__(GeminiProvider)

        self.assertEqual(
            provider._map_unified_params_to_generation_config(
                {"enable_thinking": True, "gemini_thinking_budget": 999999},
                "gemini-2.5-pro",
                profile,
            )["thinkingConfig"]["thinkingBudget"],
            32768,
        )
        self.assertEqual(
            provider._map_unified_params_to_generation_config(
                {"enable_thinking": False}, "gemini-2.5-pro", profile
            )["thinkingConfig"]["thinkingBudget"],
            128,
        )

    def test_gemini_25_flash_preserves_dynamic_budget(self) -> None:
        profile = resolve_model_profile("gemini-2.5-flash", _google_profiles(), default_safe=True)
        provider = GeminiProvider.__new__(GeminiProvider)

        self.assertEqual(
            provider._map_unified_params_to_generation_config(
                {"enable_thinking": True, "gemini_thinking_budget": -1},
                "gemini-2.5-flash",
                profile,
            )["thinkingConfig"]["thinkingBudget"],
            -1,
        )

    def test_gemini_3_profiles_do_not_allow_sampling_parameters(self) -> None:
        profiles = _google_profiles()
        provider = GeminiProvider.__new__(GeminiProvider)

        for model in ("gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"):
            profile = resolve_model_profile(model, profiles, default_safe=True)
            config = provider._map_unified_params_to_generation_config(
                {"temperature": 0.2, "top_p": 0.8, "top_k": 10, "max_tokens": 128},
                model,
                profile,
            )
            self.assertEqual(config, {"maxOutputTokens": 128}, model)

    def test_existing_gemini_31_flash_lite_uses_its_declared_profile(self) -> None:
        profile = resolve_model_profile("gemini-3.1-flash-lite", _google_profiles(), default_safe=True)

        self.assertEqual(profile["id"], "gemini-3.1-flash-lite")
        self.assertFalse(profile["safe_mode"])
        self.assertEqual(profile["thinking"]["disabled_level"], "minimal")

    def test_gemini_37_disabled_thinking_uses_low_level(self) -> None:
        config = self._generation_config("gemini-3.7-flash", {"enable_thinking": False})

        self.assertEqual(config, {"thinkingConfig": {"thinkingLevel": "low"}})
        self.assertNotIn("thinkingBudget", config["thinkingConfig"])

    def test_unknown_gemini_model_sends_no_generation_configuration(self) -> None:
        config = self._generation_config(
            "gemini-4-future-preview",
            {
                "enable_thinking": False,
                "temperature": 0.6,
                "max_tokens": 64,
                "top_p": 0.8,
                "top_k": 20,
            },
        )

        self.assertEqual(config, {})

    def test_safe_profile_keeps_app_json_parser_without_native_schema(self) -> None:
        profile = resolve_model_profile(
            "gemini-future-alias",
            _google_profiles(),
            default_safe=True,
        )

        self.assertTrue(profile["safe_mode"])
        self.assertFalse(profile["native_structured_output"])
        self.assertFalse(
            GeminiProvider._should_send_native_structured_output(
                {"structured_output": True, "model_profile": profile}
            )
        )
        self.assertTrue(
            GeminiProvider._should_send_native_structured_output(
                {"structured_output": True, "model_profile": {}}
            )
        )


class OpenRouterProfilePayloadTests(unittest.TestCase):
    def test_openrouter_reasoning_uses_explicit_effort(self) -> None:
        payload: dict = {}
        request = types.SimpleNamespace(
            extra={"enable_thinking": True, "reasoning_effort": "medium"},
            capabilities={"reasoning_control": "openrouter"},
        )

        OpenAIHTTPProviderBase._apply_reasoning(payload, request)

        self.assertEqual(payload["reasoning"], {"enabled": True, "effort": "medium"})


if __name__ == "__main__":
    unittest.main()
