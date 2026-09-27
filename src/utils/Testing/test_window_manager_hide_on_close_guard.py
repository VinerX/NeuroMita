from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog

from ui.window_manager import _HideOnCloseFilter


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class _GuardedDialog(QDialog):
    def __init__(self, allow: bool) -> None:
        super().__init__()
        self.allow = allow
        self.confirm_calls = 0

    def confirm_hide_on_close(self) -> bool:
        self.confirm_calls += 1
        return self.allow


def test_native_close_is_vetoed_before_hide_when_guard_rejects() -> None:
    app = _app()
    dialog = _GuardedDialog(False)
    filter_ = _HideOnCloseFilter(dialog)
    dialog.installEventFilter(filter_)
    dialog.show()
    app.processEvents()

    dialog.close()
    app.processEvents()

    assert dialog.confirm_calls == 1
    assert dialog.isVisible()


def test_native_close_hides_when_guard_accepts() -> None:
    app = _app()
    dialog = _GuardedDialog(True)
    filter_ = _HideOnCloseFilter(dialog)
    dialog.installEventFilter(filter_)
    dialog.show()
    app.processEvents()

    dialog.close()
    app.processEvents()

    assert dialog.confirm_calls == 1
    assert not dialog.isVisible()
