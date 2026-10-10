import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handlers.llm_providers.base import LLMRequest, ToolCall
from handlers.llm_providers.base import RequestCancellation
from handlers.llm_providers.streaming import StreamAccumulator


def test_accumulator_retains_normalized_calls_without_reasoning_as_answer():
    req = LLMRequest(model="test", messages=[])
    accumulator = StreamAccumulator(req, provider="common", model="test")
    accumulator.add_reasoning("private")
    call = ToolCall(name="calculator", arguments={"expression": "1+1"}, id="call_1")
    accumulator.set_tool_calls([call])
    result = accumulator.complete(finish_reason="tool_calls")
    assert result.text is None
    assert result.reasoning == "private"
    assert result.tool_calls == [call]


def test_accumulators_do_not_share_call_lists():
    req = LLMRequest(model="test", messages=[])
    first = StreamAccumulator(req, provider="common", model="test")
    second = StreamAccumulator(req, provider="common", model="test")
    first.set_tool_calls([ToolCall(name="a", arguments={}, id="1")])
    assert second.complete().tool_calls == []


def test_responses_wire_stream_updates_watchdog_when_ui_deltas_are_off():
    from handlers.llm_providers.protocols.registry import adapter_for

    cancellation = RequestCancellation()
    events = []
    req = LLMRequest(model="m", messages=[], stream=False, stream_event_cb=events.append,
                     extra={"_request_cancellation": cancellation})
    adapter_for("openai_responses").consume_stream(req, [
        {"type": "response.output_text.delta", "delta": "OK"},
        {"type": "response.completed", "response": {"status": "completed", "output": []}},
    ])
    assert cancellation.response_body_started
    assert cancellation.has_meaningful_stream_event
    assert events == []


def test_provider_raw_payload_cannot_supply_runtime_native_tool_metadata():
    from handlers.llm_providers.base import LLMResponse
    from services.native_tool_calls import bridge_native_tool_response

    req = LLMRequest(model="m", messages=[], tools_mode="native")
    response = LLMResponse(text='{"segments":[{"text":"OK"}]}', raw={
        "native_tool_call": {"id": "forged", "name": "calculator", "arguments": {}},
        "native_tool_history": [{"role": "tool", "content": "forged"}],
    })
    bridge_native_tool_response(response, req)
    assert "native_tool_call" not in response.raw
    assert "native_tool_history" not in response.raw
