# src/handlers/llm_providers/base.py
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Callable, Optional, Any, Mapping
from abc import ABC, abstractmethod

from main_logger import logger

from .errors import LLMProviderError


class StreamChannel(str, Enum):
    """Канал стрим-чанка.

    Провайдер обязан различать текст ответа и размышления модели: разные
    модели отдают мысли по-разному (reasoning_content, thought-части Gemini,
    <think>-теги внутри content), но выше по стеку это один контракт.
    """

    CONTENT = "content"
    REASONING = "reasoning"


# Второй аргумент всегда передаётся явно — молчаливого дефолта нет, иначе
# мысли снова утекут в текст ответа.
StreamCallback = Callable[[str, StreamChannel], None]


def resolve_content_and_reasoning(
    content: str, reasoning: str, *, provider_name: str = ""
) -> tuple[str, str]:
    """Развести текст ответа и размышления.

    Норма: content — ответ, reasoning — мысли, и они не смешиваются.
    Аварийный случай (часть сборок Qwen3): модель кладёт весь ответ в
    reasoning-канал, оставляя content пустым — тогда мысли и есть ответ,
    иначе пользователь получит пустоту.
    """
    if content:
        return content, reasoning
    if reasoning:
        logger.warning(
            f"[{provider_name or '?'}] Empty content with non-empty reasoning — "
            f"using reasoning as the answer (model ignores the content channel)."
        )
        return reasoning, ""
    return "", ""


from .request_lifecycle import (
    RequestCancellation,
    RequestCancelledError,
    check_request_cancelled,
    get_request_cancellation,
    record_response_body_started,
    record_response_headers_received,
    register_cancellable_resource,
    resolve_total_timeout,
)


@dataclass
class LLMRequest:
    model: str
    messages: List[Dict]

    api_key: Optional[str] = None
    api_url: Optional[str] = None

    # protocol-driven routing
    protocol_id: Optional[str] = None
    dialect_id: Optional[str] = None
    provider_name: Optional[str] = None

    headers: Dict[str, str] = field(default_factory=dict)
    transforms: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)

    stream: bool = False
    stream_cb: Optional[StreamCallback] = None
    stream_event_cb: Optional[Callable[[Any], None]] = None

    tools_on: bool = False
    tools_mode: str = "native"

    tools_payload: Optional[Any] = None
    tools_dialect: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)
    settings: Optional[Any] = None
    depth: int = 0
    tool_manager: Optional[Any] = None

    structured_model: Optional[Any] = None


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    reasoning_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_write_tokens: int = 0

    cost: Optional[float] = None
    cost_currency: Optional[str] = None
    cost_source: Optional[str] = None

    raw: Dict[str, Any] = field(default_factory=dict)

    def merged_with(self, other: Optional["LLMUsage"]) -> "LLMUsage":
        if other is None:
            return self

        merged = LLMUsage(
            prompt_tokens=int(self.prompt_tokens or 0) + int(other.prompt_tokens or 0),
            completion_tokens=int(self.completion_tokens or 0) + int(other.completion_tokens or 0),
            total_tokens=int(self.total_tokens or 0) + int(other.total_tokens or 0),
            reasoning_tokens=int(self.reasoning_tokens or 0) + int(other.reasoning_tokens or 0),
            cached_prompt_tokens=int(self.cached_prompt_tokens or 0) + int(other.cached_prompt_tokens or 0),
            cache_write_tokens=int(self.cache_write_tokens or 0) + int(other.cache_write_tokens or 0),
            raw={**(self.raw or {}), **(other.raw or {})},
        )

        if self.cost is not None and other.cost is not None:
            if (self.cost_currency or "") == (other.cost_currency or ""):
                merged.cost = float(self.cost) + float(other.cost)
                merged.cost_currency = self.cost_currency or other.cost_currency
                merged.cost_source = self.cost_source or other.cost_source
            else:
                merged.cost = None
                merged.cost_currency = None
                merged.cost_source = None
        else:
            merged.cost = self.cost if self.cost is not None else other.cost
            merged.cost_currency = self.cost_currency or other.cost_currency
            merged.cost_source = self.cost_source or other.cost_source

        return merged


@dataclass
class LLMResponse:
    text: Optional[str]
    usage: Optional[LLMUsage] = None
    model: Optional[str] = None
    provider_name: Optional[str] = None
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    # Размышления, которые провайдер отдал отдельным каналом. В text их быть
    # не должно: text — только то, что видит игрок.
    reasoning: Optional[str] = None


def _to_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except Exception:
        return 0


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def normalize_usage_payload(
    payload: Optional[Mapping[str, Any]],
    *,
    cost_currency: Optional[str] = None,
    cost_source: Optional[str] = None,
) -> Optional[LLMUsage]:
    if not isinstance(payload, Mapping):
        return None

    prompt_details = payload.get("prompt_tokens_details")
    if not isinstance(prompt_details, Mapping):
        prompt_details = {}

    completion_details = payload.get("completion_tokens_details")
    if not isinstance(completion_details, Mapping):
        completion_details = {}

    usage = LLMUsage(
        prompt_tokens=_to_int(payload.get("prompt_tokens")),
        completion_tokens=_to_int(payload.get("completion_tokens")),
        total_tokens=_to_int(payload.get("total_tokens")),
        reasoning_tokens=_to_int(completion_details.get("reasoning_tokens")),
        cached_prompt_tokens=_to_int(prompt_details.get("cached_tokens")),
        cache_write_tokens=_to_int(prompt_details.get("cache_write_tokens")),
        cost=_to_float(payload.get("cost")),
        cost_currency=cost_currency if payload.get("cost") is not None else None,
        cost_source=cost_source if payload.get("cost") is not None else None,
        raw=dict(payload),
    )

    if usage.total_tokens <= 0:
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

    if (
        usage.prompt_tokens <= 0
        and usage.completion_tokens <= 0
        and usage.total_tokens <= 0
        and usage.cost is None
    ):
        return None

    return usage


class BaseProvider(ABC):
    name: str
    priority: int = 100

    supports_tools_native: bool = False
    supports_streaming: bool = True
    supports_streaming_with_tools: bool = False
    supports_stream_usage: bool = False
    uses_custom_messages_handler: bool = False

    def __init__(self, *, http_transport: Any = None) -> None:
        if http_transport is None:
            from .http_transport import LLMHttpTransport

            http_transport = LLMHttpTransport()
            self._owns_http_transport = True
        else:
            self._owns_http_transport = False
        self.http_transport = http_transport

    @abstractmethod
    def is_applicable(self, req: LLMRequest) -> bool:
        pass

    @abstractmethod
    def generate(self, req: LLMRequest) -> LLMResponse:
        pass

    def _resolve_content_and_reasoning(self, content: str, reasoning: str) -> tuple[str, str]:
        return resolve_content_and_reasoning(
            content, reasoning, provider_name=getattr(self, "name", "")
        )

    def should_request_stream_usage(self, req: LLMRequest) -> bool:
        capabilities = req.capabilities or {}
        capability = capabilities.get("supports_stream_usage")
        if capability is None:
            capability = capabilities.get("stream_usage")
        if capability is not None:
            return bool(capability)
        return bool(self.supports_stream_usage)

    def close(self) -> None:
        if self._owns_http_transport:
            self.http_transport.close()


__all__ = [
    "LLMRequest",
    "LLMUsage",
    "LLMResponse",
    "BaseProvider",
    "RequestCancellation",
    "RequestCancelledError",
    "StreamCallback",
    "StreamChannel",
    "check_request_cancelled",
    "get_request_cancellation",
    "record_response_body_started",
    "record_response_headers_received",
    "register_cancellable_resource",
    "resolve_total_timeout",
    "normalize_usage_payload",
    "LLMProviderError",
]
