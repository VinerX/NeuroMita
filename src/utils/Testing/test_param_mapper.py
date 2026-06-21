import sys
import types
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


def _req(*, enable_thinking=None, reasoning_control=None, thinking_budget=None):
    extra = {}
    if enable_thinking is not None:
        extra["enable_thinking"] = enable_thinking
    if thinking_budget is not None:
        extra["thinking_budget"] = thinking_budget
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


if __name__ == "__main__":
    unittest.main()
