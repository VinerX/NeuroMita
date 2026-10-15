from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from controllers.api_presets_controller import ApiPresetsController
from controllers.gui.api_settings.controller import ApiSettingsController
from controllers.gui.api_settings.editor_mixin import EditorMixin
from controllers.gui.api_settings.model_settings_controller import PresetModelSettingsController
from controllers.gui.api_settings.presets_mixin import PresetsMixin
from controllers.gui.api_settings.protocols_mixin import ProtocolsMixin
from handlers.llm_providers.message_transforms import apply_transforms, get_transform_catalog
from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.http_transport import LLMHttpClient
from managers.api_preset_resolver import ApiPresetResolver
from managers.provider_manager import ProviderManager
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService
from presets.api_templates import API_TEMPLATES_DATA
from ui.settings.api_settings.ui import build_api_settings_ui
from ui.settings.api_settings.widgets import CustomPresetListItem


STEP = [{"id": "normalize_system_messages"}]
_APP = None


def test_strict_template_receives_one_system_and_positioned_current_context():
    source = [
        {"role": "system", "content": "persona"},
        {"role": "system", "content": "response format"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "system", "content": "current time"},
        {"role": "system", "content": "game state"},
        {"role": "user", "content": "new question"},
    ]
    result, trace = apply_transforms(source, STEP)
    assert result == [
        {"role": "system", "content": "persona\n\nresponse format"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "[SYSTEM INFO]\ncurrent time"},
        {"role": "user", "content": "[SYSTEM INFO]\ngame state"},
        {"role": "user", "content": "new question"},
    ]
    assert not trace[0].get("skipped")
    assert apply_transforms(result, STEP)[0] == result


def test_multimodal_context_and_message_metadata_survive_without_mutation():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    source = [
        {"role": "system", "content": [{"type": "text", "text": "persona"}]},
        {"role": "system", "content": "format"},
        {"role": "assistant", "content": "history"},
        {"role": "system", "content": [image], "name": "runtime"},
        {"role": "user", "content": [{"type": "text", "text": "look"}, image]},
    ]
    original = deepcopy(source)
    result, _ = apply_transforms(source, STEP)
    assert result[0]["content"] == [
        {"type": "text", "text": "persona"}, {"type": "text", "text": "\n\n"},
        {"type": "text", "text": "format"}
    ]
    assert result[2] == {"role": "user", "name": "runtime", "content": [
        {"type": "text", "text": "[SYSTEM INFO]"}, image
    ]}
    assert result[3] == original[4]
    result[2]["content"][1]["image_url"]["url"] = "changed"
    assert source == original


def test_normalization_handles_empty_blocks_and_custom_tag():
    result, _ = apply_transforms([
        {"role": "system", "content": " "},
        {"role": "user", "content": "question"},
        {"role": "system", "content": ""},
        {"role": "system", "content": [{"type": "text", "text": "update"}]},
    ], [{"id": "normalize_system_messages", "params": {"tag": "[STATE]"}}])
    assert result == [
        {"role": "user", "content": "question"},
        {"role": "user", "content": [{"type": "text", "text": "[STATE]\nupdate"}]},
    ]


def test_catalog_exposes_positional_normalization():
    assert "normalize_system_messages" in {entry["id"] for entry in get_transform_catalog()}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr("core.app_paths.base_dir", lambda: tmp_path)
    monkeypatch.setattr(ApiPresetsController, "_migrate_old_api_keys", lambda self: None)
    service = ModelSettingsService(SchemaRepository(tmp_path / "schemas"))
    controller = ApiPresetsController(model_settings_service=service, legacy_generation_settings={})
    yield controller, service
    controller.close()


@pytest.mark.parametrize("base", [9, 10])
@pytest.mark.parametrize("steps", [STEP, []])
def test_local_template_pipeline_round_trips_into_resolved_request(storage, base, steps):
    controller, service = storage
    pid = controller.save_custom({"name": "local", "base": base, "protocol_overrides": {
        "transforms": steps, "capabilities": {"streaming": False}, "headers": {"X-Test": "ignored"}
    }})
    preset = controller.get_full(pid)
    assert preset["pipeline_editable"] is True
    resolver = ApiPresetResolver({}, None, model_settings_service=service)
    resolver._load_preset_full = controller.get_full
    resolver._build_http_request_via_protocols_controller = lambda **kwargs: (kwargs["url"], kwargs["extra_headers"])
    resolved = resolver.resolve(pid)
    assert resolved.transforms == steps
    assert resolved.capabilities["streaming"] is True
    assert resolved.headers == {}
    assert resolved.protocol_id == ("lmstudio_default" if base == 9 else "openai_compatible_default")
    controller._load_data()
    assert controller.get_full(pid)["protocol_overrides"]["transforms"] == steps


def test_hosted_template_ignores_pipeline_override(storage):
    controller, service = storage
    pid = controller.save_custom({"name": "hosted", "base": 2, "protocol_overrides": {"transforms": STEP}})
    resolver = ApiPresetResolver({}, None, model_settings_service=service)
    resolver._load_preset_full = controller.get_full
    resolver._build_http_request_via_protocols_controller = lambda **kwargs: (kwargs["url"], {})
    assert resolver.resolve(pid).transforms != STEP


def test_saved_local_pipeline_reaches_http_with_strict_template_compatible_roles(storage):
    controller, service = storage
    pid = controller.save_custom({"name": "Qwen", "base": 9, "default_model": "qwen3.5-9b",
        "protocol_overrides": {"transforms": STEP}})
    resolver = ApiPresetResolver({}, None, model_settings_service=service)
    resolver._load_preset_full = controller.get_full
    resolver._build_http_request_via_protocols_controller = lambda **kwargs: (kwargs["url"], {})
    settings = resolver.resolve(pid)
    captured = []

    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        if any(message["role"] == "system" for message in payload["messages"][1:]):
            return httpx.Response(400, json={"error": {"message": "System message must be at the beginning."}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    transport = LLMHttpClient(enable_http2=False, client_factory=lambda *_: httpx.Client(transport=httpx.MockTransport(respond)))
    manager = ProviderManager.__new__(ProviderManager)
    manager.http_transport = transport
    manager._providers = [CommonProvider(http_transport=transport)]
    source = [
        {"role": "system", "content": "persona"},
        {"role": "system", "content": "format"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "system", "content": "current time"},
        {"role": "user", "content": "new question"},
    ]
    try:
        response = manager.generate(LLMRequest(
            model=settings.api_model, messages=deepcopy(source), api_url=settings.api_url,
            protocol_id=settings.protocol_id, provider_name=settings.provider_name,
            transforms=settings.transforms, capabilities=settings.capabilities,
            native_parameters=settings.native_parameters,
        ))
        assert response.text == "OK"
        assert captured[0]["model"] == "qwen3.5-9b"
        assert captured[0]["messages"] == [
            {"role": "system", "content": "persona\n\nformat"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "[SYSTEM INFO]\ncurrent time"},
            {"role": "user", "content": "new question"},
        ]
    finally:
        manager.close()


class EditorHarness(EditorMixin, PresetsMixin, ProtocolsMixin):
    _on_configure_pipeline_clicked = ApiSettingsController._on_configure_pipeline_clicked
    _effective_transforms_for_current = ApiSettingsController._effective_transforms_for_current

    def _bus_call_async(self, call, apply, **kwargs):
        apply(call())


@pytest.fixture
def editor(storage, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    controller, service = storage
    for module in ("editor_mixin", "presets_mixin"):
        monkeypatch.setattr("controllers.gui.api_settings." + module + ".use", lambda contract: controller)
    widget = QWidget()
    widget.settings = {}
    build_api_settings_ui(widget, QVBoxLayout(widget))
    widget.template_combo.addItem("No template", None)
    for template in API_TEMPLATES_DATA:
        widget.template_combo.addItem(template["name"], template["id"])
    harness = EditorHarness()
    harness.view = widget
    harness.model_settings_controller = PresetModelSettingsController(widget.model_settings_form, service=service)
    harness._protocols = harness._load_protocol_catalog()
    harness._protocol_default_id = harness._pick_default_protocol_id()
    harness._populate_protocol_combo()
    harness._protocol_overrides = {}
    harness._transform_catalog = get_transform_catalog()
    harness._snapshot = None
    harness._pending_select_id = None
    harness._is_loading_ui = False
    harness._help_links_lang_hook_bound = True
    harness._state_save_timer = QTimer(widget)
    harness.custom_presets_list_items = {}
    harness.events = []
    harness.event_bus = SimpleNamespace(emit=lambda event, data: harness.events.append(data))
    yield harness, controller
    harness.model_settings_controller.deleteLater()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


def load_editor(harness, controller, base=9, overrides=None):
    pid = controller.save_custom({"name": "model", "base": base, "protocol_overrides": overrides or {}})
    harness.custom_presets_list_items[pid] = CustomPresetListItem(pid, "model")
    harness.load_preset_async(pid)
    return pid


def test_local_editor_can_apply_cancel_save_and_reopen_pipeline(editor):
    harness, controller = editor
    pid = load_editor(harness, controller)
    assert not harness.view.protocol_section.isHidden()
    assert not harness.view.protocol_row.combo.isEnabled()
    harness._on_configure_pipeline_clicked()
    harness.events[-1]["payload"]["on_apply"](STEP)
    assert harness.view.save_preset_button.isEnabled()
    harness._cancel_changes()
    assert harness._effective_transforms_for_current() == []
    assert not harness.view.save_preset_button.isEnabled()
    harness._on_configure_pipeline_clicked()
    harness.events[-1]["payload"]["on_apply"](STEP)
    harness._save_preset_async()
    harness.load_preset_async(pid)
    assert harness._effective_transforms_for_current() == STEP
    assert not harness.view.save_preset_button.isEnabled()
    assert controller.get_full(pid)["protocol_id"] == "lmstudio_default"


def test_loading_another_preset_clears_previous_pipeline(editor):
    harness, controller = editor
    load_editor(harness, controller, overrides={"transforms": STEP})
    assert harness._effective_transforms_for_current() == STEP
    load_editor(harness, controller, base=10)
    assert harness._effective_transforms_for_current() == []
    assert not harness.view.protocol_section.isHidden()
    load_editor(harness, controller, base=2)
    assert harness.view.protocol_section.isHidden()


def test_custom_editor_reloads_saved_pipeline(editor):
    harness, controller = editor
    load_editor(harness, controller, base=None, overrides={"transforms": STEP})
    assert harness._effective_transforms_for_current() == STEP
    assert harness.view.protocol_row.combo.isEnabled()
