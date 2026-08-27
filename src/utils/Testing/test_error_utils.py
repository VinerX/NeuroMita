from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.error_utils import format_exception


class ErrorUtilsTests(unittest.TestCase):
    def test_empty_exception_still_has_its_type(self):
        self.assertEqual(format_exception(TimeoutError()), "TimeoutError")

    def test_exception_message_includes_type_and_details(self):
        self.assertEqual(
            format_exception(ValueError("invalid value")),
            "ValueError: invalid value",
        )

    def test_non_exception_values_also_have_a_non_empty_fallback(self):
        self.assertEqual(format_exception("worker unavailable"), "worker unavailable")
        self.assertEqual(format_exception(None), "UnknownError")
        self.assertEqual(format_exception(""), "UnknownError")

    def test_active_code_does_not_render_caught_exceptions_directly(self):
        violations: list[str] = []
        for path in PROJECT_SRC.rglob("*.py"):
            lowered_parts = [part.lower() for part in path.parts]
            if (
                path.name == "error_utils.py"
                or "testing" in lowered_parts
                or any("legacy" in part or "obsolete" in part for part in lowered_parts)
            ):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except (OSError, SyntaxError, UnicodeError):
                continue

            canonical_names = {"exc", "error", "err", "ex", "exception"}
            for node in ast.walk(tree):
                raw_str = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "str"
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in canonical_names
                )
                raw_fstring = (
                    isinstance(node, ast.FormattedValue)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in canonical_names
                )
                if raw_str or raw_fstring:
                    violations.append(
                        f"{path.relative_to(PROJECT_SRC)}:{node.lineno}"
                    )

            for handler in (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ExceptHandler) and node.name
            ):
                scope = ast.Module(body=handler.body, type_ignores=[])
                for node in ast.walk(scope):
                    direct_str = (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "str"
                        and len(node.args) == 1
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == handler.name
                    )
                    direct_fstring = (
                        isinstance(node, ast.FormattedValue)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == handler.name
                    )
                    direct_format = (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "format"
                        and any(
                            isinstance(value, ast.Name) and value.id == handler.name
                            for value in (
                                *node.args,
                                *(keyword.value for keyword in node.keywords),
                            )
                        )
                    )
                    direct_log_argument = (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr
                        in {"debug", "info", "warning", "error", "critical", "exception"}
                        and any(
                            isinstance(argument, ast.Name)
                            and argument.id == handler.name
                            for argument in node.args[1:]
                        )
                    )
                    if (
                        direct_str
                        or direct_fstring
                        or direct_format
                        or direct_log_argument
                    ):
                        violations.append(
                            f"{path.relative_to(PROJECT_SRC)}:{node.lineno}"
                        )

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
