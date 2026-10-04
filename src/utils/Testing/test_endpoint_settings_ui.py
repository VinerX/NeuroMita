from dataclasses import asdict
from unittest.mock import Mock

import localization
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from controllers.api_presets_controller import ApiTemplate
from controllers.gui.api_settings.editor_mixin import EditorMixin
from controllers.gui.voiceover_controller import VoiceoverGuiController
from localization.live import language_changed_signal
from presets.api_templates import API_TEMPLATES_DATA
from ui.settings.api_settings.ui import build_api_settings_ui
from ui.widgets.tr_combobox import TRQComboBox
from ui.widgets.template_url_edit import TemplateUrlEdit

_APP = None


@pytest.fixture
def editor():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    root = QWidget()
    root.settings = {}
    build_api_settings_ui(root, QVBoxLayout(root))
    result = EditorMixin()
    result.view = root
    result._is_loading_ui = False
    result._snapshot = None
    result._help_links_lang_hook_bound = True
    result._refresh_model_settings_dialect = Mock()
    result._set_dirty = Mock()
    result._state_save_timer = Mock()
    result._active_template = None
    result.current_preset_data = {}
    yield result
    root.close()
    root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


def test_custom_check_field_controls_check_button_live(editor):
    root = editor.view
    editor._apply_help_links({})
    assert not root.api_test_url_row.isHidden()
    assert root.test_button.isHidden()
    root.api_test_url_row.set_text("http://lan:5000/models")
    editor._on_field_changed()
    assert not root.test_button.isHidden()
    root.api_test_url_row.set_text("")
    editor._on_field_changed()
    assert root.test_button.isHidden()


def test_local_server_address_is_not_reset_when_other_fields_change(editor):
    root = editor.view
    template = next(item for item in API_TEMPLATES_DATA if item["id"] == 9)
    editor._active_template = asdict(ApiTemplate(**template))
    root.template_combo.addItem("LM Studio", 9)
    root.api_url_row.set_text("http://192.168.1.10:9000")
    root.api_model_row.set_text("another-model")
    editor._on_field_changed()
    assert root.api_url_row.text() == "http://192.168.1.10:9000/v1/chat/completions"
    assert root.api_test_url_row.isHidden()
    assert not root.test_button.isHidden()


def test_segment_navigation_and_https_input(editor):
    root = editor.view
    template = next(item for item in API_TEMPLATES_DATA if item["id"] == 9)
    control = root.api_url_row.edit
    control.set_template(template)
    control.setText(template["url"])
    control.setParent(None)
    control.resize(650, 40)
    control.show()
    control.activateWindow()
    QApplication.processEvents()
    control.address_edit.setFocus()
    control.address_edit.setCursorPosition(0)
    QTest.keyClick(control.address_edit, Qt.Key.Key_Left)
    assert control.secure_edit.hasFocus()
    QTest.keyClicks(control.secure_edit, "s")
    assert control.address_edit.hasFocus()
    assert control.text() == "https://127.0.0.1:1234/v1/chat/completions"
    QTest.keyClick(control.address_edit, Qt.Key.Key_Backspace)
    assert control.secure_edit.hasFocus()
    assert control.secure_edit.text() == ""
    QTest.keyClick(control.secure_edit, Qt.Key.Key_Right)
    assert control.address_edit.hasFocus()
    assert control.address_edit.cursorPosition() == 0
    QTest.keyClick(control.address_edit, Qt.Key.Key_Left)
    QTest.keyClick(control.secure_edit, Qt.Key.Key_Tab)
    assert control.address_edit.hasFocus()
    assert control.suffix.text() == "/v1/chat/completions"
    control.close()
    control.deleteLater()


def test_paste_full_url_distributes_segments_and_preserves_template_path(editor):
    root = editor.view
    template = next(item for item in API_TEMPLATES_DATA if item["id"] == 9)
    control = root.api_url_row.edit
    control.set_template(template)
    QApplication.clipboard().setText(
        "https://lan.example:444/proxy/v1/chat/completions"
    )
    QTest.keyClick(
        control.address_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier
    )
    assert control.secure_edit.text() == "s"
    assert control.address_edit.text() == "lan.example:444/proxy"
    assert control.text() == "https://lan.example:444/proxy/v1/chat/completions"
    control.address_edit.deselect()
    QTest.keyClick(
        control.address_edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier
    )
    assert QApplication.clipboard().text() == control.text()
    control.set_template({})
    assert control.text() == "https://lan.example:444/proxy/v1/chat/completions"
    control.setText("https://custom/api/endpoint")
    assert control.text() == "https://custom/api/endpoint"


def test_address_expands_smoothly_and_pushes_locked_path(editor):
    control = TemplateUrlEdit()
    control.set_template(next(item for item in API_TEMPLATES_DATA if item["id"] == 9))
    control.setText("http://lan:1234/v1/chat/completions")
    control.resize(740, 40)
    control.show()
    QApplication.processEvents()
    initial_width = control.address_edit.width()
    initial_path_x = control.suffix.x()
    control.address_edit.setText("my-long-lan-server-address:1234")
    assert control.address_edit.width() == initial_width
    QTest.qWait(200)
    assert control.address_edit.width() > initial_width
    assert control.suffix.x() > initial_path_x
    assert (
        control.text() == "http://my-long-lan-server-address:1234/v1/chat/completions"
    )
    control.address_edit.setText("x" * 400)
    QTest.qWait(200)
    assert control.suffix.geometry().right() < control.width()
    control.close()
    control.deleteLater()


def test_local_voice_names_retranslate_from_catalog_without_selection_signal(
    editor, monkeypatch
):
    language = ["EN"]
    monkeypatch.setattr(localization, "_current_language", lambda: language[0])
    combo = TRQComboBox()
    VoiceoverGuiController._add_local_model_item(combo, "cached name", "high_clf5")
    VoiceoverGuiController._add_local_model_item(combo, "cached name", "high+low")
    combo.setCurrentIndex(1)
    changed = Mock()
    combo.currentIndexChanged.connect(changed)
    assert combo.itemText(0) == "Cross-Lingual F5-TTS (English & Chinese)"
    assert combo.currentText() == "F5-TTS + RVC (Russian)"
    language[0] = "RU"
    language_changed_signal().emit("RU")
    assert combo.itemText(0) == "Cross-Lingual F5-TTS (Английский и китайский)"
    assert combo.currentText() == "F5-TTS + RVC (Русский)"
    assert combo.currentData() == "high+low"
    changed.assert_not_called()
    language[0] = "EN"
    language_changed_signal().emit("EN")
    assert combo.currentText() == "F5-TTS + RVC (Russian)"
    changed.assert_not_called()
    combo.deleteLater()
