from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from DSL import primitives
from DSL.dsl_engine import DslError, DslInterpreter
from DSL.post_dsl_engine import PostDslError, PostDslInterpreter
from core.safe_eval import SafeEvalError


@pytest.fixture(params=["dsl", "post"])
def evaluate(request):
    character = SimpleNamespace(
        char_id="Test", variables={"low": -3, "high": 7}, app_vars={}
    )
    if request.param == "dsl":
        interpreter = DslInterpreter(character, None)
        return (
            lambda expr: interpreter._eval_expr(
                expr, "random.script", 12, f"RETURN {expr}"
            ),
            DslError,
        )
    interpreter = PostDslInterpreter.__new__(PostDslInterpreter)
    interpreter.character = character
    interpreter._local_vars = {}
    return lambda expr: interpreter._eval_dsl_expression(expr, {}), PostDslError


def test_fraction_and_inclusive_range_are_available_in_both_interpreters(
    evaluate, monkeypatch
):
    expression, _ = evaluate
    monkeypatch.setattr(primitives._random, "random", lambda: 0.125)
    randint = Mock(side_effect=[-3, 7])
    monkeypatch.setattr(primitives._random, "randint", randint)
    assert expression("random() < 0.25") is True
    assert expression("random(low, high)") == -3
    assert expression('f"variant={random(low, high)}"') == "variant=7"
    assert randint.call_args_list[0].args == (-3, 7)
    assert randint.call_args_list[1].args == (-3, 7)


@pytest.mark.parametrize(
    "expr",
    [
        "random(1)",
        "random(1, 2, 3)",
        "random(2, 1)",
        "random(1.5, 3)",
        "random(True, 3)",
        "random('1', 3)",
        "random.__class__",
        "random.seed(1)",
    ],
)
def test_invalid_calls_and_module_access_stay_blocked(evaluate, expr):
    expression, expected_error = evaluate
    with pytest.raises(expected_error):
        expression(expr)


def test_invalid_bounds_explain_the_problem(evaluate):
    expression, expected_error = evaluate
    with pytest.raises(expected_error) as caught:
        expression("random(5, 1)")
    assert isinstance(caught.value.__cause__, SafeEvalError)
    assert "min <= max" in str(caught.value.__cause__)
    assert "min <= max" in str(caught.value)


def test_random_values_respect_real_ranges():
    assert all(0 <= primitives.random() < 1 for _ in range(100))
    assert all(-2 <= primitives.random(-2, 2) <= 2 for _ in range(100))
    assert primitives.random(4, 4) == 4


def test_script_can_store_a_roll_and_skipped_branches_do_not_draw(monkeypatch):
    rng = Mock(return_value=2)
    monkeypatch.setattr(primitives._random, "randint", rng)
    script = "\n".join(
        [
            "SET LOCAL roll = random(1, 3)",
            "IF roll == 2 THEN",
            'RETURN "selected=" + str(roll)',
            "ELSE",
            "RETURN str(random(10, 20))",
            "ENDIF",
        ]
    )
    resolver = SimpleNamespace(
        resolve_path=lambda path: path,
        get_dirname=lambda path: "",
        load_text=lambda path, context: script,
    )
    character = SimpleNamespace(char_id="Test", variables={}, app_vars={})
    result, _ = DslInterpreter(character, resolver).process_script("random.script")
    assert result == "selected=2"
    assert character.variables == {}
    rng.assert_called_once_with(1, 3)
