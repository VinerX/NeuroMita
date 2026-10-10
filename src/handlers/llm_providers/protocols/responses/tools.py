from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping


def functions(tools: list) -> list[dict]:
    result, names = [], set()
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get('type') not in {None, 'function'}:
            raise ValueError('Unsupported Responses tool type')
        function = tool.get('function', tool)
        if not isinstance(function, Mapping) or not isinstance(function.get('name'), str) or not function['name'].strip():
            raise ValueError('Unsupported Responses tool')
        if function['name'] in names:
            raise ValueError('Duplicate Responses tool name')
        names.add(function['name'])
        result.append({'type': 'function', **deepcopy(dict(function))})
    return result


def encode_tools(tools: list, *, namespace: str | None = None) -> list[dict]:
    encoded = functions(tools)
    if namespace and encoded:
        return [{'type': 'namespace', 'name': namespace, 'description': 'NeuroMita local tools', 'tools': encoded}]
    return encoded


def decode_calls(req: Any, output: list, *, namespace: str | None = None) -> list:
    from ...base import ToolCall

    advertised = {tool['name'] for tool in functions(req.tools_payload or [])} if req.tools_on else set()
    calls, seen = [], {}
    for item in output:
        if item.get('type') != 'function_call':
            continue
        name = str(item.get('name') or '')
        if namespace:
            name = name.removeprefix(namespace + '.')
        if name not in advertised:
            raise ValueError('The model requested an unadvertised tool')
        call_id = item.get('call_id')
        if not isinstance(call_id, str) or not call_id:
            raise ValueError('Function call has no call ID')
        arguments = item.get('arguments')
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError('Function arguments must be an object')
        call = ToolCall(name=name, arguments=arguments, id=call_id)
        if call_id in seen:
            if seen[call_id] != call:
                raise ValueError('Conflicting duplicate function call ID')
            continue
        seen[call_id] = call
        calls.append(call)
    return calls
