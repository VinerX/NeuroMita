from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.pages.settings.settings_page_widget import SettingsPage
from ui.pages.settings.settings_presentation import SettingsPageState
from ui.settings.voiceover_settings.widgets import VoiceCard
from ui.widgets.loading_spinner import LoadingSpinner

_APP = None


def test_loading_spinner_animates_and_stops_when_hidden():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    spinner = LoadingSpinner()
    try:
        spinner.show()
        _APP.processEvents()
        timer, angle, _step = spinner._animation.info[spinner]
        QTest.qWait(120)
        assert spinner._animation.info[spinner][1] != angle
        assert timer.isActive()
        spinner.hide()
        angle = spinner._animation.info[spinner][1]
        QTest.qWait(80)
        assert spinner._animation.info[spinner][1] == angle
        assert not timer.isActive()
    finally:
        spinner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_only_local_voice_cards_wait_for_runtime():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    page = QWidget()
    layout = QVBoxLayout(page)
    local = VoiceCard()
    local.setProperty("requiresLocalVoice", True)
    remote = VoiceCard()
    layout.addWidget(local)
    layout.addWidget(remote)
    host = SimpleNamespace(settings_containers={"voice": page})
    try:
        SettingsPage._render_feature_state(
            host,
            SettingsPageState(
                preparing_features=frozenset({"voice"}),
            ),
        )
        assert not local.isEnabled()
        assert remote.isEnabled()
        assert local.objectName() == "VoiceCard"
        progress = local.findChild(QWidget, "VoiceRuntimeProgress")
        assert progress is not None
        assert not progress.isHidden()
        SettingsPage._render_feature_state(host, SettingsPageState())
        assert local.isEnabled()
        assert progress.isHidden()
    finally:
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
