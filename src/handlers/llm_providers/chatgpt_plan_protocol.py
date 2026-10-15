from __future__ import annotations

import json
from types import SimpleNamespace
from dataclasses import replace
from typing import Any, Mapping

from .protocols.responses import ResponsesAdapter, ResponsesPolicy
from .protocols.responses.response import normalize_responses_usage


def build_responses_payload(model: str, messages: list[dict[str, Any]], *,
                            parameters: Mapping[str, Any] | None = None,
                            tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    req = SimpleNamespace(model=model, messages=messages, native_parameters=parameters,
                          extra={}, tools_on=bool(tools), tools_payload=tools, capabilities={})
    policy = ResponsesPolicy.siwc()
    if not tools:
        policy = replace(policy, namespace=None)
    return ResponsesAdapter(policy=policy).encode(req, wire_stream=True)


class ResponsesInferenceAdapter(ResponsesAdapter):
    """Compatibility facade for the historical SIWC adapter API."""

    def __init__(self):
        super().__init__(policy=ResponsesPolicy.siwc())

    def build(self, req: Any) -> dict[str, Any]:
        return self.encode(req, wire_stream=True)

    def normalize_output(self, req: Any, response: Mapping[str, Any], text: str) -> str:
        calls = [item for item in response.get('output', []) if item.get('type') == 'function_call']
        if not calls:
            return text
        if len(calls) != 1:
            raise ValueError('The application supports one tool call per turn')
        call = calls[0]
        name = str(call.get('name') or '').removeprefix('neuromita.')
        advertised = {str((tool.get('function') or tool).get('name') or '')
                      for tool in (req.tools_payload or [])} if req.tools_on else set()
        if name not in advertised:
            raise ValueError('The model requested an unadvertised tool')
        arguments = json.loads(call.get('arguments') or '{}')
        if not isinstance(arguments, dict):
            raise ValueError('Function arguments must be an object')
        return json.dumps({'segments': [{'text': text}] if text else [],
                           'tool_call': {'name': name, 'args': arguments}}, ensure_ascii=False)


def parse_sse_data_line(line: str) -> dict[str, Any] | None:
    line = str(line or "").strip()
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


__all__ = ['ResponsesInferenceAdapter', 'build_responses_payload', 'normalize_responses_usage', 'parse_sse_data_line']
