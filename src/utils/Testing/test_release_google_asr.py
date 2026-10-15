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


@pytest.mark.parametrize("language", ["en-US", "ru-RU", "it-IT", "pt-BR", "pl-PL", "ko-KR", "hi-IN", "yue-Hant-HK"])
def test_google_language_setting_reaches_recognizer(language):
    adapter = GoogleRecognizer(None, Mock())
    adapter.apply_settings({"language": language})
    sr = Mock()
    sr.Recognizer.return_value.recognize_google.return_value = "recognized"
    sr.UnknownValueError = type("UnknownValueError", (Exception,), {})
    adapter._sr = sr
    adapter._is_initialized = True
    assert asyncio.run(adapter.transcribe(np.zeros(16), 16000)) == "recognized"
    assert sr.Recognizer.return_value.recognize_google.call_args.kwargs["language"] == language
    spec = next(row for row in adapter.settings_spec() if row["key"] == "language")
    assert spec["default"] == "ru-RU"
    assert adapter.get_default_settings() == {"language": "ru-RU"}



@pytest.mark.parametrize("language", ["en-US", "it-IT", "pt-BR", "pl-PL", "ko-KR", "hi-IN", "yue-Hant-HK"])
def test_google_choice_is_persisted_in_existing_asr_settings(tmp_path, language):
    from services.asr_settings_service import FileASRSettingsService
    path = str(tmp_path / "asr_settings.json")
    service = FileASRSettingsService(path)
    adapter = GoogleRecognizer(None, Mock())
    with patch("handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service", return_value=service):
        adapter.save_settings({"language": language})
    reloaded = FileASRSettingsService(path)
    with patch("handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service", return_value=reloaded):
        adapter.apply_settings(adapter.load_settings())
    assert adapter.language == language



def test_ukrainian_asr_choice_survives_restart_and_reaches_google(tmp_path):
    from services.asr_settings_service import FileASRSettingsService
    path = str(tmp_path / "asr_settings.json")
    adapter = GoogleRecognizer(None, Mock())
    schema = next(row for row in adapter.settings_spec() if row["key"] == "language")
    assert "uk-UA" in schema["options"]
    assert {
        "Russian", "Ukrainian", "English (US)", "English (UK)", "German", "French", "Spanish", "Japanese", "Chinese",
    } <= set(adapter.MODEL_CONFIGS[0]["languages"])
    original = FileASRSettingsService(path)
    with patch("handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service", return_value=original):
        adapter.save_settings({"language": "uk-UA"})
    restarted = GoogleRecognizer(None, Mock())
    with patch("handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service", return_value=FileASRSettingsService(path)):
        restarted.apply_settings(restarted.load_settings())
    sr = Mock()
    sr.UnknownValueError = type("UnknownValueError", (Exception,), {})
    sr.Recognizer.return_value.recognize_google.return_value = "Привіт"
    restarted._sr = sr
    restarted._is_initialized = True
    assert asyncio.run(restarted.transcribe(np.zeros(16), 16000)) == "Привіт"
    assert sr.Recognizer.return_value.recognize_google.call_args.kwargs["language"] == "uk-UA"
