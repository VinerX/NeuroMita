import json
import threading
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controllers.api_presets_controller as module
from controllers.api_presets_controller import (
    ApiPresetsController,
    ApiTemplate,
    UserPreset,
)
from core.events import Event, Events
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService
from presets.api_endpoints import resolve_api_url, resolve_test_url, server_address
from presets.api_templates import API_TEMPLATES_DATA


@pytest.fixture
def controller(tmp_path):
    result = ApiPresetsController.__new__(ApiPresetsController)
    result.templates = {item["id"]: ApiTemplate(**item) for item in API_TEMPLATES_DATA}
    result.presets = {}
    result.presets_order = []
    result.preset_states = {}
    result.presets_path = tmp_path / "presets.json"
    result._io_lock = threading.RLock()
    result.event_bus = Mock()
    result.model_settings_service = ModelSettingsService(
        SchemaRepository(tmp_path / "schemas")
    )
    return result


@pytest.mark.parametrize("template_id", [9, 10])
def test_local_server_address_builds_both_endpoints(controller, template_id):
    template = asdict(controller.templates[template_id])
    address = "http://192.168.1.20:9000/proxy"
    request_url = resolve_api_url(template, address)
    assert request_url == address + "/v1/chat/completions"
    assert resolve_api_url(template, request_url) == request_url
    assert server_address(template, request_url) == address
    assert resolve_test_url(template, request_url) == address + "/v1/models"


@pytest.mark.parametrize("base", [None, 9, 10])
def test_endpoint_survives_save_and_disk_reload(controller, base):
    custom_url = "http://192.168.1.20:9000/proxy/v1/chat/completions"
    test_url = "http://192.168.1.20:9000/proxy/status"
    pid = controller.save_custom(
        {"name": "LAN", "base": base, "url": custom_url, "test_url": test_url}
    )
    assert pid is not None
    stored = json.loads(controller.presets_path.read_text(encoding="utf-8"))["presets"][
        str(pid)
    ]
    controller.presets[pid] = controller._user_preset_from_dict(stored)
    effective = controller._build_effective_preset_dict(pid)
    assert effective["url"] == custom_url
    assert effective["test_url"] == (
        test_url if base is None else "http://192.168.1.20:9000/proxy/v1/models"
    )


def test_cloud_template_ignores_endpoint_overrides(controller):
    template = next(
        item
        for item in controller.templates.values()
        if not item.url_editable and item.url
    )
    pid = controller.save_custom(
        {
            "name": "Cloud",
            "base": template.id,
            "url": "http://other",
            "test_url": "http://other/check",
        }
    )
    effective = controller._build_effective_preset_dict(pid)
    assert effective["url"] == template.url
    assert effective["test_url"] == template.test_url
    assert controller.presets[pid].url == ""
    assert controller.presets[pid].test_url == ""


def test_draft_updates_local_address_and_clears_custom_test_url(controller):
    controller.presets[1001] = UserPreset(id=1001, name="LAN", base=9)
    controller.presets_order = [1001]
    assert controller.save_state(1001, {"url": "http://192.168.1.40:5000"})
    effective = controller._build_effective_preset_dict(1001)
    assert effective["url"] == "http://192.168.1.40:5000/v1/chat/completions"
    assert effective["test_url"] == "http://192.168.1.40:5000/v1/models"
    controller.presets[1001].base = None
    controller.presets[1001].test_url = "http://server/models"
    assert controller.save_state(1001, {"test_url": ""})
    assert controller.presets[1001].test_url == ""


@pytest.mark.parametrize("base", [None, 9])
def test_check_uses_unsaved_endpoint_and_selected_protocol(
    controller, monkeypatch, base
):
    controller.presets[1001] = UserPreset(id=1001, name="Saved", base=9)
    supervisor = SimpleNamespace(start_thread=Mock())
    monkeypatch.setattr(module, "task_supervisor", lambda: supervisor)
    controller._on_test_connection(
        Event(
            Events.ApiPresets.TEST_CONNECTION,
            {
                "id": 1001,
                "base": base,
                "url": "http://192.168.1.50:3333/v1/chat/completions",
                "test_url": "http://custom/status",
                "protocol_id": "openai_compatible_default",
                "key": "secret",
            },
        )
    )
    _, template, key = supervisor.start_thread.call_args.kwargs["args"]
    assert template.test_url == (
        "http://custom/status" if base is None else "http://192.168.1.50:3333/v1/models"
    )
    assert template.protocol_id == (
        "openai_compatible_default" if base is None else "lmstudio_default"
    )
    assert key == "secret"


def test_template_can_declare_independent_test_url_override():
    template = {
        "url_editable": False,
        "test_url_editable": True,
        "test_url": "https://fixed/models",
    }
    assert (
        resolve_test_url(template, "https://fixed/chat", "https://other/health")
        == "https://other/health"
    )


@pytest.mark.parametrize(
    "url",
    [
        "111232132",
        "http://",
        "ftp://server/models",
        "http://host:wrong/models",
        "http://[bad",
        "http://two hosts/models",
    ],
)
def test_invalid_test_url_is_rejected_before_network_task(controller, monkeypatch, url):
    supervisor = SimpleNamespace(start_thread=Mock())
    monkeypatch.setattr(module, "task_supervisor", lambda: supervisor)
    controller._on_test_connection(
        Event(
            Events.ApiPresets.TEST_CONNECTION,
            {"id": 1001, "base": None, "test_url": url},
        )
    )
    supervisor.start_thread.assert_not_called()
    event, payload = controller.event_bus.emit.call_args.args
    assert event == Events.ApiPresets.TEST_FAILED
    assert payload["error"] == "invalid_test_url"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:1234/v1/models",
        "https://192.168.1.10:8080/models",
        "http://[::1]:1234/v1/models",
        "http://lan-server/models",
    ],
)
def test_validation_accepts_local_and_remote_http_addresses(url):
    from core.networking.errors import valid_http_url

    assert valid_http_url(url)


def test_check_handles_common_network_error_without_traceback(controller, monkeypatch):
    from core.networking.errors import NetworkTimeoutError

    url = "https://server.test/models?key=secret"
    builder = SimpleNamespace(
        build_http_request=lambda **kwargs: {
            "url": url,
            "headers": {},
            "safe_url": "https://server.test/models?key=<redacted>",
        }
    )
    monkeypatch.setattr(module, "use", lambda _contract: builder)
    error = NetworkTimeoutError(
        "api-presets",
        "Истекло время ожидания ответа сервера.",
        code="network.timeout.read",
        url=url,
    )
    controller._http_transport = SimpleNamespace(get=Mock(side_effect=error))
    log = Mock()
    monkeypatch.setattr(module, "logger", log)
    controller._sync_test_connection(
        1001, ApiTemplate(id=0, name="Custom", test_url=url), ""
    )
    log.error.assert_not_called()
    log.warning.assert_called_once()
    event, payload = controller.event_bus.emit.call_args.args
    assert event == Events.ApiPresets.TEST_RESULT
    assert not payload["success"]
    assert payload["error"] == "network.timeout.read"
    assert "secret" not in payload["error_details"]["url"]


def test_non_json_response_has_readable_message_without_traceback(
    controller, monkeypatch
):
    url = "http://localhost:1234/"
    builder = SimpleNamespace(
        build_http_request=lambda **kwargs: {"url": url, "headers": {}}
    )
    monkeypatch.setattr(module, "use", lambda _contract: builder)
    response = SimpleNamespace(
        status_code=200, text="<html>Server home</html>", close=Mock()
    )
    controller._http_transport = SimpleNamespace(get=Mock(return_value=response))
    log = Mock()
    monkeypatch.setattr(module, "logger", log)
    controller._sync_test_connection(
        1001, ApiTemplate(id=0, name="Custom", test_url=url), ""
    )
    log.error.assert_not_called()
    response.close.assert_called_once()
    _, payload = controller.event_bus.emit.call_args.args
    assert not payload["success"]
    assert "JSON" in payload["message"]


@pytest.mark.parametrize(
    "status", [400, 401, 403, 404, 405, 408, 429, 500, 502, 503, 504, 418, 520]
)
@pytest.mark.parametrize("raised", [False, True])
def test_http_failure_explains_cause_and_action(
    controller, monkeypatch, status, raised
):
    import httpx
    from core.networking.errors import classify_network_error, http_status_message

    url = "http://localhost:1234/v1/models"
    builder = SimpleNamespace(
        build_http_request=lambda **kwargs: {"url": url, "headers": {}}
    )
    monkeypatch.setattr(module, "use", lambda _contract: builder)
    response = httpx.Response(
        status,
        text="untrusted response body with secret",
        request=httpx.Request("GET", url),
    )
    if raised:
        error = classify_network_error(
            "api-presets",
            httpx.HTTPStatusError(
                "failed", request=response.request, response=response
            ),
        )
        controller._http_transport = SimpleNamespace(get=Mock(side_effect=error))
    else:
        controller._http_transport = SimpleNamespace(get=Mock(return_value=response))
    controller._sync_test_connection(
        1001, ApiTemplate(id=0, name="Custom", test_url=url), ""
    )
    _, result = controller.event_bus.emit.call_args.args
    assert not result["success"]
    assert result["message"] == http_status_message(status, translate=module._)
    assert len(result["message"].split("\n\n")[1]) > 40
    assert "secret" not in result["message"]
    if status == 503:
        assert "позже" in result["message"] or "later" in result["message"]


def test_http_error_explanation_is_localized(monkeypatch):
    import localization
    from core.networking.errors import http_status_message

    monkeypatch.setattr(localization, "_current_language", lambda: "EN")
    message = http_status_message(503, translate=localization.translate)
    assert message.startswith("HTTP 503")
    assert "temporarily unavailable" in message
    assert "Retry later" in message
