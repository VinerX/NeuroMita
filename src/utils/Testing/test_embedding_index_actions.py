from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from PyQt6.QtWidgets import QApplication, QWidget
from ui.settings.embedding_index_actions import EmbeddingIndexActionsWidget


class _Dialog:
    def __init__(self) -> None:
        self.shown = False
        self.raised = False
        self.activated = False

    def status_text(self) -> str:
        return "[1/2] Character"

    def detail_text(self) -> str:
        return "Processed: 12 / 50"

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        self.raised = True

    def activateWindow(self) -> None:
        self.activated = True


class EmbeddingIndexActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_running_index_has_visible_status_and_reopen_button(self) -> None:
        parent = QWidget()
        dialog = _Dialog()

        widget = EmbeddingIndexActionsWidget(
            parent,
            lambda: None,
            lambda: None,
            lambda: dialog,
        )
        widget._refresh_task_state()
        widget._show_progress()

        self.assertFalse(widget._active_widget.isHidden())
        self.assertIn("12 / 50", widget._active_label.text())
        self.assertTrue(dialog.shown)
        self.assertTrue(dialog.raised)
        self.assertTrue(dialog.activated)
        widget.deleteLater()
        parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
