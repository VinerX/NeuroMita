# src/managers/tools/builtin/calc.py
from typing import Any
from core.safe_eval import SafeEvalError, safe_eval_arithmetic
from managers.tools.base import Tool


class CalculatorTool(Tool):
    name = "calculator"
    description = "Выполняет простые арифметические выражения. Пример: 2+2*5"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Арифметическое выражение, допускающее + - * / и скобки"
            }
        },
        "required": ["expression"]
    }

    def run(self, expression: str, **_) -> Any:
        try:
            result = safe_eval_arithmetic(expression)
            return str(result)
        except SafeEvalError as e:
            return f"Ошибка калькулятора: {e}"
        except Exception as e:
            return f"Ошибка калькулятора: {e}"
