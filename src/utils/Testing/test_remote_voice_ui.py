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

from controllers.gui.remote_voice_settings_view_model import (
    RemoteVoiceSettingsViewModel,
)
from controllers.gui.voiceover_controller import VoiceoverGuiController
from controllers.gui.voiceover_settings_view_model import VoiceoverSettingsViewModel
from core.networking import HttpClientRegistry
from services.remote_voice_repository import RemoteVoiceRepository
from services.remote_voice_service import DefaultRemoteVoiceService
from ui.settings.voiceover_settings.remote_api import RemoteVoiceSettingsWidget
from ui.settings.voiceover_settings.ui import build_voiceover_settings_ui
from ui.character_names import character_display_name

_APP = None


def settle(app, vm):
    deadline = time.monotonic() + 5
    while vm.state.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert not vm.state.busy


@pytest.fixture
def panel(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    app = _APP
    app.setQuitOnLastWindowClosed(False)
    service = DefaultRemoteVoiceService(
        repository=RemoteVoiceRepository(tmp_path / "profiles.json"),
        registry=HttpClientRegistry(),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(401))
        ),
    )
    registry = SimpleNamespace(
        all_ids=lambda: ["Kind", "Cappie"],
        display_name_of=lambda cid: {"Kind": "Kind Mita", "Cappie": "Cappie"}[cid],
        current_id=lambda: "Kind",
    )
    vm = RemoteVoiceSettingsViewModel(service, character_registry=lambda: registry)
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
    assert widget.preview_character.text() == widget.character_title.text()
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
    widget.key.setText("private-key")
    widget.voice.setText("a" * 32)
    widget.add_button.click()
    settle(app, vm)
    assert len(service.configuration().presets) == 2
    assert widget.key.text() == ""
    widget.profiles.setCurrentIndex(widget.profiles.findData(original_id))
    settle(app, vm)
    assert service.configuration().active.name == "Fish Audio"
    assert widget.key.text() == "private-key"
    assert widget.voice.text() == "a" * 32
    assert not service.status().verified


def test_actual_voiceover_panel_has_api_and_shared_playback(panel):
    app, service, vm, widget = panel

    class Store(dict):
        def set(self, key, value):
            self[key] = value

    root = QWidget()
    root.settings = Store(USE_VOICEOVER=True, VOICEOVER_METHOD="API")
    root._save_setting = root.settings.set
    actions = VoiceoverSettingsViewModel(
        events=SimpleNamespace(publish=lambda *args: None), remote_service=service
    )
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
    assert root.api_preview_frame.isVisible()
    remote_panel = root.api_settings_frame.findChild(RemoteVoiceSettingsWidget)
    remote_panel.key.setText("Draft key")
    root.use_voice_checkbox.setChecked(False)
    controller._effective_use_voice = root.use_voice_checkbox.isChecked
    controller._apply_voiceover_visibility_from_widgets()
    root.voice_method_selector.buttons["TG"].click()
    assert root.settings["VOICEOVER_METHOD"] == "TG"
    assert root.tg_settings_frame.isVisible()
    assert root.telegram_status_frame.isVisible()
    assert not root.api_preview_frame.isVisible()
    root.voice_method_selector.buttons["Local"].click()
    assert root.settings["VOICEOVER_METHOD"] == "Local"
    assert root.local_status_frame.isVisible()
    root.voice_method_selector.buttons["API"].click()
    assert root.api_preview_frame.isVisible()
    assert remote_panel.key.text() == "Draft key"
    actions.remote.update_state(busy=True)
    assert not root.api_preview_frame.isEnabled()
    assert not remote_panel.controls.isEnabled()
    actions.close()
    root.close()


def test_preview_playback_failure_releases_file_and_speaking_state(panel, tmp_path):
    app, service, vm, widget = panel
    path = tmp_path / "preview.wav"
    path.write_bytes(b"audio")
    transitions = []
    vm._playback_state = transitions.append
    with patch.object(
        service, "synthesize", new_callable=AsyncMock, return_value=str(path)
    ), patch(
        "handlers.audio_handler.AudioHandler.handle_voice_file",
        new_callable=AsyncMock,
        side_effect=RuntimeError("no device"),
    ):
        with pytest.raises(RuntimeError):
            asyncio.run(vm._preview("test"))
    assert transitions == [True, False]
    assert not path.exists()


def test_avatar_tabs_keep_independent_drafts_and_save_together(panel):
    app, service, vm, widget = panel
    assert widget.voice_tabs.count() == 3
    assert widget.voice_tabs.height() >= 80
    assert widget.voice_tabs.tabData(widget.voice_tabs.currentIndex()) == "Kind"
    widget.voice.setText("a" * 32)
    assert widget.character_title.text() == character_display_name("Kind")
    widget.voice_tabs.setCurrentIndex(2)
    assert widget.voice.text() == ""
    assert widget.character_title.text() == character_display_name("Cappie")
    widget.voice.setText("b" * 32)
    widget.voice_tabs.setCurrentIndex(1)
    assert widget.voice.text() == "a" * 32
    assert widget.character_title.text() == character_display_name("Kind")
    widget.save_button.click()
    settle(app, vm)
    assert not vm.state.error
    assert service.configuration().active.voice_for("Kind") == "a" * 32
    assert service.configuration().active.voice_for("Cappie") == "b" * 32
    assert service.configuration().active.voice_id == ""
    widget.voice_tabs.setCurrentIndex(0)
    assert widget.character_title.text() in ("Общий голос", "Default voice")
    assert not hasattr(widget, "voice_display_name")


def test_preview_uses_selected_tab_and_cleans_file(panel, tmp_path):
    app, service, vm, widget = panel
    path = tmp_path / "preview.wav"
    path.write_bytes(b"audio")
    widget.voice_tabs.setCurrentIndex(2)
    with patch.object(
        service, "synthesize", new_callable=AsyncMock, return_value=str(path)
    ) as synthesize, patch(
        "handlers.audio_handler.AudioHandler.handle_voice_file", new_callable=AsyncMock
    ):
        widget.preview_button.click()
        settle(app, vm)
    synthesize.assert_awaited_once_with(
        widget.sample.toPlainText(), character_id="Cappie"
    )
    assert not path.exists()


def test_painted_tabs_support_mouse_keyboard_and_finish_animation(panel):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    app, service, vm, widget = panel
    widget.resize(700, 760)
    widget.show()
    app.processEvents()
    tabs = widget.voice_tabs
    QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(2).center())
    assert tabs.tabData(tabs.currentIndex()) == "Cappie"
    QTest.qWait(270)
    assert abs(tabs.activePosition - 2) < 0.01
    QTest.keyClick(tabs, Qt.Key.Key_Home)
    assert tabs.tabData(tabs.currentIndex()) is None
    QTest.keyClick(tabs, Qt.Key.Key_Right)
    assert tabs.tabData(tabs.currentIndex()) == "Kind"


def test_voice_catalog_link_uses_selected_template(panel):
    app, service, vm, widget = panel
    assert '<a href="voices"' in widget.voice_hint.text()
    assert "Голос не назначен" not in widget.voice_hint.text()
    with patch(
        "ui.settings.voiceover_settings.remote_api.QDesktopServices.openUrl"
    ) as open_url:
        widget.voice_hint.linkActivated.emit("voices")
    assert open_url.call_args.args[0].toString() == vm.templates[0].voices_url


def test_language_refresh_preserves_drafts_selection_and_key_visibility(
    panel, monkeypatch
):
    import localization
    from localization.live import refresh_all

    app, service, vm, widget = panel
    monkeypatch.setattr(localization, "_current_language", lambda: "EN")
    widget.voice_tabs.setCurrentIndex(0)
    widget.voice.setText("a" * 32)
    widget.eye.trigger()
    vm.update_state(busy=True)
    refresh_all()
    assert widget.character_title.text() == "Default voice"
    assert widget.voice_tabs.accessibleDescription() == "Default voice"
    assert widget.status.text() == "Working…"
    assert widget.eye.toolTip() == "Hide API key"
    assert "Fish Audio catalog" in widget.voice_hint.text()
    assert widget.sample.toPlainText().startswith("Hi!")
    assert widget.voice.text() == "a" * 32
    widget.sample.setPlainText("My own preview text")
    monkeypatch.setattr(localization, "_current_language", lambda: "ZH")
    refresh_all()
    assert widget.character_title.text() == "通用声音"
    assert widget.sample.toPlainText() == "My own preview text"
    assert widget.voice.text() == "a" * 32
    vm.update_state(
        busy=False, message="Fish Audio: API-ключ не принят (HTTP 401).", error=True
    )
    monkeypatch.setattr(localization, "_current_language", lambda: "EN")
    refresh_all()
    assert widget.status.text() == "Fish Audio: API key rejected (HTTP 401)."
    vm.update_state(busy=True)
    assert widget.status.text() == "Working…"
