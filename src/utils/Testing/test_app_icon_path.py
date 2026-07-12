"""Проверка независимого от cwd разрешения иконки приложения."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ui.app_icon import app_icon_path


class AppIconPathTests(unittest.TestCase):
    def test_icon_path_does_not_depend_on_cwd_when_base_is_unconfigured(self):
        original_cwd = Path.cwd()
        with patch.dict(
            os.environ, {"NEUROMITA_BASE_DIR": ""}, clear=False
        ):
            os.chdir(PROJECT_SRC / "utils")
            try:
                self.assertEqual(
                    Path(app_icon_path()).resolve(),
                    (PROJECT_SRC.parent / "Icon.png").resolve(),
                )
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
