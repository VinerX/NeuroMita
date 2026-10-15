from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from ...structured_output import responses_text_format
from ..history import normalize_history_message
from .tools import encode_tools


@dataclass(frozen=True)
class ResponsesPolicy:
    namespace: str | None = None
    force_stream: bool = False
    allowed_parameters: tuple[str, ...] = (
        'reasoning', 'text', 'parallel_tool_calls', 'temperature', 'top_p',
        'max_output_tokens', 'tool_choice', 'truncation', 'include', 'metadata',
        'store', 'previous_response_id', 'instructions', 'user', 'service_tier',
        'max_tool_calls', 'prompt_cache_key', 'prompt_cache_retention', 'safety_identifier',
    )
    force_store_false: bool = False

    @classmethod
    def siwc(cls) -> 'ResponsesPolicy':
        return cls(namespace='neuromita', force_stream=True,
                   allowed_parameters=('reasoning', 'text', 'parallel_tool_calls'),
                   force_store_false=True)


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
        elif kind == 'image_url':
            image = part.get('image_url')
            image = image if isinstance(image, Mapping) else {'url': image}
            result.append({'type': 'input_image', 'image_url': image.get('url'), **({'detail': image['detail']} if image.get('detail') else {})})
        elif kind == 'input_image' or (kind == 'input_file' and role == 'user'):
            result.append(dict(part))
        elif kind == 'file' and role == 'user':
            result.append({'type': 'input_file', **dict(part.get('file') or {})})
        else:
            raise ValueError(f'Unsupported Responses content type: {kind}')
    return result


def _message_items(content: Any, role: str) -> list[dict[str, Any]]:
    encoded = _content(content, role)
    if not encoded:
        return []
    if isinstance(encoded, str):
        return [{'role': role, 'content': encoded}]
    items: list[dict[str, Any]] = []
    for part in encoded:
        part_role = 'user' if part['type'] == 'input_image' else role
        if not items or items[-1]['role'] != part_role:
            items.append({'role': part_role, 'content': []})
        items[-1]['content'].append(part)
    return items


def encode_request(req: Any, *, wire_stream: bool, policy: ResponsesPolicy) -> dict:
    items = []
    for source in req.messages or []:
        message = normalize_history_message(source)
        role = str(message.get('role') or 'user').lower()
        if role == 'tool':
            call_id = message.get('tool_call_id')
            if not call_id:
                raise ValueError('Tool result has no call ID')
            output = message.get('content')
            items.append({'type': 'function_call_output', 'call_id': call_id,
                          'output': output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)})
            continue
        if role == 'system':
            role = 'developer'
        if role not in {'developer', 'user', 'assistant'}:
            raise ValueError(f'Unsupported Responses role: {role}')
        history = (message.get('protocol_history') or {}).get('openai_responses') or {}
        if 'output' in history:
            raw_output = history['output']
            if role != 'assistant' or not isinstance(raw_output, list):
                raise ValueError('Invalid Responses output history')
            for item in raw_output:
                if not isinstance(item, Mapping) or item.get('type') not in {'reasoning', 'message', 'function_call'}:
                    raise ValueError('Unsupported Responses output history item')
                items.append(deepcopy(dict(item)))
            continue
        for reasoning in history.get('reasoning_items') or []:
            if role != 'assistant' or not isinstance(reasoning, Mapping) or reasoning.get('type') != 'reasoning':
                raise ValueError('Invalid Responses reasoning history item')
            items.append(deepcopy(dict(reasoning)))
        items.extend(_message_items(message.get('content'), role))
        for call in message.get('tool_calls') or []:
            function = call.get('function') or call
            call_id = call.get('id')
            if role != 'assistant' or not call_id or not function.get('name'):
                raise ValueError('Invalid function call history')
            arguments = function.get('arguments', '{}')
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            if not isinstance(arguments, str):
                raise ValueError('Function arguments must be JSON text or an object')
            name = function['name']
            if policy.namespace and not name.startswith(policy.namespace + '.'):
                name = policy.namespace + '.' + name
            items.append({'type': 'function_call', 'call_id': call_id,
                          'name': name, 'arguments': arguments})
    payload = {'model': str(req.model or '').strip(), 'input': items,
               'store': False, 'stream': bool(wire_stream or policy.force_stream)}
    parameters = req.native_parameters if req.native_parameters is not None else (req.extra or {})
    for name in policy.allowed_parameters:
        if name in parameters:
            payload[name] = deepcopy(parameters[name])
    if policy.force_store_false:
        payload['store'] = False
    if req.tools_on and getattr(req, 'tools_mode', 'native') == 'native':
        if (req.capabilities or {}).get('tools_native') is False:
            raise ValueError('Native tools are unsupported by this Responses endpoint')
        tools = encode_tools(req.tools_payload or [], namespace=policy.namespace)
        if tools:
            payload['tools'] = tools
            if policy.namespace:
                payload['parallel_tool_calls'] = False
    caps = req.capabilities or {}
    if caps.get('structured_output') and caps.get('native_structured_output', True):
        payload.setdefault('text', {})['format'] = responses_text_format(req)
    return payload
