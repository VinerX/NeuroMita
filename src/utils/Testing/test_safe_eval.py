from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from DSL.post_dsl_engine import PostDslError, PostDslInterpreter
from managers.tools.builtin.calc import CalculatorTool


class _StubCharacter:
    char_id = "Stub"

    def __init__(self) -> None:
        self.variables = {"count": 3, "enabled": True}
        self.app_vars = {"suffix": "ok"}


class SafeEvalTests(unittest.TestCase):
    def _make_post_interpreter(self) -> PostDslInterpreter:
        interp = PostDslInterpreter.__new__(PostDslInterpreter)
        interp.character = _StubCharacter()
        interp.resolver = None
        interp.rules = []
        interp.debug_display_config = {}
        interp._local_vars = {"label": "value"}
        interp._declared_local_vars = {"label"}
        return interp

    def test_post_dsl_allows_expected_expressions(self) -> None:
        interp = self._make_post_interpreter()
        result = interp._eval_dsl_expression(
            'str(count + 2) if enabled and count > 1 else default("missing", "fallback")',
            {},
        )
        self.assertEqual(result, "5")

    def test_post_dsl_rejects_unsafe_constructs(self) -> None:
        interp = self._make_post_interpreter()
        with self.assertRaises(PostDslError):
            interp._eval_dsl_expression('__import__("os")', {})
        with self.assertRaises(PostDslError):
            interp._eval_dsl_expression("label.__class__", {})

    def test_calculator_accepts_arithmetic_and_rejects_names(self) -> None:
        tool = CalculatorTool()
        self.assertEqual(tool.run("2 + 3 * 4"), "14")
        self.assertIn("Ошибка калькулятора", tool.run("value + 1"))


if __name__ == "__main__":
    unittest.main()
