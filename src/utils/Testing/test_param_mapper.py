import sys
import types
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase
from handlers.llm_providers.param_mapper import build_unified_generation_params


def _req(*, enable_thinking=None, reasoning_control=None, thinking_budget=None, reasoning_effort=None):
    extra = {}
    if enable_thinking is not None:
        extra["enable_thinking"] = enable_thinking
    if thinking_budget is not None:
        extra["thinking_budget"] = thinking_budget
    if reasoning_effort is not None:
        extra["reasoning_effort"] = reasoning_effort
    capabilities = {}
    if reasoning_control is not None:
        capabilities["reasoning_control"] = reasoning_control
    return types.SimpleNamespace(extra=extra, capabilities=capabilities)


class ApplyReasoningTests(unittest.TestCase):
    """Thinking is strictly opt-in via a declared reasoning_control transport."""

    def test_legacy_provider_never_receives_thinking(self):
        # Generic OpenAI-compatible (e.g. Mistral): no reasoning_control declared.
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(payload, _req(enable_thinking=True, thinking_budget=1024))
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning", payload)

    def test_absent_enable_thinking_emits_nothing(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(payload, _req(reasoning_control="openrouter"))
        self.assertEqual(payload, {})

    def test_openrouter_transport_emits_reasoning_map(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=True, reasoning_control="openrouter", thinking_budget=2048)
        )
        self.assertEqual(payload["reasoning"], {"enabled": True, "max_tokens": 2048})

    def test_openrouter_disabled_still_sent(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=False, reasoning_control="openrouter")
        )
        self.assertEqual(payload["reasoning"], {"enabled": False})

    def test_deepseek_disabled_uses_native_object(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=False, reasoning_control="deepseek")
        )
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_reasoning_effort_disabled_sends_none(self):
        # LM Studio: единственный способ заглушить мысли Gemma 4 / Qwen3.
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=False, reasoning_control="reasoning_effort")
        )
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_reasoning_effort_enabled_without_level_sends_nothing(self):
        # Без явного уровня ничего не шлём: reasoning-модели LM Studio думают по
        # умолчанию, а "medium" на модели, знающей лишь on/off (gemma-4-12b-qat),
        # даёт WARN и откат на 'on' — тот же результат, но с шумом в логах.
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=True, reasoning_control="reasoning_effort")
        )
        self.assertNotIn("reasoning_effort", payload)

    def test_reasoning_effort_honours_explicit_level(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload,
            _req(enable_thinking=True, reasoning_control="reasoning_effort", reasoning_effort="high"),
        )
        self.assertEqual(payload["reasoning_effort"], "high")

    def test_reasoning_effort_ignores_unknown_level(self):
        # Мусорный уровень трактуем как «уровень не выбран» — не шлём ничего.
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload,
            _req(enable_thinking=True, reasoning_control="reasoning_effort", reasoning_effort="ultra"),
        )
        self.assertNotIn("reasoning_effort", payload)


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class PresetReasoningOverrideTests(unittest.TestCase):
    """Переопределение пресета бьёт глобальную настройку мышления."""

    def _effective(self, global_settings, overrides):
        from managers.model_config_loader import ModelConfigLoader

        loader = ModelConfigLoader(_Settings(global_settings))
        preset = types.SimpleNamespace(generation_overrides=overrides, preset_name="test")
        return loader.effective_for_preset(loader.load(), preset, "gemma-4")

    def test_preset_can_enable_effort_over_global_off(self):
        cfg = self._effective(
            {"ENABLE_THINKING": False},
            {
                "enable_thinking": {"enabled": True, "value": True},
                "reasoning_effort": {"enabled": True, "value": "high"},
            },
        )
        self.assertTrue(cfg.enable_thinking)
        self.assertEqual(cfg.reasoning_effort, "high")

    def test_preset_effort_overrides_global_effort(self):
        cfg = self._effective(
            {"ENABLE_THINKING": True, "MODEL_REASONING_EFFORT": "low"},
            {"reasoning_effort": {"enabled": True, "value": "high"}},
        )
        self.assertEqual(cfg.reasoning_effort, "high")

    def test_disabled_override_keeps_global(self):
        cfg = self._effective(
            {"ENABLE_THINKING": True, "MODEL_REASONING_EFFORT": "low"},
            {"reasoning_effort": {"enabled": False, "value": "high"}},
        )
        self.assertEqual(cfg.reasoning_effort, "low")

    def test_empty_override_value_does_not_wipe_global(self):
        cfg = self._effective(
            {"ENABLE_THINKING": True, "MODEL_REASONING_EFFORT": "low"},
            {"reasoning_effort": {"enabled": True, "value": ""}},
        )
        self.assertEqual(cfg.reasoning_effort, "low")


def _params(**kwargs):
    base = dict(
        settings=_Settings(),
        temperature=None,
        max_response_tokens=None,
        presence_penalty=None,
        frequency_penalty=None,
        log_probability=None,
        top_k=None,
        top_p=None,
        thinking_budget=None,
    )
    base.update(kwargs)
    return build_unified_generation_params(**base)


class PresetBoolOverrideTests(unittest.TestCase):
    """Схемный CoT: переопределение пресета поверх глобальной настройки."""

    def _resolve(self, global_value, overrides):
        from controllers.model_controller import ModelController

        ctl = ModelController.__new__(ModelController)
        ctl.settings = _Settings({"SCHEMA_REASONING": global_value})
        preset = types.SimpleNamespace(generation_overrides=overrides)
        return ctl._resolve_preset_bool(preset, "schema_reasoning", "SCHEMA_REASONING", default=False)

    def test_preset_can_enable_over_global_off(self):
        self.assertTrue(self._resolve(False, {"schema_reasoning": {"enabled": True, "value": True}}))

    def test_preset_can_disable_over_global_on(self):
        self.assertFalse(self._resolve(True, {"schema_reasoning": {"enabled": True, "value": False}}))

    def test_disabled_override_falls_back_to_global(self):
        self.assertTrue(self._resolve(True, {"schema_reasoning": {"enabled": False, "value": False}}))

    def test_no_overrides_uses_global(self):
        self.assertTrue(self._resolve(True, {}))

    def test_missing_preset_uses_global(self):
        from controllers.model_controller import ModelController

        ctl = ModelController.__new__(ModelController)
        ctl.settings = _Settings({"SCHEMA_REASONING": True})
        # резолв пресета мог упасть — тогда остаётся глобальная настройка
        self.assertTrue(ctl._resolve_preset_bool(None, "schema_reasoning", "SCHEMA_REASONING", default=False))


class ReasoningEffortParamTests(unittest.TestCase):
    """Глубина размышлений едет дальше только вместе с включённым thinking."""

    def test_effort_passed_when_thinking_enabled(self):
        self.assertEqual(
            _params(enable_thinking=True, reasoning_effort="high")["reasoning_effort"], "high"
        )

    def test_effort_dropped_when_thinking_disabled(self):
        self.assertNotIn("reasoning_effort", _params(enable_thinking=False, reasoning_effort="high"))

    def test_effort_absent_by_default(self):
        self.assertNotIn("reasoning_effort", _params(enable_thinking=True))


if __name__ == "__main__":
    unittest.main()
