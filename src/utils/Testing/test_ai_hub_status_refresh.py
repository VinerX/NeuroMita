"""Обновление статусов карточек AI Hub после установки.

Регресс: свежеустановленный компонент оставался «Не установлен», потому что
проверка не укладывалась в бюджет каталога, а досчитанный статус до UI не доходил.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtCore import QCoreApplication

from controllers.gui.ai_hub_view_model import AIHubViewModel
from controllers.gui.presentation_contracts import UiTopic
from ui.mvvm import mutable_payload


@pytest.fixture(scope="module")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class _FakeEvents:
    def __init__(self) -> None:
        self.subscribers: dict[str, list] = {}

    def subscribe(self, topic, callback, *, weak: bool = False):
        self.subscribers.setdefault(str(topic), []).append(callback)
        return SimpleNamespace(close=lambda: None)

    def publish(self, topic, data) -> None:
        for callback in self.subscribers.get(str(topic), []):
            callback(SimpleNamespace(topic=topic, data=data))


class _FakeCatalog:
    def __init__(self) -> None:
        self.invalidated: list[str | None] = []
        self.list_calls: list[dict] = []

    def invalidate(self, component_id=None) -> None:
        self.invalidated.append(component_id)

    def list_rows(self, **kwargs):
        self.list_calls.append(dict(kwargs))
        return []

    def hardware_snapshot(self):
        return {}


def _row(component_id: str, status: dict | None) -> dict:
    row = {
        "metadata": {"id": component_id, "category": "rag", "title": component_id},
        "compatibility": {"supported": True},
    }
    if status is not None:
        row["status"] = status
    return row


def _transient_status(component_id: str) -> dict:
    return {
        "id": component_id,
        "code": "unknown",
        "installed": False,
        "ready": False,
        "probe_state": "timeout",
        "details": {"probe_state": "timeout", "transient": True},
    }


def _ready_status(component_id: str) -> dict:
    return {
        "id": component_id,
        "code": "ready",
        "installed": True,
        "ready": True,
        "details": {},
    }


def _make_vm(qt_app):
    events = _FakeEvents()
    catalog = _FakeCatalog()
    presentation = SimpleNamespace(
        events=events,
        installables=catalog,
        app=SimpleNamespace(backend_ready=False),
    )
    vm = AIHubViewModel(presentation)
    return vm, events, catalog


def _rows_of(vm) -> list[dict]:
    return [dict(mutable_payload(item) or {}) for item in vm.state.rows]


def test_unfinished_probe_keeps_card_in_checking_state(qt_app):
    vm, _events, _catalog = _make_vm(qt_app)
    component_id = "rag:embeddings:qwen-qwen3-embedding-0-6b"

    vm._apply_refresh(
        {
            "rows": [
                _row(component_id, _transient_status(component_id)),
                _row("rag:reranker:other", _ready_status("rag:reranker:other")),
            ],
            "hardware": {},
            "checked_at": None,
            "included_status": True,
        }
    )

    assert vm.state.checking_component_ids == frozenset({component_id})
    vm.close()


def test_deferred_status_updates_only_its_own_card(qt_app):
    vm, events, _catalog = _make_vm(qt_app)
    component_id = "rag:embeddings:qwen-qwen3-embedding-0-6b"
    other_id = "rag:reranker:other"

    vm._apply_refresh(
        {
            "rows": [
                _row(component_id, _transient_status(component_id)),
                _row(other_id, _transient_status(other_id)),
            ],
            "hardware": {},
            "checked_at": None,
            "included_status": True,
        }
    )
    revision_before = vm.state.revision

    events.publish(
        UiTopic.INSTALL_COMPONENT_STATUS,
        {
            "component_id": component_id,
            "status": _ready_status(component_id),
            "compatibility": {"supported": True, "recommended": True},
        },
    )
    qt_app.processEvents()

    rows = {row["metadata"]["id"]: row for row in _rows_of(vm)}
    assert rows[component_id]["status"]["ready"] is True
    assert rows[component_id]["compatibility"]["recommended"] is True
    assert rows[other_id]["status"]["code"] == "unknown"
    assert vm.state.checking_component_ids == frozenset({other_id})
    assert vm.state.revision > revision_before
    vm.close()


def test_unknown_component_status_does_not_touch_rows(qt_app):
    vm, events, _catalog = _make_vm(qt_app)
    component_id = "rag:embeddings:qwen-qwen3-embedding-0-6b"

    vm._apply_refresh(
        {
            "rows": [_row(component_id, _transient_status(component_id))],
            "hardware": {},
            "checked_at": None,
            "included_status": True,
        }
    )
    revision_before = vm.state.revision

    events.publish(
        UiTopic.INSTALL_COMPONENT_STATUS,
        {"component_id": "tts:not-in-catalog", "status": _ready_status("tts:x")},
    )
    qt_app.processEvents()

    assert vm.state.revision == revision_before
    assert vm.state.checking_component_ids == frozenset({component_id})
    vm.close()


def test_install_finished_rechecks_finished_component_without_full_reprobe(qt_app):
    vm, events, catalog = _make_vm(qt_app)
    component_id = "rag:embeddings:qwen-qwen3-embedding-0-6b"
    refresh_calls: list[dict] = []
    vm.refresh = lambda **kwargs: refresh_calls.append(dict(kwargs))

    events.publish(
        UiTopic.INSTALL_TASK_FINISHED,
        {
            "component_id": component_id,
            "meta": {"component_id": component_id, "category": "rag"},
            "ok": True,
        },
    )
    qt_app.processEvents()

    assert catalog.invalidated == [component_id]
    assert refresh_calls == [{"force": False, "include_status": True}]
    vm.close()


def test_stalled_probe_stops_blocking_the_card(qt_app):
    vm, _events, _catalog = _make_vm(qt_app)
    component_id = "rag:embeddings:qwen-qwen3-embedding-0-6b"

    vm._apply_refresh(
        {
            "rows": [_row(component_id, _transient_status(component_id))],
            "hardware": {},
            "checked_at": None,
            "included_status": True,
        }
    )
    assert vm.state.checking_component_ids

    vm._on_pending_check_timeout(vm._checking_generation)

    assert vm.state.checking_component_ids == frozenset()
    vm.close()
