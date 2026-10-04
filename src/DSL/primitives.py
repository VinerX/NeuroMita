import random as _random

from core.safe_eval import SafeEvalError


def random(*bounds):
    """Return a float in [0, 1) or an integer in the inclusive given range."""
    if not bounds:
        return _random.random()
    if len(bounds) != 2:
        raise SafeEvalError(
            "random expects no arguments or two integer bounds: random(min, max)."
        )
    lower, upper = bounds
    if any(not isinstance(value, int) or isinstance(value, bool) for value in bounds):
        raise SafeEvalError(
            "random(min, max) requires integer bounds; booleans are not accepted."
        )
    if lower > upper:
        raise SafeEvalError("random(min, max) requires min <= max.")
    return _random.randint(lower, upper)
