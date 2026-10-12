from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import patch
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from ui.mvvm import immutable_payload
from ui.windows.ai_hub.dialog import AIHubDialog
from ui.windows.ai_hub.presentation import AIHubState
from ui.windows.ai_hub.settings_presentation import AIHubSettingsState, ApplyAIHubSettingsRows


class ViewModel(QObject):
    state_changed = pyqtSignal(object)
    effect_emitted = pyqtSignal(object)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.intents = []

    def dispatch(self, intent):
        self.intents.append(intent)

    def close(self):
        pass


@pytest.fixture
def dialog():
    app = QApplication.instance() or QApplication([])
    state = AIHubState(
        loaded_once=True,
        revision=1,
        queue_state=immutable_payload({
            "running": {"task_id": "dependency:opencv:install", "title": "OpenCV"},
            "pending": [{"task_id": "dependency:ffmpeg:install", "title": "FFmpeg"}],
        }),
        install_bar_visible=True,
    )
    model = ViewModel(state)
    settings_model = ViewModel(AIHubSettingsState())
    with patch("ui.windows.ai_hub.dialog.get_ai_hub_stylesheet", return_value=""):
        widget = AIHubDialog(model, settings_model, None)
    app.processEvents()
    yield widget, settings_model, state
    widget._allow_close_without_unsaved_prompt = True
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_progress_updates_preserve_queue_widgets(dialog):
    widget, _, state = dialog
    widget.render(replace(state, install_progress=10))
    original = [widget._queue_layout.itemAt(i).widget() for i in range(widget._queue_layout.count())]
    assert len(original) == 3

    widget.render(replace(state, install_progress=20, install_detail="Downloading OpenCV"))

    assert [widget._queue_layout.itemAt(i).widget() for i in range(widget._queue_layout.count())] == original
    assert widget._install_bar_progress.value() == 20


def test_progress_updates_do_not_resubmit_catalog_to_settings(dialog):
    widget, settings_model, state = dialog
    settings_model.intents.clear()

    widget.render(replace(state, install_progress=20))

    assert not any(isinstance(intent, ApplyAIHubSettingsRows) for intent in settings_model.intents)


@pytest.mark.parametrize("running,pending", [(True, False), (False, True), (True, True)])
def test_progress_updates_keep_refresh_disabled_while_queue_busy(dialog, running, pending):
    widget, _, state = dialog
    queue = {
        "running": {"task_id": "dependency:opencv:install", "title": "OpenCV"} if running else None,
        "pending": [{"task_id": "dependency:ffmpeg:install", "title": "FFmpeg"}] if pending else [],
    }
    state = replace(state, queue_state=immutable_payload(queue))
    widget.render(state)
    assert not widget.btn_refresh.isEnabled()

    widget.render(replace(state, install_progress=20))

    assert not widget.btn_refresh.isEnabled()


def test_queue_change_still_updates_visible_jobs(dialog):
    widget, _, state = dialog
    widget.render(replace(state, queue_state=immutable_payload({"running": None, "pending": []})))
    assert widget._queue_layout.count() == 0
    assert widget.btn_refresh.isEnabled()


def test_catalog_revision_still_reaches_settings(dialog):
    widget, settings_model, state = dialog
    settings_model.intents.clear()
    widget.render(replace(state, revision=2))
    assert any(isinstance(intent, ApplyAIHubSettingsRows) for intent in settings_model.intents)
