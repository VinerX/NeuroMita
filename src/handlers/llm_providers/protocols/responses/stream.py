from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import Iterable

from ...base import check_request_cancelled, record_response_body_started
from ...streaming import StreamAccumulator
from ...errors import LLMProviderError
from .response import decode_response, response_error


def iter_responses_events(data: Iterable[str]) -> Iterable[dict]:
    for raw in data:
        if raw.strip() == '[DONE]':
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Responses SSE data must be an object')
        yield value


def consume_response_stream(req, chunks: Iterable[dict], *, namespace: str | None = None):
    event_request = req
    if not req.stream:
        event_request = replace(req, stream_cb=None, stream_event_cb=None,
                                extra={key: value for key, value in req.extra.items()
                                       if key != '_stream_event_channel'})
    accumulator = StreamAccumulator(event_request, provider=req.provider_name or 'responses', model=req.model)
    items: dict[str, dict] = {}
    indices: dict[int, str] = {}
    started: set[str] = set()
    completed: set[str] = set()
    pending: dict[str, list[str]] = {}
    text_parts, reasoning_parts = [], []
    text_done: dict[tuple, str] = {}
    reasoning_done: dict[tuple, str] = {}

    def error(payload, code):
        return response_error(req, payload, code=code, phase='stream')

    def name(item):
        value = str(item.get('name') or '')
        return value.removeprefix(namespace + '.') if namespace else value

    def remember(item, index=None):
        key = item.get('id') or item.get('call_id')
        if not key:
            if index is None:
                raise error(item, 'responses.missing_item_id')
            key = f'index:{index}'
        previous_key = indices.get(index) if index is not None else None
        if previous_key and previous_key != key:
            if previous_key.startswith('index:'):
                items[key] = items.pop(previous_key)
            else:
                raise error(item, 'responses.conflicting_item_id')
        state = items.setdefault(key, {})
        old_call_id = state.get('call_id')
        if old_call_id and item.get('call_id') and old_call_id != item['call_id']:
            raise error(item, 'responses.conflicting_call_id')
        state.update(deepcopy(item))
        if index is not None:
            indices[index] = key
        if state.get('type') == 'function_call':
            cid = state.get('call_id')
            if not cid:
                raise error(item, 'responses.missing_call_id')
            if cid not in started:
                record_response_body_started(req)
                if accumulator:
                    accumulator.tool_call_started(tool_call_id=cid, tool_name=name(state))
                started.add(cid)
            authoritative_arguments = state.get('arguments')
            for delta in pending.pop(key, []):
                append_arguments(state, delta)
            if authoritative_arguments:
                state['arguments'] = authoritative_arguments
        return state

    def append_arguments(state, delta):
        state['arguments'] = str(state.get('arguments') or '') + delta
        record_response_body_started(req)
        if accumulator:
            accumulator.tool_call_delta(tool_call_id=state['call_id'], tool_name=name(state), arguments_delta=delta)

    def find_item(event):
        key = event.get('item_id') or indices.get(event.get('output_index'))
        state = items.get(key)
        if state and state.get('type') != 'function_call':
            raise error(event, 'responses.arguments_for_nonfunction')
        return key, state

    for event in chunks:
        check_request_cancelled(req)
        kind = str(event.get('type') or '')
        if kind in {'error', 'response.failed', 'response.incomplete'}:
            source = event if kind == 'error' else event.get('response') or {}
            if kind == 'error' and not isinstance(source.get('error'), dict):
                source = {'error': source}
            exc = error(source, 'responses.' + kind.removeprefix('response.'))
            exc.raw_payload = event if kind == 'error' else source
            raise exc
        part = event.get('part') or {}
        if kind in {'response.content_part.added', 'response.content_part.done'} and part.get('type') == 'refusal':
            record_response_body_started(req)
            raise error({'error': {'message': part.get('refusal')}}, 'responses.refusal')
        if kind in {'response.refusal.delta', 'response.refusal.done'}:
            record_response_body_started(req)
            raise error({'error': {'message': event.get('delta') or event.get('refusal')}}, 'responses.refusal')
        if kind == 'response.output_text.delta':
            delta = str(event.get('delta') or '')
            if delta:
                record_response_body_started(req)
                text_parts.append(delta)
                if accumulator:
                    accumulator.add_text(delta)
        elif kind in {'response.reasoning_summary_text.delta', 'response.reasoning_text.delta'}:
            delta = str(event.get('delta') or '')
            if delta:
                record_response_body_started(req)
                reasoning_parts.append(delta)
                if accumulator:
                    accumulator.add_reasoning(delta)
        elif kind in {'response.output_text.done', 'response.reasoning_summary_text.done', 'response.reasoning_text.done'}:
            key = (event.get('item_id'), event.get('content_index'), event.get('summary_index'))
            (text_done if kind == 'response.output_text.done' else reasoning_done)[key] = str(event.get('text') or '')
            if event.get('text'):
                record_response_body_started(req)
        elif kind in {'response.output_item.added', 'response.output_item.done'}:
            item = event.get('item') or {}
            if item.get('type') == 'message':
                for part in item.get('content') or []:
                    if part.get('type') == 'refusal':
                        record_response_body_started(req)
                        raise error({'error': {'message': part.get('refusal')}}, 'responses.refusal')
            remember(item, event.get('output_index'))
            if kind == 'response.output_item.done' and (item.get('content') or item.get('summary') or item.get('encrypted_content')):
                record_response_body_started(req)
        elif kind == 'response.function_call_arguments.delta':
            key, state = find_item(event)
            if not key:
                raise error(event, 'responses.missing_item_id')
            delta = str(event.get('delta') or '')
            if delta:
                record_response_body_started(req)
            if state:
                append_arguments(state, delta)
            else:
                pending.setdefault(key, []).append(delta)
        elif kind == 'response.function_call_arguments.done':
            key, state = find_item(event)
            if state is None:
                if not event.get('name') or not event.get('call_id'):
                    raise error(event, 'responses.orphan_arguments')
                state = remember({'type': 'function_call', 'id': key, 'call_id': event['call_id'], 'name': event['name']})
            state['arguments'] = event.get('arguments', state.get('arguments'))
        elif kind == 'response.completed':
            payload = deepcopy(event.get('response') or {})
            final_output = payload.get('output') or []
            for index, item in enumerate(final_output):
                remember(item, None if item.get('id') or item.get('call_id') else f'final:{index}')
            if pending:
                raise error(event, 'responses.orphan_arguments')
            final_calls = {item.get('call_id') for item in final_output if item.get('type') == 'function_call'}
            final_reasoning = {item.get('id') for item in final_output if item.get('type') == 'reasoning'}
            merged = list(final_output)
            for item in items.values():
                if item.get('type') == 'function_call' and item.get('call_id') not in final_calls:
                    merged.append(item)
                    final_calls.add(item.get('call_id'))
                elif item.get('type') == 'reasoning' and item.get('id') not in final_reasoning:
                    merged.append(item)
                    final_reasoning.add(item.get('id'))
                elif not final_output and item.get('type') not in {'function_call', 'reasoning'}:
                    merged.append(item)
            payload['output'] = merged
            try:
                result = decode_response(req, payload, namespace=namespace)
            except LLMProviderError as exc:
                exc.phase = 'stream'
                raise
            if not any(part.get('type') == 'output_text' for item in merged
                       if item.get('type') == 'message' for part in item.get('content') or []):
                result.text = ''.join(text_done.values()) if text_done else ''.join(text_parts)
            if not result.reasoning:
                result.reasoning = (''.join(reasoning_done.values()) if reasoning_done else ''.join(reasoning_parts)) or None
            record_response_body_started(req)
            if accumulator:
                if result.text and not text_parts:
                    accumulator.add_text(result.text)
                if result.reasoning and not reasoning_parts:
                    accumulator.add_reasoning(result.reasoning)
                accumulator.set_usage(result.usage)
                accumulator.set_tool_calls(result.tool_calls)
                for call in result.tool_calls:
                    if call.id not in completed:
                        accumulator.tool_call_completed(tool_call_id=call.id, tool_name=call.name)
                        completed.add(call.id)
            return result
    check_request_cancelled(req)
    raise error({}, 'responses.stream_interrupted')
