from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from DSL.dsl_engine import DslError, DslInterpreter
from DSL.post_dsl_engine import PostDslError, PostDslInterpreter
from characters.character import _evaluate_custom_param_formula
from core.safe_eval import safe_eval_expression
from managers.tools.builtin.calc import CalculatorTool


class _StubCharacter:
    char_id = "Stub"

    def __init__(self) -> None:
        self.variables = {"count": 3, "enabled": True}
        self.app_vars = {"suffix": "ok"}

    def set_variable(self, name, value) -> None:
        self.variables[name] = value


class _StubResolver:
    def __init__(self, text: str) -> None:
        self.text = text

    def resolve_path(self, path: str) -> str:
        return path

    def load_text(self, _path: str, _context: str) -> str:
        return self.text


class _MultiFileResolver:
    """Resolver backed by an in-memory {path: content} map for template tests."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def resolve_path(self, path: str) -> str:
        return path

    def load_text(self, path: str, _context: str) -> str:
        return self.files[path]

    def get_dirname(self, _path: str) -> str:
        return ""


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

    def test_safe_eval_supports_formatted_strings_without_attribute_access(self) -> None:
        result = safe_eval_expression(
            'f"{name}: {score:.1f}"',
            names={"name": "Mita", "score": 4.25},
        )
        self.assertEqual(result, "Mita: 4.2")

        with self.assertRaises(ValueError):
            safe_eval_expression('f"{name.__class__}"', names={"name": "Mita"})

    def test_main_template_declares_intent_support_explicitly(self) -> None:
        character = _StubCharacter()
        interpreter = DslInterpreter(
            character,
            resolver=_StubResolver("support_intents=True\n"),
        )

        blocks, messages = interpreter.process_main_template("main_template.txt")

        self.assertEqual(blocks, [])
        self.assertEqual(messages, [])
        self.assertIs(interpreter.get_prompt_feature("support_intents"), True)
        self.assertNotIn("support_intents", character.variables)

        interpreter.resolver = _StubResolver("support_intents=False\n")
        interpreter.process_main_template("main_template.txt")
        self.assertIs(interpreter.get_prompt_feature("support_intents"), False)

    def test_add_context_info_uses_separate_volatile_channel(self) -> None:
        files = {
            "main_template.txt": "behavior_state=custom\n[<band.script>]\n",
            "band.script": (
                'ADD_CONTEXT_INFO "Attitude: 62/100 — warm"\n'
                'ADD_SYSTEM_INFO "static change rule"\n'
            ),
        }
        interpreter = DslInterpreter(_StubCharacter(), resolver=_MultiFileResolver(files))

        blocks, messages = interpreter.process_main_template("main_template.txt")

        # ADD_SYSTEM_INFO stays in the static channel, ADD_CONTEXT_INFO does not.
        self.assertEqual(messages, ["static change rule"])
        self.assertEqual(interpreter.get_context_infos(), ["Attitude: 62/100 — warm"])
        self.assertEqual(blocks, [])
        self.assertEqual(interpreter.get_prompt_feature("behavior_state"), "custom")

    def test_template_at_marker_routes_include_to_context(self) -> None:
        files = {
            "main_template.txt": "[<Main/identity.txt>]\n[<@ Structural/band.txt>]\n",
            "Main/identity.txt": "You are a character.",
            "Structural/band.txt": "[Behavior State]\nAttitude: 62/100 — warm",
        }
        interpreter = DslInterpreter(_StubCharacter(), resolver=_MultiFileResolver(files))
        blocks, _ = interpreter.process_main_template("main_template.txt")
        # Plain include stays static; @-marked include goes to the volatile channel.
        self.assertEqual(blocks, ["You are a character."])
        self.assertEqual(
            interpreter.get_context_infos(),
            ["[Behavior State]\nAttitude: 62/100 — warm"],
        )

    def test_context_infos_reset_between_builds(self) -> None:
        files = {
            "main_template.txt": "[<band.script>]\n",
            "band.script": 'ADD_CONTEXT_INFO "line"\n',
        }
        interpreter = DslInterpreter(_StubCharacter(), resolver=_MultiFileResolver(files))
        interpreter.process_main_template("main_template.txt")
        interpreter.process_main_template("main_template.txt")
        # Must not accumulate across builds.
        self.assertEqual(interpreter.get_context_infos(), ["line"])

    def test_legacy_dsl_uses_safe_evaluator_and_preserves_fallbacks(self) -> None:
        interp = DslInterpreter(_StubCharacter(), resolver=None)
        result = interp._eval_expr(
            'f"{count}-{suffix}"',
            "test.script",
            1,
            'RETURN f"{count}-{suffix}"',
        )
        self.assertEqual(result, "3-ok")
        self.assertEqual(
            interp._eval_expr(
                '"count=" + count',
                "test.script",
                2,
                'RETURN "count=" + count',
            ),
            "count=3",
        )

        self.assertTrue(
            interp._eval_expr(
                "missing_value is None",
                "test.script",
                3,
                "IF missing_value is None THEN",
            )
        )
        self.assertIsNone(interp._local_vars["missing_value"])

        with self.assertRaises(DslError):
            interp._eval_expr(
                'suffix.__class__',
                "test.script",
                4,
                "RETURN suffix.__class__",
            )

    def test_custom_param_formula_is_safe_and_keeps_expected_math(self) -> None:
        result = _evaluate_custom_param_formula(
            "max(0, current + value * scale)",
            variables={"scale": 2},
            current=10,
            value=-3,
            change_command="attitude_change",
            variable_name="attitude",
        )
        self.assertEqual(result, 4)

        with self.assertRaises(ValueError):
            _evaluate_custom_param_formula(
                '().__class__.__base__.__subclasses__()',
                variables={},
                current=0,
                value=1,
                change_command="change",
                variable_name="score",
            )

    def test_runtime_p0_paths_do_not_call_builtin_eval(self) -> None:
        runtime_files = (
            PROJECT_SRC / "DSL" / "dsl_engine.py",
            PROJECT_SRC / "characters" / "character.py",
        )
        violations: list[str] = []
        for path in runtime_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "eval"
                ):
                    violations.append(f"{path.relative_to(PROJECT_SRC)}:{node.lineno}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
