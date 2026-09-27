from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QMessageBox

from ui.windows.ai_hub.dialog import AIHubDialog


class _PanelStub:
    def __init__(self, dirty: bool = True) -> None:
        self._dirty = dirty
        self.discard_calls = 0

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def discard_unsaved_changes(self) -> None:
        self.discard_calls += 1
        self._dirty = False


def test_confirm_close_with_unsaved_settings_discards_on_user_confirmation(monkeypatch) -> None:
    owner = type("Owner", (), {})()
    owner._settings_panel = _PanelStub(dirty=True)

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a, **_kw: QMessageBox.StandardButton.Discard,
    )

    assert AIHubDialog._confirm_close_with_unsaved_settings(owner) is True
    assert owner._settings_panel.discard_calls == 1


def test_confirm_close_with_unsaved_settings_cancels_without_discard(monkeypatch) -> None:
    owner = type("Owner", (), {})()
    owner._settings_panel = _PanelStub(dirty=True)

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a, **_kw: QMessageBox.StandardButton.Cancel,
    )

    assert AIHubDialog._confirm_close_with_unsaved_settings(owner) is False
    assert owner._settings_panel.discard_calls == 0
