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

    def test_reasoning_effort_enabled_defaults_to_medium(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload, _req(enable_thinking=True, reasoning_control="reasoning_effort")
        )
        self.assertEqual(payload["reasoning_effort"], "medium")

    def test_reasoning_effort_honours_explicit_level(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload,
            _req(enable_thinking=True, reasoning_control="reasoning_effort", reasoning_effort="high"),
        )
        self.assertEqual(payload["reasoning_effort"], "high")

    def test_reasoning_effort_rejects_unknown_level(self):
        payload = {}
        OpenAIHTTPProviderBase._apply_reasoning(
            payload,
            _req(enable_thinking=True, reasoning_control="reasoning_effort", reasoning_effort="ultra"),
        )
        self.assertEqual(payload["reasoning_effort"], "medium")


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


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
