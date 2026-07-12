from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ui.windows.ai_hub.dialog import AIHubDialog


class _Button:
    def __init__(self) -> None:
        self.enabled: bool | None = None

    def setEnabled(self, value: bool) -> None:
        self.enabled = value


class _TimedOutRefreshDialog:
    """Minimal UI boundary for exercising the timeout recovery path."""

    def __init__(self) -> None:
        self._refresh_timeout_generation = 3
        self._refresh_generation = 3
        self._refresh_inflight = True
        self._refresh_worker_active = True
        self._refresh_timeout_reported = False
        self._checking_component_ids = {"tts:edge"}
        self.btn_refresh = _Button()
        self.busy_state_applied = False
        self.status = ""

    def _apply_busy_state(self) -> None:
        self.busy_state_applied = True

    def _set_task_status(self, text: str) -> None:
        self.status = text


def test_status_refresh_timeout_releases_cards_and_ignores_late_worker_result():
    dialog = _TimedOutRefreshDialog()

    AIHubDialog._on_refresh_timeout(dialog)

    assert dialog._refresh_inflight is False
    # The UI is released, but the still-running worker remains accounted for;
    # a subsequent refresh must not create another orphaned probe.
    assert dialog._refresh_worker_active is True
    assert dialog._refresh_timeout_reported is True
    assert dialog._checking_component_ids == set()
    assert dialog.btn_refresh.enabled is True
    assert dialog.busy_state_applied is True
    assert "Новая проверка будет доступна" in dialog.status
    # The generation bump makes the late background result stale.
    assert dialog._refresh_generation == 4


def test_refresh_does_not_start_another_worker_while_timed_out_worker_is_alive():
    dialog = _TimedOutRefreshDialog()

    with patch("ui.windows.ai_hub.dialog.task_supervisor") as supervisor:
        AIHubDialog.refresh(dialog)

    supervisor.assert_not_called()
    assert "Предыдущая проверка ещё выполняется" in dialog.status
