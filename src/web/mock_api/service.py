from __future__ import annotations

from typing import Any, Optional


_DEFAULT_ERROR_SCENARIOS: dict[str, tuple[int, str]] = {
    "bad_request": (400, "Check API key and endpoint."),
    "unauthorized": (401, "Invalid API key."),
    "forbidden": (403, "Access forbidden. Check API key permissions."),
    "not_found": (404, "Endpoint not found."),
    "rate_limit": (429, "Rate limit exceeded."),
    "server_error": (500, "Temporary server error."),
}


def resolve_error_scenario(
    *,
    scenario: Optional[str],
    status_code: Optional[int],
    message: Optional[str],
) -> tuple[int, str]:
    normalized = str(scenario or "").strip().lower()
    if normalized in _DEFAULT_ERROR_SCENARIOS:
        default_status, default_message = _DEFAULT_ERROR_SCENARIOS[normalized]
        return int(status_code or default_status), str(message or default_message)

    if status_code is not None:
        fallback = message or f"Mock error for HTTP {status_code}."
        return int(status_code), str(fallback)

    return 200, str(message or "Mock response")


def build_openai_error_payload(
    *,
    status_code: int,
    message: str,
    error_code: Optional[str] = None,
    error_type: str = "mock_error",
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "code": error_code or str(status_code),
        }
    }


def build_openai_models_payload(models: Optional[list[str]] = None) -> dict[str, Any]:
    data = []
    for model in models or ["mock-gpt-4o-mini", "mock-deepseek-chat"]:
        data.append(
            {
                "id": model,
                "object": "model",
                "owned_by": "neuromita-mock",
            }
        )
    return {"object": "list", "data": data}


def build_openai_chat_payload(
    *,
    model: str,
    content: str,
    include_reasoning: bool = False,
    reasoning: Optional[str] = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
    }
    if include_reasoning and reasoning:
        message["reasoning_content"] = reasoning

    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1730000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }
