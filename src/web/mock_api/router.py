from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse

from web.mock_api.service import (
    build_openai_chat_payload,
    build_openai_error_payload,
    build_openai_models_payload,
    resolve_error_scenario,
)


router = APIRouter(prefix="/mock/openai/v1", tags=["Mock OpenAI API"])


@router.get(
    "",
    summary="Mock OpenAI API info",
    description="Lists available mock endpoints for testing OpenAI-compatible error handling.",
)
async def get_mock_info() -> dict[str, Any]:
    return {
        "name": "NeuroMita Mock OpenAI API",
        "chat_completions": "/mock/openai/v1/chat/completions",
        "models": "/mock/openai/v1/models",
        "examples": {
            "429": "/mock/openai/v1/chat/completions?scenario=rate_limit",
            "400": "/mock/openai/v1/chat/completions?status_code=400&message=Check%20API%20key%20and%20endpoint",
            "models_429": "/mock/openai/v1/models?scenario=rate_limit",
        },
    }


@router.get(
    "/models",
    summary="Mock models endpoint",
    description="Returns mock model list or a configured error status for connection testing.",
)
async def get_mock_models(
    scenario: Optional[str] = Query(default=None),
    status_code: Optional[int] = Query(default=None, ge=200, le=599),
    message: Optional[str] = Query(default=None),
    error_code: Optional[str] = Query(default=None),
) -> JSONResponse:
    resolved_status, resolved_message = resolve_error_scenario(
        scenario=scenario,
        status_code=status_code,
        message=message,
    )

    if resolved_status != status.HTTP_200_OK:
        return JSONResponse(
            status_code=resolved_status,
            content=build_openai_error_payload(
                status_code=resolved_status,
                message=resolved_message,
                error_code=error_code,
                error_type="mock_models_error",
            ),
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content=build_openai_models_payload())


@router.post(
    "/chat/completions",
    summary="Mock chat completions endpoint",
    description="Returns a successful OpenAI-compatible response or a configured HTTP error for UI testing.",
)
async def create_mock_chat_completion(
    payload: Optional[dict[str, Any]] = Body(default=None),
    scenario: Optional[str] = Query(default=None),
    status_code: Optional[int] = Query(default=None, ge=200, le=599),
    message: Optional[str] = Query(default=None),
    error_code: Optional[str] = Query(default=None),
    response_text: Optional[str] = Query(default=None),
    include_reasoning: bool = Query(default=False),
    reasoning_text: Optional[str] = Query(default=None),
) -> JSONResponse:
    resolved_status, resolved_message = resolve_error_scenario(
        scenario=scenario,
        status_code=status_code,
        message=message,
    )

    if resolved_status != status.HTTP_200_OK:
        return JSONResponse(
            status_code=resolved_status,
            content=build_openai_error_payload(
                status_code=resolved_status,
                message=resolved_message,
                error_code=error_code,
            ),
        )

    request_payload = payload or {}
    model = str(request_payload.get("model") or "mock-gpt-4o-mini")
    content = str(response_text or "This is a mock response from the NeuroMita test endpoint.")
    reasoning = reasoning_text or "Mock reasoning block"

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=build_openai_chat_payload(
            model=model,
            content=content,
            include_reasoning=include_reasoning,
            reasoning=reasoning,
        ),
    )
