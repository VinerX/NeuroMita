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



@pytest.mark.parametrize("template,base,names,expected", [
    ("Google AI Studio", 3, ["Google AI Studio 1", "Google AI Studio 2", "Google AI Studio 4"], "Google AI Studio 3"),
    ("OpenRouter", 2, ["OpenRouter 1", "My renamed API"], "OpenRouter 2"),
    ("Google AI Studio", 3, [], "Google AI Studio 1"),
])
def test_add_preset_immediately_uses_selected_template_and_unique_number(app, template, base, names, expected):
    view = QWidget()
    view.template_combo = QComboBox(view)
    view.template_combo.addItem("No template", None)
    view.template_combo.addItem(template, base)
    view.template_combo.setCurrentIndex(1)
    existing = {i: SimpleNamespace(base_name=name) for i, name in enumerate(names)}
    editor = SimpleNamespace(view=view, custom_presets_list_items=existing,
        _protocol_default_id="openai", _parse_base=lambda value: value)
    service = Mock()
    service.save_custom.return_value = 1001
    editor._bus_call_async = lambda call, apply, **kwargs: call()
    with patch("PyQt6.QtWidgets.QDialog.exec", side_effect=AssertionError("Creation must not open a modal")), \
         patch("controllers.gui.api_settings.editor_mixin.use", return_value=service):
        EditorMixin._add_custom_preset_async(editor)
    payload = service.save_custom.call_args.args[0]
    assert payload["name"] == expected
    assert payload["base"] == base
    assert [item.base_name for item in existing.values()] == names
    view.close()



def test_existing_manual_preset_rename_is_preserved(app):
    from ui.settings.api_settings.widgets import CustomPresetListItem
    item = CustomPresetListItem(1001, "Google AI Studio 1")
    view = SimpleNamespace(custom_presets_list=SimpleNamespace(currentItem=lambda: item),
        provider_label=Mock(), preset_name_row=Mock())
    editor = SimpleNamespace(view=view, current_preset_data={"id": 1001, "name": item.base_name, "base": 3},
        _snapshot=None)
    editor._bus_call_async = lambda call, apply, **kwargs: apply(call())
    service = Mock()
    service.save_custom.return_value = 1001
    with patch("controllers.gui.api_settings.editor_mixin.QInputDialog.getText", return_value=("My Ukrainian API", True)), \
         patch("controllers.gui.api_settings.editor_mixin.use", return_value=service):
        EditorMixin._rename_custom_preset_async(editor)
    assert service.save_custom.call_args.args[0]["name"] == "My Ukrainian API"
    assert item.base_name == "My Ukrainian API"
    assert editor.current_preset_data["name"] == "My Ukrainian API"
