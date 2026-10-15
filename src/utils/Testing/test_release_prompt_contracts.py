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


def test_clothing_prompt_requires_catalog_ids_and_segment_intents():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "extra" / "Prompts"
    behavior = (root / "Crazy" / "By_mactep_kot_new_mini" / "Main" / "common_behavior.txt").read_text(encoding="utf-8")
    assert "точные ID из блока Available Outfits" in behavior
    assert 'массив "intents" текущего сегмента' in behavior



@pytest.mark.parametrize("intents", [False, True])
@pytest.mark.parametrize("graph", [False, True])
def test_shared_prompt_renders_intent_contract_only_when_enabled(intents, graph):
    from pathlib import Path
    from DSL.dsl_engine import DslInterpreter
    script = (Path(__file__).resolve().parents[3] / "extra" / "Prompts" / "Structural" / "response_format_json.script").read_text(encoding="utf-8")
    class Resolver:
        def resolve_path(self, path):
            return path
        def load_text(self, path, _context):
            return "[<format.script>]" if path == "main_template.txt" else script
        def get_dirname(self, _path):
            return ""
    variables = {"SCHEMA_REASONING_ENABLED": False, "ENABLE_GAMES": False,
        "GRAPH_EXTRACTION_ENABLED": graph, "RAG_ENABLED": graph,
        "MITA_CAMERA_ENABLED": False, "MITA_CAMERA_ON_DEMAND": False,
        "TOOLS_DESCRIPTION": "", "CUSTOM_PARAMS_SCHEMA": ""}
    character = SimpleNamespace(char_id="Test", variables=variables, app_vars={},
        set_variable=lambda key, value: variables.update({key: value}))
    interpreter = DslInterpreter(character, Resolver())
    blocks, _messages = interpreter.process_main_template("main_template.txt",
        feature_overrides={"support_intents": intents})
    rendered = "\n".join(blocks)
    assert ("Intent types are not command strings" in rendered) == intents
    assert ("do not guess Cat" in rendered) == intents
    assert '"commands"' in rendered
