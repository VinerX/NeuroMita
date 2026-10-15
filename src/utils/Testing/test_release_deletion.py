from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QWidget

from controllers.chat_controller import ChatController
from controllers.gui.api_settings.editor_mixin import EditorMixin
from controllers.gui.settings_controller import SettingsController
from handlers.asr_models.google_recognizer import GoogleRecognizer
from managers.unity_retry_store import UnityRetryStore
from ui.chat.presentation_coordinator import ChatPresentationCoordinator, ChatRenderCommand
from ui.windows.app_window_base import AppWindowBase
from core.events import Events


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])



def test_delete_failed_unity_message_survives_restart_without_erasing_history(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROMITA_HISTORIES_DIR", str(tmp_path))
    path = tmp_path / "Crazy" / "unity_retry_outbox.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 1, "records": [
        {"message_id": mid, "character_id": "Crazy", "status": "needs_generation",
         "created_at": time.time(), "request": {"user_input": "hi"}}
        for mid in ["in:failed", "in:other"]
    ]}), encoding="utf-8")
    controller = ChatController.__new__(ChatController)
    history = Mock()
    history.delete_message.return_value = False
    controller._get_character_ref = lambda _cid: SimpleNamespace(history_manager=history)
    controller._ui_requests_by_message_id = {}
    controller.event_bus = Mock()
    controller._on_delete_message(SimpleNamespace(data={"character_id": "Crazy", "message_id": "in:failed"}))
    assert [r["message_id"] for r in UnityRetryStore.list_for_character("Crazy")] == ["in:other"]
    history.delete_message.assert_called_once_with("in:failed")
    controller.event_bus.emit.assert_called_once_with(Events.GUI.RELOAD_CHAT_HISTORY,
        {"deleted_message_id": "in:failed", "character_id": "Crazy"})



def test_deleted_live_bubble_is_not_replayed_but_other_character_is_preserved():
    coordinator = ChatPresentationCoordinator()
    for cid in ["Crazy", "Kind"]:
        coordinator.record_live(ChatRenderCommand(role="user", content="failed", character_id=cid, message_id="in:failed"))
    coordinator.forget_message(message_id="in:failed", character_id="Crazy")
    for cid, expected in [("Crazy", 0), ("Kind", 1)]:
        ticket = coordinator.begin_history_load(cid)
        plan = coordinator.plan_history_projection(request_id=ticket.request_id,
            response_character_id=cid, current_character_id=cid, history_messages=[])
        assert len(plan.replay) == expected



def test_delete_event_forgets_bubble_on_qt_thread_before_reload():
    view = SimpleNamespace(chat_message_deleted_signal=Mock(), load_chat_history_signal=Mock())
    controller = SettingsController.__new__(SettingsController)
    controller.view = view
    payload = {"deleted_message_id": "in:failed", "character_id": "Crazy"}
    controller._on_reload_chat_history(SimpleNamespace(data=payload))
    view.chat_message_deleted_signal.emit.assert_called_once_with(payload)
    view.load_chat_history_signal.emit.assert_not_called()



def test_delete_clears_presentation_then_requests_history():
    calls = []
    window = SimpleNamespace(_shell_actions=SimpleNamespace(current_character_id=lambda: "Crazy"),
        _chat_presentation=SimpleNamespace(forget_message=lambda **kw: calls.append(("forget", kw))),
        load_chat_history=lambda: calls.append(("reload", {})))
    AppWindowBase._on_chat_message_deleted(window, {"deleted_message_id": "in:failed", "character_id": "Crazy"})
    assert calls == [("forget", {"message_id": "in:failed", "character_id": "Crazy"}), ("reload", {})]



def test_deleted_failed_message_cannot_be_replayed_by_late_event_during_another_stream():
    coordinator = ChatPresentationCoordinator()
    old = ChatRenderCommand(role="user", content="failed", character_id="Crazy", message_id="in:failed")
    assert coordinator.record_live(old)
    coordinator.begin_stream("other-request", character_id="Crazy")
    coordinator.mark_stream_mounted("other-request")
    coordinator.record_stream_chunk("other-request", "ongoing answer", character_id="Crazy")
    coordinator.forget_message(message_id="in:failed", character_id="Crazy")
    assert coordinator.record_live(old) is False
    assert coordinator.should_render_stream("other-request", current_character_id="Crazy")
    ticket = coordinator.begin_history_load("Crazy")
    deferred = coordinator.plan_history_projection(request_id=ticket.request_id,
        response_character_id="Crazy", current_character_id="Crazy", history_messages=[])
    assert deferred.retry_after_stream
    assert coordinator.finish_stream("other-request", current_character_id="Crazy")
    ticket = coordinator.begin_history_load("Crazy")
    plan = coordinator.plan_history_projection(request_id=ticket.request_id,
        response_character_id="Crazy", current_character_id="Crazy", history_messages=[])
    assert plan.accepted
    assert plan.replay == ()
    assert coordinator.record_live(ChatRenderCommand(role="user", content="Kind row", character_id="Kind", message_id="in:failed"))



def test_deletion_removes_only_target_widgets_without_waiting_for_active_stream(app):
    from ui.chat.chat_widget import ChatWidget
    chat = ChatWidget()
    from ui.chat import message_renderer
    from ui.chat.message_widget import MessageWidget
    actions = SimpleNamespace(is_closed=False, dispatch=Mock())
    render_context = SimpleNamespace(chat_message_actions=actions)
    deleted = MessageWidget(role="user", content_text="failed", message_id="in:failed")
    other = MessageWidget(role="user", content_text="Kind message", message_id="in:failed")
    message_renderer._connect_widget_signals(render_context, deleted, "in:failed", "Crazy")
    message_renderer._connect_widget_signals(render_context, other, "in:failed", "Kind")
    stream = QWidget()
    for widget in (deleted, other, stream):
        chat.add_message_widget(widget)
    coordinator = ChatPresentationCoordinator()
    coordinator.begin_stream("other-request", character_id="Crazy")
    coordinator.mark_stream_mounted("other-request")
    loads = []
    window = SimpleNamespace(chat_window=chat, _chat_presentation=coordinator,
        _shell_actions=SimpleNamespace(current_character_id=lambda: "Crazy"), load_chat_history=lambda: loads.append(True))
    AppWindowBase._on_chat_message_deleted(window, {"deleted_message_id": "in:failed", "character_id": "Crazy"})
    assert chat._messages == [other, stream]
    assert coordinator.is_stream_mounted("other-request")
    assert loads == [True]
    chat.close()



def test_stale_history_row_is_not_rendered_after_deletion():
    coordinator = ChatPresentationCoordinator()
    coordinator.forget_message(message_id="in:failed", character_id="Crazy")
    window = SimpleNamespace(_chat_presentation=coordinator, _chat_render_context=Mock(),
        _get_setting=lambda _key, default: default)
    with patch("ui.windows.app_window_base.message_renderer.insert_message") as insert:
        AppWindowBase._render_history_entry(window,
            {"role": "user", "content": "stale failed row", "message_id": "in:failed"}, character_id="Crazy")
    insert.assert_not_called()



def test_prepended_history_row_is_not_rendered_after_deletion():
    coordinator = ChatPresentationCoordinator()
    coordinator.forget_message(message_id="in:failed", character_id="Crazy")
    window = SimpleNamespace(chat_window=SimpleNamespace(verticalScrollBar=lambda: Mock()), _chat_presentation=coordinator,
        _shell_actions=SimpleNamespace(current_character_id=lambda: "Crazy"), _chat_render_context=Mock())
    with patch("ui.windows.app_window_base.message_renderer.insert_message") as insert, \
         patch("ui.windows.app_window_base.QTimer.singleShot"):
        AppWindowBase._on_more_history_loaded(window, {"character_id": "Crazy", "messages": [
            {"role": "user", "content": "stale failed row", "message_id": "in:failed"}]})
    insert.assert_not_called()
