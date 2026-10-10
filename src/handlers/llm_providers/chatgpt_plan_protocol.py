from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

from .structured_output import responses_text_format


def _content(content: Any, role: str) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if content is None:
        return ''
    if not isinstance(content, list):
        raise ValueError('Unsupported message content')
    result = []
    for part in content:
        if isinstance(part, str):
            part = {'type': 'text', 'text': part}
        kind = part.get('type') if isinstance(part, Mapping) else None
        if kind in {'text', 'input_text', 'output_text'}:
            result.append({'type': 'output_text' if role == 'assistant' else 'input_text', 'text': str(part.get('text') or '')})
        elif kind == 'image_url' and role == 'user':
            image = part.get('image_url')
            image = image if isinstance(image, Mapping) else {'url': image}
            result.append({'type': 'input_image', 'image_url': image.get('url'), **({'detail': image['detail']} if image.get('detail') else {})})
        elif kind in {'input_image', 'input_file'} and role == 'user':
            result.append(dict(part))
        elif kind == 'file' and role == 'user':
            result.append({'type': 'input_file', **dict(part.get('file') or {})})
        else:
            raise ValueError(f'Unsupported Responses content type: {kind}')
    return result


def build_responses_payload(model: str, messages: list[dict[str, Any]], *,
                            parameters: Mapping[str, Any] | None = None,
                            tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    for message in messages or []:
        role = str(message.get('role') or 'user').lower()
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if not call_id:
                raise ValueError('Tool result has no call ID')
            input_items.append({'type': 'function_call_output', 'call_id': call_id,
                                'output': str(message.get('content') or '')})
            continue
        if role == 'system':
            role = 'developer'
        if role not in {'developer', 'user', 'assistant'}:
            raise ValueError(f'Unsupported Responses role: {role}')
        content = _content(message.get('content'), role)
        if content:
            input_items.append({'role': role, 'content': content})
        for call in message.get('tool_calls') or []:
            function = call.get('function') or {}
            if not call.get('id') or not function.get('name'):
                raise ValueError('Invalid function call history')
            input_items.append({'type': 'function_call', 'call_id': call['id'],
                                'name': function['name'], 'arguments': function.get('arguments') or '{}'})
    payload: dict[str, Any] = {'model': str(model or '').strip(), 'input': input_items,
                               'store': False, 'stream': True}
    for name in ('reasoning', 'text', 'parallel_tool_calls'):
        if parameters and name in parameters:
            payload[name] = deepcopy(parameters[name])
    if tools:
        functions = []
        for tool in tools:
            if tool.get('type') not in {None, 'function'}:
                raise ValueError('Unsupported Responses tool type')
            function = tool.get('function') if tool.get('type') == 'function' else tool
            if not isinstance(function, Mapping) or not function.get('name'):
                raise ValueError('Unsupported Responses tool')
            functions.append({'type': 'function', **dict(function)})
        payload['tools'] = [{'type': 'namespace', 'name': 'neuromita',
                             'description': 'NeuroMita local tools', 'tools': functions}]
        payload['parallel_tool_calls'] = False
    return payload


class ResponsesInferenceAdapter:
    def build(self, req: Any) -> dict[str, Any]:
        payload = build_responses_payload(req.model, req.messages,
            parameters=req.native_parameters or req.extra,
            tools=req.tools_payload if req.tools_on else None)
        caps = req.capabilities or {}
        if caps.get('structured_output') and caps.get('native_structured_output', True):
            payload.setdefault('text', {})['format'] = responses_text_format(req)
        return payload

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


def normalize_responses_usage(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    input_details = payload.get("input_tokens_details")
    output_details = payload.get("output_tokens_details")
    input_details = input_details if isinstance(input_details, Mapping) else {}
    output_details = output_details if isinstance(output_details, Mapping) else {}
    return {
        "prompt_tokens": int(payload.get("input_tokens") or 0),
        "completion_tokens": int(payload.get("output_tokens") or 0),
        "total_tokens": int(payload.get("total_tokens") or 0),
        "cached_prompt_tokens": int(input_details.get("cached_tokens") or 0),
        "cache_write_tokens": int(input_details.get("cache_write_tokens") or 0),
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        "raw": dict(payload),
    }


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


__all__ = ["ResponsesInferenceAdapter", "build_responses_payload", "normalize_responses_usage", "parse_sse_data_line"]
