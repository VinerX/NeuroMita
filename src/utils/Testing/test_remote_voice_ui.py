import os
import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget, QVBoxLayout

from controllers.gui.remote_voice_settings_view_model import RemoteVoiceSettingsViewModel
from controllers.gui.voiceover_controller import VoiceoverGuiController
from controllers.gui.voiceover_settings_view_model import VoiceoverSettingsViewModel
from core.networking import HttpClientRegistry
from services.remote_voice_repository import RemoteVoiceRepository
from services.remote_voice_service import DefaultRemoteVoiceService
from ui.settings.voiceover_settings.remote_api import RemoteVoiceSettingsWidget
from ui.settings.voiceover_settings.ui import build_voiceover_settings_ui


def settle(app, vm):
    deadline = time.monotonic() + 5
    while vm.state.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert not vm.state.busy


@pytest.fixture
def panel(tmp_path):
    app = QApplication.instance() or QApplication([])
    service = DefaultRemoteVoiceService(repository=RemoteVoiceRepository(tmp_path / "profiles.json"),
        registry=HttpClientRegistry(), client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))))
    vm = RemoteVoiceSettingsViewModel(service)
    widget = RemoteVoiceSettingsWidget(vm)
    settle(app, vm)
    yield app, service, vm, widget
    vm.close()
    widget.close()
    service.close()


def test_key_is_masked_and_validation_keeps_draft(panel):
    app, service, vm, widget = panel
    widget.key.setText("private-key")
    assert widget.key.echoMode() == QLineEdit.EchoMode.Password
    assert not widget.eye.icon().isNull()
    widget.eye.trigger()
    assert widget.key.echoMode() == QLineEdit.EchoMode.Normal
    widget.eye.trigger()
    widget.voice.setText("invalid-voice")
    widget.save_button.click()
    settle(app, vm)
    assert vm.state.error
    assert widget.voice.text() == "invalid-voice"
    assert widget.key.text() == "private-key"
    assert service.configuration().active.api_key == ""


def test_profile_switch_saves_draft_without_network(panel):
    app, service, vm, widget = panel
    original_id = service.configuration().active_id
    widget.name.setText("Мой голос")
    widget.key.setText("private-key")
    widget.add_button.click()
    settle(app, vm)
    assert len(service.configuration().presets) == 2
    assert widget.key.text() == ""
    widget.profiles.setCurrentIndex(widget.profiles.findData(original_id))
    settle(app, vm)
    assert widget.name.text() == "Мой голос"
    assert widget.key.text() == "private-key"
    assert not service.status().verified


def test_actual_voiceover_panel_has_api_and_shared_playback(panel):
    app, service, vm, widget = panel

    class Store(dict):
        def set(self, key, value):
            self[key] = value

    root = QWidget()
    root.settings = Store(USE_VOICEOVER=True, VOICEOVER_METHOD="API")
    root._save_setting = root.settings.set
    actions = VoiceoverSettingsViewModel(events=SimpleNamespace(publish=lambda *args: None), remote_service=service)
    build_voiceover_settings_ui(root, QVBoxLayout(root), actions=actions)
    settle(app, actions.remote)
    controller = VoiceoverGuiController.__new__(VoiceoverGuiController)
    controller.view = root
    controller._effective_use_voice = lambda: True
    controller._effective_method = lambda: "API"
    controller._apply_voiceover_visibility_from_widgets()
    root.show()
    app.processEvents()
    assert root.method_combobox.currentText() == "API"
    assert root.api_settings_frame.isVisible()
    assert root.playback_settings_frame.isVisible()
    assert not root.local_settings_frame.isVisible()
    assert not root.tg_settings_frame.isVisible()
    actions.close()
    root.close()


def test_preview_playback_failure_releases_file_and_speaking_state(panel, tmp_path):
    app, service, vm, widget = panel
    path = tmp_path / "preview.wav"
    path.write_bytes(b"audio")
    transitions = []
    vm._playback_state = transitions.append
    with patch.object(service, "synthesize", new_callable=AsyncMock, return_value=str(path)), \
         patch("handlers.audio_handler.AudioHandler.handle_voice_file", new_callable=AsyncMock, side_effect=RuntimeError("no device")):
        with pytest.raises(RuntimeError):
            asyncio.run(vm._preview("test"))
    assert transitions == [True, False]
    assert not path.exists()
