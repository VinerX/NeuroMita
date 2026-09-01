from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from characters.character import Character


class _StatStub(Character):
    """Bypass Character's heavy __init__; exercise only the stat math."""

    def __init__(self, variables: dict) -> None:  # noqa: D401 - intentional bypass
        self.char_id = "T"
        self._vars = dict(variables)

    def get_variable(self, name, default=None):
        return self._vars.get(name, default)

    def set_variable(self, name, value):
        self._vars[name] = value


class CharacterStatTests(unittest.TestCase):
    def test_zero_change_leaves_value_untouched(self):
        stub = _StatStub({"attitude": 60.0})
        stub.adjust_attitude(0)
        self.assertEqual(stub.get_variable("attitude"), 60.0)

    def test_normal_change_applied(self):
        stub = _StatStub({"attitude": 60.0})
        stub.adjust_attitude(1.5)
        self.assertEqual(stub.get_variable("attitude"), 61.5)

    def test_default_hard_limit_is_six(self):
        stub = _StatStub({"attitude": 60.0})
        stub.adjust_attitude(50)  # far beyond scale
        self.assertEqual(stub.get_variable("attitude"), 66.0)  # +6 cap

    def test_hard_limit_is_configurable(self):
        stub = _StatStub({"attitude": 60.0, "STAT_CHANGE_HARD_LIMIT": 2.0})
        stub.adjust_attitude(50)
        self.assertEqual(stub.get_variable("attitude"), 62.0)  # +2 cap

    def test_total_stays_within_bounds(self):
        stub = _StatStub({"attitude": 99.0, "attitude_min": 0.0, "attitude_max": 100.0})
        stub.adjust_attitude(5)
        self.assertEqual(stub.get_variable("attitude"), 100.0)

        stub2 = _StatStub({"stress": 1.0, "stress_min": 0.0, "stress_max": 100.0})
        stub2.adjust_stress(-5)
        self.assertEqual(stub2.get_variable("stress"), 0.0)


if __name__ == "__main__":
    unittest.main()
