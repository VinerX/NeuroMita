from __future__ import annotations

from copy import deepcopy

from ...base import LLMRequest
from ...structured_output import openai_response_format
from ...message_transforms import trailing_system_to_user_prefix
from ..history import normalize_history_message
from utils.openrouter_routing import annotate_openrouter_prompt_cache, normalize_openrouter_routing
from .tools import encode_tools


REASONING_EFFORT_LEVELS = ("low", "medium", "high")
_MESSAGE_KEYS = frozenset({"role", "content", "name", "tool_calls", "tool_call_id", "function_call",
                           "refusal", "audio", "extra_content"})


def apply_reasoning(payload: dict, req: LLMRequest) -> None:
    """Encode an explicitly configured reasoning control."""
    extra = req.extra or {}
    if "enable_thinking" not in extra:
        return

    enabled = bool(extra.get("enable_thinking"))
    try:
        budget = int(extra.get("thinking_budget") or extra.get("gemini_thinking_budget") or 0)
    except Exception:
        budget = 0

    transport = str((req.capabilities or {}).get("reasoning_control") or "")

    if transport == "openrouter":
        reasoning: dict = {"enabled": enabled}
        effort = str(extra.get("reasoning_effort") or "").strip().lower()
        model_profile = (req.capabilities or {}).get("model_profile") or {}
        thinking_profile = model_profile.get("thinking") if isinstance(model_profile, dict) else {}
        allowed_efforts = {
            str(value).strip().lower()
            for value in (thinking_profile.get("allowed_levels") or [])
            if str(value).strip()
        } if isinstance(thinking_profile, dict) else set()
        if enabled and effort and (not allowed_efforts or effort in allowed_efforts):
            reasoning["effort"] = effort
        elif enabled and budget > 0:
            reasoning["max_tokens"] = budget
        payload["reasoning"] = reasoning
    elif transport == "deepseek":
        thinking: dict = {"type": "enabled" if enabled else "disabled"}
        if enabled and budget > 0:
            thinking["budget_tokens"] = budget
        payload["thinking"] = thinking
    elif transport == "reasoning_effort":
        if not enabled:
            payload["reasoning_effort"] = "none"
        else:
            effort = str(extra.get("reasoning_effort") or "").strip().lower()
            if effort in REASONING_EFFORT_LEVELS:
                payload["reasoning_effort"] = effort



def generation_parameters(req: LLMRequest) -> dict:
    if req.native_parameters is not None:
        return deepcopy(req.native_parameters)
    extra = req.extra or {}
    parameters = {key: deepcopy(extra[key]) for key in (
        "temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"
    ) if key in extra}
    if "top_k" in extra and "deepseek" in (req.model or "").lower():
        parameters["top_k"] = extra["top_k"]
    if "logprobs" in extra:
        parameters["logprobs"] = bool(extra["logprobs"])
    apply_reasoning(parameters, req)
    return parameters


def encode_request(req: LLMRequest, *, wire_stream: bool, supports_stream_usage: bool = False) -> dict:
    messages = []
    for source in req.messages or []:
        if not isinstance(source, dict):
            continue
        message = normalize_history_message(source)
        wire_message = {key: value for key, value in message.items() if key in _MESSAGE_KEYS}
        history = (message.get('protocol_history') or {}).get('openai_chat_completions') or {}
        if message.get('role') == 'assistant' and history.get('tool_calls'):
            wire_message['tool_calls'] = history['tool_calls']
        messages.append(wire_message)
    if req.protocol_id == "openrouter_default":
        if (req.extra or {}).get("openrouter_tail_system_to_user", True):
            messages = trailing_system_to_user_prefix(messages, tag="[SYSTEM INFO]")
        messages = annotate_openrouter_prompt_cache(messages, req.model)
    payload = generation_parameters(req)
    payload.update(model=req.model, messages=messages, stream=bool(wire_stream))
    if req.protocol_id == "openrouter_default":
        routing = normalize_openrouter_routing((req.extra or {}).get("openrouter_routing"))
        if routing:
            payload["provider"] = routing
        session_id = str((req.extra or {}).get("openrouter_session_id") or "").strip()
        if session_id:
            payload["session_id"] = session_id
    caps = req.capabilities or {}
    stream_usage = caps.get("supports_stream_usage")
    if stream_usage is None:
        stream_usage = caps.get("stream_usage", supports_stream_usage)
    if wire_stream and stream_usage:
        payload["stream_options"] = {**(payload.get("stream_options") or {}), "include_usage": True}
    elif not wire_stream:
        payload.pop("stream_options", None)
    if caps.get("structured_output") and caps.get("native_structured_output", True):
        payload["response_format"] = openai_response_format(req)
    if req.tools_on and req.tools_mode == "native" and req.tools_payload:
        if not caps.get("tools_native", True):
            raise ValueError("Native tools are not supported by this endpoint.")
        payload["tools"] = encode_tools(req.tools_payload)
    return payload


def _next_response_format_fallback(payload: dict, error_message: str):
    """Return the next narrower response-format attempt for compatible APIs."""
    message = str(error_message or "").lower()
    explicit_format_error = any(
        signal in message
        for signal in (
            "response_format",
            "response_schema",
            "json_schema",
            "json_object",
        )
    )
    unsupported_terms = ("unsupported", "not supported", "does not support", "not allowed")
    schema_error = (
        any(signal in message for signal in ("schema", "properties", "structured"))
        and any(term in message for term in unsupported_terms)
    )
    generation_schema_error = (
        "generation_config" in message
        and any(signal in message for signal in ("schema", "properties"))
    )
    if not (explicit_format_error or schema_error or generation_schema_error):
        return None

    response_format = payload.get("response_format")
    if not isinstance(response_format, dict):
        return None
    mode = response_format.get("type")
    if mode == "json_schema":
        return {"type": "json_object"}
    if mode == "json_object":
        return {}
    if isinstance(response_format.get("json_schema"), dict):
        return {"type": "json_object"}
    return None


def fallback_payload(payload: dict, error_message: str) -> dict | None:
    """Return the next protocol payload for an explicit response-format rejection."""
    response_format = _next_response_format_fallback(payload, error_message)
    if response_format is None:
        return None
    result = deepcopy(payload)
    if response_format:
        result['response_format'] = response_format
    else:
        result.pop('response_format', None)
    return result
