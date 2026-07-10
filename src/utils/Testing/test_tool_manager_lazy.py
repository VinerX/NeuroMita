from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.tools.tool_manager import ToolManager


class ToolManagerLazyTests(unittest.TestCase):
    def test_builtin_tools_are_not_imported_during_manager_construction(self):
        calls: list[str] = []
        real_import_module = importlib.import_module

        def tracked_import(name: str, package=None):
            calls.append(name)
            return real_import_module(name, package)

        with patch(
            "managers.tools.tool_manager.import_module",
            side_effect=tracked_import,
        ):
            manager = ToolManager()
            self.assertFalse(
                any(name.startswith("managers.tools.builtin.") for name in calls)
            )

            result = manager.run("calculator", {"expression": "2 + 2"})

        self.assertEqual(result, "4")
        self.assertIn("managers.tools.builtin.calc", calls)
        self.assertNotIn("managers.tools.builtin.web_read", calls)
        self.assertNotIn("managers.tools.builtin.web_search", calls)


if __name__ == "__main__":
    unittest.main()
