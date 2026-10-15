import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controllers.model_controller import ModelController
from core.request_policy import RequestPolicy
from handlers.chat_handler import ChatModel
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.http_transport import LLMHttpClient
from handlers.llm_providers.responses_provider import ResponsesProvider
from managers.api_preset_resolver import ApiPresetResolver
from schemas.structured_response import StructuredResponse
from services.contracts import RuntimeCapabilities
from services.structured_response_capabilities import resolve_structured_response_capabilities


@pytest.mark.parametrize("transport_kind", ["responses", "chat_http", "chat_openai_alias",
                                            "responses_to_chat_http", "responses_to_chat_openai_alias"])
@pytest.mark.parametrize("stream", [False, True])
def test_native_tool_roundtrip_through_chat_model_runner_manager_and_executor(monkeypatch, transport_kind, stream):
    responses = transport_kind.startswith("responses")
    fallback = transport_kind.startswith("responses_to_")
    wire_requests, executions, deltas = [], [], []
    final_text = '{"segments":[{"text":"Two"}]}'

    def handle(request):
        assert request.headers["authorization"] == "Bearer fixture-key"
        payload = json.loads(request.content)
        wire_requests.append(payload)
        is_responses = request.url.path.endswith("/responses")
        if fallback and is_responses and len(wire_requests) > 1:
            return httpx.Response(503, json={"error": {"message": "fixture unavailable"}})
        if fallback and not is_responses:
            assert all("responses_output" not in message and "responses_reasoning_items" not in message
                       for message in payload["messages"])
        if len(wire_requests) == 1:
            if responses:
                result = {"status": "completed", "model": "fixture-model", "output": [
                    {"type": "reasoning", "id": "rs1", "summary": [], "encrypted_content": "opaque"},
                    {"type": "function_call", "id": "fc1", "call_id": "real-call", "name": "calculator",
                     "arguments": '{"expression":"1+1"}'}],
                    "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}}
            else:
                result = {"model": "fixture-model", "choices": [{"index": 0, "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": [{"type": "function",
                        "id": "real-call", "function": {"name": "calculator", "arguments": '{"expression":"1+1"}'}}]}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}
        elif is_responses:
            result = {"status": "completed", "model": "fixture-model", "output": [{"type": "message",
                "id": "msg1", "role": "assistant", "content": [{"type": "output_text", "text": final_text}]}],
                "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11}}
        else:
            result = {"model": "fixture-model", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": final_text}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}}
        if not payload.get("stream"):
            return httpx.Response(200, json=result)
        if is_responses:
            chunks = [{"type": "response.completed", "response": result}]
        else:
            choice = result["choices"][0]
            delta = dict(choice["message"])
            for index, call in enumerate(delta.get("tool_calls", [])):
                call["index"] = index
            chunks = [{"model": result["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": choice["finish_reason"]}]},
                      {"choices": [], "usage": result["usage"]}]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        if not responses:
            body += "data: [DONE]\n\n"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    protocol = "openai_responses_default" if responses else "openai_compatible_default"
    preset = {"base": None, "name": "Fixture", "protocol_id": protocol, "key": "fixture-key",
              "default_model": "fixture-model", "url": "https://fixture.test/v1",
              "protocol_overrides": {"capabilities": {"streaming_with_tools": True, "supports_stream_usage": True}}}
    monkeypatch.setattr(ApiPresetResolver, "_load_preset_full", lambda *_: preset)
    monkeypatch.setattr("handlers.chat_handler._save_last_request_context", lambda *args, **kw: None)
    monkeypatch.setattr("handlers.chat_handler._save_last_response_context", lambda *args, **kw: None)
    settings = SimpleNamespace(get=lambda key, default=None: {"ENABLE_STREAMING": stream, "TOOL_MAX_DEPTH": 1,
        "MODEL_MESSAGE_ATTEMPTS_COUNT": 1, "MODEL_MESSAGE_ATTEMPTS_TIME": 0}.get(key, default))
    model = ChatModel(settings)
    manager = model.request_runner.provider_manager
    manager.close()
    transport = LLMHttpClient(enable_http2=False, client_factory=lambda *_: httpx.Client(transport=httpx.MockTransport(handle)))
    manager.http_transport = transport
    provider_type = ResponsesProvider if responses else CommonProvider
    provider = provider_type(http_transport=transport)
    if transport_kind == "chat_openai_alias":
        original_resolve = model.preset_resolver.resolve
        from dataclasses import replace
        monkeypatch.setattr(model.preset_resolver, "resolve", lambda *args, **kwargs: replace(
            original_resolve(*args, **kwargs), provider_name="openai"))
    manager._providers = [provider]
    if fallback:
        from dataclasses import replace
        alias = transport_kind.endswith("openai_alias")
        chat_provider = CommonProvider(http_transport=transport)
        manager._providers.append(chat_provider)
        main_preset = model.preset_resolver.resolve()
        fallback_preset = replace(main_preset, protocol_id="openai_compatible_default",
            dialect_id="openai_chat_completions", provider_name="openai" if alias else "common",
            preset_name="Chat fallback")
        monkeypatch.setattr(model.preset_resolver, "resolve_chain", lambda _: [main_preset, fallback_preset])
    profile = resolve_structured_response_capabilities(settings=settings, runtime=RuntimeCapabilities(),
        character=SimpleNamespace(), structured_output=True, tools_enabled=True, enabled_tools=["calculator"],
        tools_mode="native", tool_depth=0, tool_max_depth=1, images_available=False, has_custom_params=False, schema_reasoning=False)
    caps = {"structured_response_profile": profile, "structured_output": True, "tools_native": True}
    messages = [{"role": "user", "content": "What is one plus one?"}]

    def execute(name, arguments, **kw):
        executions.append((name, arguments))
        return "2"

    model.tool_manager.run = execute
    harness = SimpleNamespace(settings=settings, model=model, event_bus=SimpleNamespace(emit=lambda *args, **kw: None),
        _build_usage_snapshot=lambda *args, **kw: None, _split_response_thinking=lambda r: (r.text, r.reasoning or ""),
        _process_structured_output=lambda **kw: kw)
    try:
        response = model.generate(messages, capabilities_override=caps,
                                  stream_event_callback=deltas.append if stream else None)
        assert response and response.tool_calls[0].id == "real-call"
        structured = StructuredResponse.model_validate_json(response.text)
        result = ModelController._handle_tool_call(harness, structured=structured, visible_raw=response.text,
            think_text=response.reasoning or "", usage=response.usage, response_model=response.model,
            response_provider=response.provider_name, pricing_info=None, char=SimpleNamespace(), char_id="Crazy",
            char_name="Crazy", origin_message_id=None, capabilities=caps, policy=RequestPolicy(write_to_history=False),
            sender="Player", participants=[], user_input="calculate", image_data=[], image_source="", req_id="r",
            task_uid="t", event_type="chat", combined_messages=messages, preset_id=None, enabled_tools=["calculator"],
            tool_depth=0, native_tool_call=response.raw["native_tool_call"])
        assert executions == [("calculator", {"expression": "1+1"})]
        assert len(wire_requests) == (3 if fallback else 2)
        assert result["visible_raw"] == final_text
        assert result["usage"].total_tokens == 18
        first, followup = wire_requests[0], wire_requests[-1]
        assert first["tools"][0]["type"] == "function"
        assert (first["tools"][0] if responses else first["tools"][0]["function"])["name"] == "calculator"
        assert "tools" not in followup
        if responses and not fallback:
            assert any(item.get("type") == "reasoning" and item["encrypted_content"] == "opaque" for item in followup["input"])
            assert {"type": "function_call_output", "call_id": "real-call", "output": "2"} in followup["input"]
        else:
            assert next(m for m in followup["messages"] if m.get("tool_calls"))["tool_calls"][0]["id"] == "real-call"
            assert {"role": "tool", "tool_call_id": "real-call", "content": "2"} in followup["messages"]
        assert (first["text"]["format"] if responses else first["response_format"])["type"] == "json_schema"
        if stream:
            assert any(event.tool_call_id == "real-call" for event in deltas)
        if fallback:
            import sqlite3
            from controllers.history_controller import HistoryController
            from managers.database_manager import DatabaseManager
            from managers.history_manager import HistoryManager
            from services.native_tool_calls import native_tool_followup_messages

            connection = sqlite3.connect(":memory:", check_same_thread=False)
            class Connection:
                def __getattr__(self, name):
                    return getattr(connection, name)
                def close(self):
                    pass
            monkeypatch.setattr(DatabaseManager, "get_connection", lambda _: Connection())
            monkeypatch.setattr(DatabaseManager, "_instance", None)
            monkeypatch.setattr(DatabaseManager, "_path_override", None)
            monkeypatch.setattr(HistoryManager, "_schedule_history_embeddings", lambda *_: None)
            try:
                history = HistoryManager(storage_name="Crazy", character_id="Crazy")
                exchange = native_tool_followup_messages(response.raw["native_tool_call"], "2")
                history.add_messages([{"role": "assistant", "content": "Checking",
                    "structured_data": {"native_tool_history": exchange}}])
                rows = HistoryManager(storage_name="Crazy", character_id="Crazy").load_history()["messages"]
                projector = HistoryController.__new__(HistoryController)
                projector._get_setting = settings.get
                restored = projector._sanitize_history_for_llm(SimpleNamespace(char_id="Crazy"), rows)
                assert restored == exchange
                next_response = model.generate([*messages, *restored, {"role": "user", "content": "Continue"}],
                    capabilities_override=caps, stream_event_callback=deltas.append if stream else None,
                    request_options_override={"max_attempts": 1, "retry_delay": 0})
                assert next_response.text == final_text
                assert len(wire_requests) == 5
                assert executions == [("calculator", {"expression": "1+1"})]
                replay = wire_requests[-1]["messages"]
                assert next(message for message in replay if message.get("tool_calls"))["tool_calls"][0]["id"] == "real-call"
                assert {"role": "tool", "tool_call_id": "real-call", "content": "2"} in replay
                assert "openai_responses" in restored[0]["protocol_history"]
            finally:
                connection.close()
    finally:
        model.close()
