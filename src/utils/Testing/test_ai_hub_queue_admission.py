from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from controllers.gui.ai_hub_view_model import AIHubViewModel


class _Stub:
    """Лёгкая граница view model: проверяем только логику допуска в очередь
    (`request_component_action`), без бэкенда и потоков."""

    _VALID_ACTIONS = AIHubViewModel._VALID_ACTIONS
    _task_id_for = staticmethod(AIHubViewModel._task_id_for)
    _is_task_active = AIHubViewModel._is_task_active
    request_component_action = AIHubViewModel.request_component_action

    def __init__(self, *, running_task_id: str | None) -> None:
        running = {"task_id": running_task_id} if running_task_id else None
        self.state = SimpleNamespace(queue_state={"running": running, "pending": []})
        self._inflight: set[str] = set()
        self.updates: list[dict] = []
        self.exclusive_calls: list[str] = []

    def update_state(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def run_exclusive(self, name, worker, applied, failed) -> None:
        # До сюда доходит только незаблокированный запрос — воркер не запускаем.
        self.exclusive_calls.append(name)


def test_second_component_enqueues_while_queue_busy() -> None:
    vm = _Stub(running_task_id="tts:voice:install")

    vm.request_component_action("rag:model", "install")

    # Другой компонент во время занятой очереди должен дойти до run_exclusive
    # (т.е. быть принятым в очередь), а не отвергнуться.
    assert vm.exclusive_calls == ["ai-hub-action:rag:model:install"]
    assert all(
        "Дождитесь" not in (u.get("task_status") or "")
        and "Wait for the current" not in (u.get("task_status") or "")
        for u in vm.updates
    )


def test_same_component_is_not_requeued() -> None:
    vm = _Stub(running_task_id="rag:model:install")

    vm.request_component_action("rag:model", "install")

    # Тот же компонент уже в работе — второй запрос не должен создавать операцию.
    assert vm.exclusive_calls == []
    assert any(
        (u.get("task_status") or "") in ("Уже в очереди", "Already queued")
        for u in vm.updates
    )


def test_rapid_double_click_same_component_deduped() -> None:
    vm = _Stub(running_task_id=None)
    vm._inflight.add("ai-hub-action:rag:model:install")

    vm.request_component_action("rag:model", "install")

    # Повторный клик до попадания в очередь ловится `_inflight`.
    assert vm.exclusive_calls == []
    assert any(
        "подготавливается" in (u.get("task_status") or "")
        or "already preparing" in (u.get("task_status") or "").lower()
        for u in vm.updates
    )
