from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from ...base import LLMRequest, LLMResponse, normalize_usage_payload, resolve_content_and_reasoning
from ...errors import build_provider_error
from .tools import decode_tool_calls




def content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if not isinstance(part, dict) or part.get("type") not in ("text", "output_text"):
                raise ValueError("Unsupported provider completion content part.")
            text = part.get("text")
            if not isinstance(text, str):
                raise ValueError("Provider completion text part must contain a string.")
            parts.append(text)
        return "".join(parts)
    raise ValueError("Provider completion content must be text or text parts.")


def history_for_message(message: dict) -> dict:
    calls = deepcopy(message.get('tool_calls') or [])
    for call in calls:
        call.pop('index', None)
    return {'openai_chat_completions': {'tool_calls': calls}} if calls else {}


def reasoning_text(message: dict) -> str:
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    details = message.get("reasoning_details") or []
    return "".join(item["text"] for item in details
                   if isinstance(item, dict) and isinstance(item.get("text"), str))


def extract_usage(req: LLMRequest, payload: dict):
    usage = payload.get("usage")
    is_openrouter = urlsplit(str(req.api_url or "")).hostname == "openrouter.ai"
    return normalize_usage_payload(
        usage, cost_currency="credits" if is_openrouter else None,
        cost_source="provider_usage" if isinstance(usage, dict) and usage.get("cost") is not None else None,
    )


def terminal_error(finish_reason: str | None, refusal: Any = None) -> str | None:
    if refusal:
        return f"Provider refused the request: {refusal}"
    if finish_reason in {"length", "content_filter", "error", "failed", "cancelled", "incomplete"}:
        return f"Provider completion failed or was incomplete (finish_reason={finish_reason})."
    return None


def decode_response(req: LLMRequest, payload: dict, *, provider: str = "") -> LLMResponse:
    provider = provider or req.provider_name or "chat_completions"
    if not isinstance(payload, dict):
        raise build_provider_error(provider, provider_message="Provider completion is not an object.", url=req.api_url)
    if payload.get("error"):
        error = payload["error"]
        try:
            status = int(error.get("code")) if isinstance(error, dict) else None
        except (TypeError, ValueError):
            status = None
        raise build_provider_error(provider, payload=payload, status_code=status, url=req.api_url)
    try:
        choices = payload.get("choices") or []
        if not isinstance(choices, list):
            raise ValueError("Provider completion choices must be an array.")
        choice = choices[0] if choices else {}
        if not isinstance(choice, dict):
            raise ValueError("Provider completion choice must be an object.")
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            raise ValueError("Provider completion message must be an object.")
        finish = choice.get("finish_reason")
        error = terminal_error(finish, message.get("refusal"))
        calls = [] if error else decode_tool_calls(message)
        text = content_text(message.get("content"))
        reasoning = reasoning_text(message)
    except (TypeError, ValueError, AttributeError) as exc:
        raise build_provider_error(provider, payload=payload, provider_message=str(exc),
                                   code="completion.invalid_payload", url=req.api_url) from exc
    if not calls and not error:
        text, reasoning = resolve_content_and_reasoning(text, reasoning, provider_name=provider)
    text, reasoning = text.strip(), reasoning.strip()
    if not text and not calls and not error:
        error = "Provider returned no completion choices." if not choices else "Provider returned empty message content."
    return LLMResponse(text=text or None, reasoning=reasoning or None, tool_calls=calls,
                       usage=extract_usage(req, payload), model=payload.get("model") or req.model,
                       provider_name=req.provider_name or provider,
                       provider_display_name=req.provider_display_name or req.provider_name or provider,
                       finish_reason=finish, error_message=error, raw=payload,
                       protocol_history=history_for_message(message) if not error else {})
