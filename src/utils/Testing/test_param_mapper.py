import unittest
import importlib.util
from pathlib import Path

_PARAM_MAPPER_PATH = Path(__file__).resolve().parents[2] / "handlers" / "llm_providers" / "param_mapper.py"
_SPEC = importlib.util.spec_from_file_location("test_param_mapper_module", _PARAM_MAPPER_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
drop_unsupported_thinking_params = _MODULE.drop_unsupported_thinking_params


class ThinkingParamFilterTests(unittest.TestCase):
    def test_generic_openai_compat_drops_thinking_params(self):
        params = {
            "temperature": 0.7,
            "enable_thinking": True,
            "thinking_budget": 1024,
            "gemini_thinking_budget": 8192,
        }

        filtered = drop_unsupported_thinking_params(
            params,
            provider_name="common",
            capabilities={},
        )

        self.assertEqual(filtered, {"temperature": 0.7})

    def test_openrouter_keeps_reasoning_controls(self):
        params = {
            "enable_thinking": True,
            "thinking_budget": 1024,
        }

        filtered = drop_unsupported_thinking_params(
            params,
            provider_name="common",
            capabilities={"reasoning_control": "openrouter"},
        )

        self.assertEqual(filtered, params)

    def test_gemini_keeps_enable_and_budget_but_not_openai_thinking_budget(self):
        params = {
            "enable_thinking": True,
            "thinking_budget": 1024,
            "gemini_thinking_budget": 4096,
        }

        filtered = drop_unsupported_thinking_params(
            params,
            provider_name="gemini",
            capabilities={},
        )

        self.assertEqual(
            filtered,
            {
                "enable_thinking": True,
                "gemini_thinking_budget": 4096,
            },
        )


if __name__ == "__main__":
    unittest.main()
