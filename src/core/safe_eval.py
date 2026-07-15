from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class SafeEvalError(ValueError):
    """Raised when an expression uses disallowed syntax or names."""


class UnknownNameError(SafeEvalError):
    """Raised when an expression references a name absent from its scope."""

    def __init__(self, name: str) -> None:
        self.name = str(name)
        super().__init__(f"Unknown name: {self.name}")


_GENERAL_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}

_GENERAL_UNARYOPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
    ast.Not: lambda a: not a,
}

_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}

_ARITHMETIC_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: _GENERAL_BINOPS[ast.Add],
    ast.Sub: _GENERAL_BINOPS[ast.Sub],
    ast.Mult: _GENERAL_BINOPS[ast.Mult],
    ast.Div: _GENERAL_BINOPS[ast.Div],
    ast.FloorDiv: _GENERAL_BINOPS[ast.FloorDiv],
    ast.Mod: _GENERAL_BINOPS[ast.Mod],
    ast.Pow: _GENERAL_BINOPS[ast.Pow],
}

_ARITHMETIC_UNARYOPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: _GENERAL_UNARYOPS[ast.UAdd],
    ast.USub: _GENERAL_UNARYOPS[ast.USub],
}


@dataclass(frozen=True)
class _EvalPolicy:
    binops: Mapping[type[ast.operator], Callable[[Any, Any], Any]]
    unaryops: Mapping[type[ast.unaryop], Callable[[Any], Any]]
    allow_bool_ops: bool
    allow_compare: bool
    allow_ifexp: bool
    allow_calls: bool
    allow_names: bool
    allow_collections: bool


_GENERAL_POLICY = _EvalPolicy(
    binops=_GENERAL_BINOPS,
    unaryops=_GENERAL_UNARYOPS,
    allow_bool_ops=True,
    allow_compare=True,
    allow_ifexp=True,
    allow_calls=True,
    allow_names=True,
    allow_collections=True,
)

_ARITHMETIC_POLICY = _EvalPolicy(
    binops=_ARITHMETIC_BINOPS,
    unaryops=_ARITHMETIC_UNARYOPS,
    allow_bool_ops=False,
    allow_compare=False,
    allow_ifexp=False,
    allow_calls=False,
    allow_names=False,
    allow_collections=False,
)


class _SafeExpressionEvaluator:
    def __init__(
        self,
        *,
        names: Mapping[str, Any],
        allowed_calls: Mapping[str, Callable[..., Any]],
        policy: _EvalPolicy,
    ) -> None:
        self._names = dict(names or {})
        self._allowed_calls = dict(allowed_calls or {})
        self._policy = policy

    def eval(self, expr: str) -> Any:
        try:
            tree = ast.parse(str(expr or "").strip(), mode="eval")
        except SyntaxError as exc:
            raise SafeEvalError(f"Invalid expression syntax: {exc.msg}") from exc
        return self._visit(tree.body)

    def _visit(self, node: ast.AST) -> Any:
        method = getattr(self, f"_visit_{type(node).__name__}", None)
        if method is None:
            raise SafeEvalError(f"Disallowed expression node: {type(node).__name__}")
        return method(node)

    def _visit_Constant(self, node: ast.Constant) -> Any:
        if not self._policy.allow_collections and not isinstance(node.value, (int, float)):
            raise SafeEvalError("Only numeric literals are allowed in arithmetic expressions.")
        return node.value

    def _visit_Name(self, node: ast.Name) -> Any:
        if node.id.startswith("__"):
            raise SafeEvalError("Dunder names are not allowed.")
        if not self._policy.allow_names:
            raise SafeEvalError(f"Names are not allowed in this expression: {node.id}")
        if node.id in self._names:
            return self._names[node.id]
        if node.id in self._allowed_calls:
            return self._allowed_calls[node.id]
        raise UnknownNameError(node.id)

    def _visit_List(self, node: ast.List) -> Any:
        if not self._policy.allow_collections:
            raise SafeEvalError("Collection literals are not allowed in this expression.")
        return [self._visit(item) for item in node.elts]

    def _visit_Tuple(self, node: ast.Tuple) -> Any:
        if not self._policy.allow_collections:
            raise SafeEvalError("Collection literals are not allowed in this expression.")
        return tuple(self._visit(item) for item in node.elts)

    def _visit_Set(self, node: ast.Set) -> Any:
        if not self._policy.allow_collections:
            raise SafeEvalError("Collection literals are not allowed in this expression.")
        return {self._visit(item) for item in node.elts}

    def _visit_Dict(self, node: ast.Dict) -> Any:
        if not self._policy.allow_collections:
            raise SafeEvalError("Collection literals are not allowed in this expression.")
        return {
            self._visit(key): self._visit(value)
            for key, value in zip(node.keys, node.values)
        }

    def _visit_JoinedStr(self, node: ast.JoinedStr) -> str:
        if not self._policy.allow_collections:
            raise SafeEvalError("Formatted strings are not allowed in this expression.")
        return "".join(str(self._visit(value)) for value in node.values)

    def _visit_FormattedValue(self, node: ast.FormattedValue) -> str:
        if not self._policy.allow_collections:
            raise SafeEvalError("Formatted strings are not allowed in this expression.")

        value = self._visit(node.value)
        if node.conversion == ord("s"):
            value = str(value)
        elif node.conversion == ord("r"):
            value = repr(value)
        elif node.conversion == ord("a"):
            value = ascii(value)
        elif node.conversion != -1:
            raise SafeEvalError("Unsupported formatted-string conversion.")

        if node.format_spec is None:
            return str(value)

        format_spec = self._visit(node.format_spec)
        if not isinstance(format_spec, str):
            raise SafeEvalError("Formatted-string format spec must evaluate to text.")
        try:
            return format(value, format_spec)
        except (TypeError, ValueError) as exc:
            raise SafeEvalError(f"Invalid formatted-string format spec: {exc}") from exc

    def _visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if not self._policy.allow_bool_ops:
            raise SafeEvalError("Boolean operators are not allowed in this expression.")
        if isinstance(node.op, ast.And):
            result = True
            for value_node in node.values:
                result = self._visit(value_node)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value_node in node.values:
                result = self._visit(value_node)
                if result:
                    return result
            return result
        raise SafeEvalError(f"Disallowed boolean operator: {type(node.op).__name__}")

    def _visit_BinOp(self, node: ast.BinOp) -> Any:
        op = self._policy.binops.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"Disallowed arithmetic operator: {type(node.op).__name__}")
        return op(self._visit(node.left), self._visit(node.right))

    def _visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op = self._policy.unaryops.get(type(node.op))
        if op is None:
            raise SafeEvalError(f"Disallowed unary operator: {type(node.op).__name__}")
        return op(self._visit(node.operand))

    def _visit_Compare(self, node: ast.Compare) -> Any:
        if not self._policy.allow_compare:
            raise SafeEvalError("Comparisons are not allowed in this expression.")
        left = self._visit(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _COMPARE_OPS.get(type(op_node))
            if op is None:
                raise SafeEvalError(f"Disallowed comparison operator: {type(op_node).__name__}")
            right = self._visit(comparator)
            if not op(left, right):
                return False
            left = right
        return True

    def _visit_IfExp(self, node: ast.IfExp) -> Any:
        if not self._policy.allow_ifexp:
            raise SafeEvalError("Conditional expressions are not allowed in this expression.")
        return self._visit(node.body) if self._visit(node.test) else self._visit(node.orelse)

    def _visit_Call(self, node: ast.Call) -> Any:
        if not self._policy.allow_calls:
            raise SafeEvalError("Function calls are not allowed in this expression.")
        if not isinstance(node.func, ast.Name):
            raise SafeEvalError("Only direct allowlisted function calls are allowed.")
        if node.func.id.startswith("__"):
            raise SafeEvalError("Dunder call targets are not allowed.")
        func = self._allowed_calls.get(node.func.id)
        if func is None:
            raise SafeEvalError(f"Call target is not allowed: {node.func.id}")
        args = [self._visit(arg) for arg in node.args]
        kwargs = {}
        for kw in node.keywords:
            if kw.arg is None:
                raise SafeEvalError("Star-arguments are not allowed.")
            if kw.arg.startswith("__"):
                raise SafeEvalError("Dunder keyword arguments are not allowed.")
            kwargs[kw.arg] = self._visit(kw.value)
        return func(*args, **kwargs)

    def _visit_Attribute(self, node: ast.Attribute) -> Any:
        raise SafeEvalError("Attribute access is not allowed.")

    def _visit_Subscript(self, node: ast.Subscript) -> Any:
        raise SafeEvalError("Subscripting is not allowed.")

    def _visit_Lambda(self, node: ast.Lambda) -> Any:
        raise SafeEvalError("Lambda expressions are not allowed.")

    def _visit_ListComp(self, node: ast.ListComp) -> Any:
        raise SafeEvalError("Comprehensions are not allowed.")

    def _visit_SetComp(self, node: ast.SetComp) -> Any:
        raise SafeEvalError("Comprehensions are not allowed.")

    def _visit_DictComp(self, node: ast.DictComp) -> Any:
        raise SafeEvalError("Comprehensions are not allowed.")

    def _visit_GeneratorExp(self, node: ast.GeneratorExp) -> Any:
        raise SafeEvalError("Comprehensions are not allowed.")


def safe_eval_expression(
    expr: str,
    *,
    names: Mapping[str, Any] | None = None,
    allowed_calls: Mapping[str, Callable[..., Any]] | None = None,
) -> Any:
    evaluator = _SafeExpressionEvaluator(
        names=names or {},
        allowed_calls=allowed_calls or {},
        policy=_GENERAL_POLICY,
    )
    return evaluator.eval(expr)


def safe_eval_arithmetic(expr: str) -> Any:
    evaluator = _SafeExpressionEvaluator(
        names={},
        allowed_calls={},
        policy=_ARITHMETIC_POLICY,
    )
    return evaluator.eval(expr)
