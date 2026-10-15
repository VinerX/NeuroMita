from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from ...base import LLMRequest, LLMResponse, check_request_cancelled
from ...errors import build_stream_error
from ...streaming import StreamAccumulator
from .response import content_text, extract_usage, history_for_message, reasoning_text, terminal_error
from .tools import ToolCallAccumulator


def consume_stream(req: LLMRequest, chunks: Iterable[dict], *, provider: str = "") -> LLMResponse:
    provider = provider or req.provider_name or "chat_completions"
    event_request = req
    if not req.stream:
        event_request = replace(req, stream_cb=None, stream_event_cb=None,
                                extra={key: value for key, value in req.extra.items()
                                       if key != "_stream_event_channel"})
    accumulator = StreamAccumulator(event_request, provider=provider, model=req.model)
    tools = ToolCallAccumulator(accumulator)
    finish = None
    response_model = None
    for payload in chunks:
        check_request_cancelled(req)
        if not isinstance(payload, dict):
            raise build_stream_error(provider, payload=payload, code="stream.invalid_payload",
                                     provider_message="Provider stream chunk is not an object.", url=req.api_url)
        if payload.get("error"):
            raise build_stream_error(provider, payload=payload, url=req.api_url)
        response_model = response_model or payload.get("model")
        accumulator.set_usage(extract_usage(req, payload))
        try:
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            finish = choice.get("finish_reason") or finish
            failure = terminal_error(finish, delta.get("refusal"))
            if failure:
                raise build_stream_error(provider, payload=payload, provider_message=failure,
                                         code="stream.terminal_failure", url=req.api_url)
            accumulator.add_text(content_text(delta.get("content")))
            accumulator.add_reasoning(reasoning_text(delta))
            for tool in delta.get("tool_calls") or []:
                tools.add(tool)
            if delta.get("function_call"):
                tools.add({"index": 0, "function": delta["function_call"]})
        except (TypeError, ValueError, AttributeError) as exc:
            raise build_stream_error(provider, payload=payload, provider_message=str(exc),
                                     code="stream.invalid_payload", url=req.api_url) from exc
    check_request_cancelled(req)
    if finish is None and (tools.calls or accumulator.text_parts or accumulator.reasoning_parts):
        raise build_stream_error(provider, provider_message="Provider stream ended before a terminal finish reason.",
                                 code="stream.incomplete", url=req.api_url)
    try:
        tools.complete()
    except (TypeError, ValueError) as exc:
        raise build_stream_error(provider, provider_message=str(exc), code="stream.invalid_tool_call",
                                 url=req.api_url) from exc
    response = accumulator.complete(finish_reason=finish, model=response_model)
    message = {"role": "assistant", "content": "".join(accumulator.text_parts) or None}
    if tools.calls:
        message["tool_calls"] = tools.raw_calls()
    if accumulator.reasoning_parts:
        message["reasoning_content"] = "".join(accumulator.reasoning_parts)
    response.raw = {"model": response.model,
                    "choices": [{"message": message, "finish_reason": finish}]}
    response.protocol_history = history_for_message(message)
    if response.usage is not None:
        response.raw["usage"] = dict(response.usage.raw)
    if not response.text and not response.tool_calls:
        response.error_message = "Provider stream ended without content or tool calls."
    return response
