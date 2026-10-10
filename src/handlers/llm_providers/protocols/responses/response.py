from __future__ import annotations

from typing import Any, Mapping
from copy import deepcopy

from ...base import LLMResponse, LLMUsage
from ...errors import LLMProviderError
from .tools import decode_calls


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


def response_error(req: Any, payload: Mapping, *, code: str, phase: str = 'response') -> LLMProviderError:
    error = payload.get('error') or {}
    if not isinstance(error, Mapping):
        error = {}
    code = str(error.get('code') or code)
    incomplete = payload.get('incomplete_details')
    incomplete = incomplete if isinstance(incomplete, Mapping) else {}
    details = error.get('message') or incomplete.get('reason') or code
    return LLMProviderError(provider=req.provider_name or 'responses',
                            friendly_message='Responses API could not complete the response.',
                            provider_message=str(details), raw_payload=dict(payload), code=code,
                            retryable=False, phase=phase, url=req.api_url)


def decode_response(req: Any, payload: Mapping, *, namespace: str | None = None) -> LLMResponse:
    if not isinstance(payload, Mapping):
        raise ValueError('Responses payload must be an object')
    status = payload.get('status')
    if payload.get('error') or status in {'failed', 'incomplete', 'cancelled'}:
        raise response_error(req, payload, code=f'responses.{status or "failed"}')
    if status and status != 'completed':
        raise response_error(req, payload, code='responses.nonterminal_response')
    text, reasoning = [], []
    output = payload.get('output') or []
    if not isinstance(output, list):
        raise ValueError('Responses output must be an array')
    for item in output:
        if not isinstance(item, Mapping):
            raise ValueError('Responses output item must be an object')
        if item.get('status') in {'failed', 'incomplete'}:
            raise response_error(req, payload, code='responses.incomplete_item')
        if item.get('type') == 'message':
            for part in item.get('content') or []:
                if not isinstance(part, Mapping):
                    raise ValueError('Responses content part must be an object')
                if part.get('type') == 'refusal':
                    raise response_error(req, {'error': {'message': part.get('refusal')}}, code='responses.refusal')
                if part.get('type') == 'output_text':
                    text.append(str(part.get('text') or ''))
        elif item.get('type') == 'reasoning':
            for part in (item.get('summary') or []) + (item.get('content') or []):
                if part.get('type') in {'summary_text', 'reasoning_text', 'text'}:
                    reasoning.append(str(part.get('text') or ''))
        elif item.get('type') not in {'function_call'}:
            raise ValueError(f'Unsupported Responses output item: {item.get("type")}')
    usage = normalize_responses_usage(payload.get('usage'))
    return LLMResponse(text=''.join(text), reasoning=''.join(reasoning) or None,
                       tool_calls=decode_calls(req, output, namespace=namespace),
                       usage=LLMUsage(**usage) if usage else None,
                       model=str(payload.get('model') or req.model),
                       provider_name=req.provider_name or 'responses',
                       provider_display_name=req.provider_display_name,
                       finish_reason='completed', raw=dict(payload),
                       protocol_history={'openai_responses': {'output': deepcopy(output)}})
