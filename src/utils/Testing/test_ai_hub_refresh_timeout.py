from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from controllers.gui.ai_hub_view_model import AIHubViewModel


class _TimedOutViewModel:
    """Минимальная граница view model для проверки восстановления после таймаута."""

    def __init__(self, *, refreshing: bool = True, generation: int = 3) -> None:
        self._refresh_timeout_generation = generation
        self.state = SimpleNamespace(refreshing=refreshing)
        self.updates: list[dict] = []

    def update_state(self, **kwargs) -> None:
        self.updates.append(kwargs)


def test_status_refresh_timeout_releases_ui():
    vm = _TimedOutViewModel()

    AIHubViewModel._on_refresh_timeout(vm, 3)

    assert len(vm.updates) == 1
    update = vm.updates[0]
    assert update["refreshing"] is False
    assert update["checking_component_ids"] == frozenset()
    assert "Новая проверка будет доступна" in update["task_status"]


def test_stale_generation_timeout_is_ignored():
    vm = _TimedOutViewModel(generation=4)

    AIHubViewModel._on_refresh_timeout(vm, 3)

    assert vm.updates == []


def test_timeout_after_finished_refresh_is_ignored():
    vm = _TimedOutViewModel(refreshing=False)

    AIHubViewModel._on_refresh_timeout(vm, 3)

    assert vm.updates == []
