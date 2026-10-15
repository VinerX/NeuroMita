from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field

from ...base import ToolCall


def encode_tools(declarations: list[dict]) -> list[dict]:
    result = []
    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise ValueError("Tool declaration must be an object.")
        if isinstance(declaration.get("function"), dict):
            result.append(deepcopy(declaration))
        elif declaration.get("name"):
            function = {key: deepcopy(value) for key, value in declaration.items() if key != "type"}
            result.append({"type": "function", "function": function})
        else:
            raise ValueError("Tool declaration has no function name.")
    return result


def parse_tool_call(function: dict, call_id: str = "") -> ToolCall:
    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Provider tool call has no function name.")
    arguments = function.get("arguments")
    if arguments in (None, ""):
        arguments = {}
    elif isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("Provider tool arguments must be a JSON object.")
    return ToolCall(name=name, arguments=arguments, id=str(call_id or ""))


def decode_tool_calls(message: dict) -> list[ToolCall]:
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list):
        raise ValueError("Provider tool_calls must be an array.")
    result = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise ValueError("Invalid provider function tool call.")
        if call.get("type", "function") != "function":
            raise ValueError("Unsupported provider tool call type.")
        result.append(parse_tool_call(call["function"], call.get("id", "")))
    if not result and message.get("function_call"):
        result.append(parse_tool_call(message["function_call"]))
    return result


@dataclass
class ToolDelta:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)
    started: bool = False
    extensions: dict = field(default_factory=dict)
    function_extensions: dict = field(default_factory=dict)


def _merge_extensions(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_extensions(target[key], value)
        else:
            target[key] = deepcopy(value)


class ToolCallAccumulator:
    def __init__(self, accumulator) -> None:
        self.accumulator = accumulator
        self.calls: dict[int, ToolDelta] = {}

    def add(self, delta: dict) -> None:
        if not isinstance(delta, dict) or delta.get("type", "function") != "function":
            raise ValueError("Invalid provider tool delta.")
        index = int(delta.get("index") or 0)
        state = self.calls.setdefault(index, ToolDelta())
        state.id = str(delta.get("id") or state.id)
        function = delta.get("function") or {}
        if not isinstance(function, dict):
            raise ValueError("Invalid provider tool function delta.")
        _merge_extensions(state.extensions, {key: value for key, value in delta.items()
                                              if key not in {"id", "index", "type", "function"}})
        _merge_extensions(state.function_extensions, {key: value for key, value in function.items()
                                                       if key not in {"name", "arguments"}})
        state.name += str(function.get("name") or "")
        if not state.started and (state.id or state.name):
            self.accumulator.tool_call_started(tool_call_id=state.id, tool_name=state.name)
            state.started = True
        arguments = function.get("arguments") or ""
        if not isinstance(arguments, str):
            raise ValueError("Provider tool argument delta must be a string.")
        if arguments:
            state.arguments.append(arguments)
            self.accumulator.tool_call_delta(tool_call_id=state.id, tool_name=state.name,
                                             arguments_delta=arguments)

    def complete(self) -> list[ToolCall]:
        calls = [parse_tool_call({"name": state.name, "arguments": "".join(state.arguments)}, state.id)
                 for _, state in sorted(self.calls.items())]
        self.accumulator.set_tool_calls(calls)
        for call in calls:
            self.accumulator.tool_call_completed(tool_call_id=call.id, tool_name=call.name)
        return calls

    def raw_calls(self) -> list[dict]:
        return [{**deepcopy(state.extensions), "id": state.id, "type": "function",
                 "function": {**deepcopy(state.function_extensions), "name": state.name,
                              "arguments": "".join(state.arguments) or "{}"}}
                for _, state in sorted(self.calls.items())]
