import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handlers.llm_providers.base import LLMRequest, LLMResponse, ToolCall
from handlers.llm_providers.base import record_response_body_started
from handlers.llm_providers.errors import LLMProviderError
from managers.api_preset_resolver import PresetSettings
from managers.llm_request_runner import LLMRequestRunner
from managers.provider_manager import ProviderManager


def test_responses_dialect_routes_inside_existing_provider_manager():
    manager = ProviderManager.__new__(ProviderManager)
    calls = []
    manager._providers = [SimpleNamespace(name="common"), SimpleNamespace(
        name="responses", generate=lambda req: calls.append(req) or LLMResponse(text="ok"))]
    manager._unavailable = {}
    req = LLMRequest(model="m", messages=[], provider_name="common", dialect_id="openai_responses")
    assert manager.generate(req).text == "ok"
    assert calls == [req]


def test_siwc_routing_never_uses_generic_responses_provider():
    manager = ProviderManager.__new__(ProviderManager)
    calls = []
    manager._providers = [SimpleNamespace(name="chatgpt_plan", generate=lambda req: calls.append("siwc") or LLMResponse(text="ok")),
                          SimpleNamespace(name="responses", generate=lambda req: calls.append("api_key"))]
    manager._unavailable = {}
    manager.generate(LLMRequest(model="m", messages=[], provider_name="chatgpt_plan", dialect_id="openai_responses"))
    assert calls == ["siwc"]


def test_explicit_unsupported_native_tools_fail_instead_of_silently_disappearing():
    manager = ProviderManager.__new__(ProviderManager)
    req = LLMRequest(model="m", messages=[], provider_name="common", tools_on=True,
                     tools_payload=[{"name": "calculator"}], capabilities={"tools_native": False})
    with pytest.raises(LLMProviderError):
        manager._enforce_capabilities(req)
    assert req.tools_on


def test_runner_accepts_tool_only_response_once_without_fallback():
    preset = PresetSettings(protocol_id="openai_compatible_default", dialect_id="openai_chat_completions",
        provider_name="common", headers={}, transforms=[], capabilities={}, api_key="key",
        api_url="https://example.test/v1", api_model="m", preset_name="main", reserve_keys=[])
    calls = []
    result = LLMResponse(text=None, tool_calls=[ToolCall(name="calculator", arguments={}, id="c1")])
    manager = SimpleNamespace(generate=lambda req: calls.append(req) or result, close=lambda: None)
    resolver = SimpleNamespace(resolve_chain=lambda _: [preset, preset], apply_key_rotation=lambda p, _: p)
    runner = LLMRequestRunner(SimpleNamespace(get=lambda _, default=None: default), resolver,
                              SimpleNamespace(emit=lambda *args, **kw: None))
    runner.provider_manager.close()
    runner.provider_manager = manager
    try:
        response = runner.run(messages=[], preset_id=None, stream_callback=None,
            build_request=lambda p, m: LLMRequest(model=m, messages=[], provider_name="common", api_url=p.api_url),
            max_attempts=2, retry_delay=0, request_timeout=10)
        assert response is result
        assert len(calls) == 1
    finally:
        runner.close()


def test_forced_wire_stream_failure_after_body_never_retries_with_ui_stream_off():
    preset = PresetSettings(protocol_id="chatgpt_plan_default", dialect_id="openai_responses",
        provider_name="chatgpt_plan", headers={}, transforms=[], capabilities={"force_wire_stream": True}, api_key="",
        api_url="https://api.openai.com/v1/responses", api_model="m", preset_name="main", reserve_keys=[])
    calls = []

    def generate(req):
        calls.append(req)
        record_response_body_started(req)
        raise LLMProviderError(provider="chatgpt_plan", friendly_message="interrupted", retryable=True, phase="stream")

    resolver = SimpleNamespace(resolve_chain=lambda _: [preset, preset], apply_key_rotation=lambda p, _: p)
    runner = LLMRequestRunner(SimpleNamespace(get=lambda _, default=None: default), resolver,
                              SimpleNamespace(emit=lambda *args, **kw: None))
    runner.provider_manager.close()
    runner.provider_manager = SimpleNamespace(generate=generate, close=lambda: None)
    try:
        response = runner.run(messages=[], preset_id=None, stream_callback=None,
            build_request=lambda p, m: LLMRequest(model=m, messages=[], provider_name=p.provider_name,
                api_url=p.api_url, stream=False, capabilities=p.capabilities),
            max_attempts=2, retry_delay=0, request_timeout=10)
        assert not response.text
        assert len(calls) == 1
        assert not runner.last_error.retryable
    finally:
        runner.close()
