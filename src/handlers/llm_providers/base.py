# src/handlers/llm_providers/base.py
from dataclasses import dataclass, field
import threading
from typing import List, Dict, Callable, Optional, Any, Mapping
from abc import ABC, abstractmethod

from .errors import LLMProviderError


class RequestCancelledError(TimeoutError):
    pass


class RequestCancellation:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def add_cancel_callback(self, callback: Callable[[], None]) -> None:
        call_now = False
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                self._callbacks.append(callback)
        if call_now:
            try:
                callback()
            except Exception:
                pass

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise RequestCancelledError("LLM request was cancelled")


def get_request_cancellation(req: "LLMRequest") -> Optional[RequestCancellation]:
    extra = req.extra or {}
    token = extra.get("_request_cancellation")
    return token if isinstance(token, RequestCancellation) else None


def check_request_cancelled(req: "LLMRequest") -> None:
    token = get_request_cancellation(req)
    if token is not None:
        token.raise_if_cancelled()


def register_cancellable_resource(req: "LLMRequest", resource: Any) -> Any:
    token = get_request_cancellation(req)
    close = getattr(resource, "close", None)
    if token is not None and callable(close):
        token.add_cancel_callback(close)
    return resource


def resolve_requests_timeout(
    req: "LLMRequest",
    *,
    default_total: float = 240.0,
) -> tuple[float, float]:
    extra = req.extra or {}

    try:
        total = max(
            1.0,
            float(extra.get("http_timeout_seconds") or default_total),
        )
    except (TypeError, ValueError):
        total = max(1.0, float(default_total))

    try:
        connect = max(
            1.0,
            float(extra.get("http_connect_timeout_seconds") or min(15.0, total)),
        )
    except (TypeError, ValueError):
        connect = min(15.0, total)

    try:
        read = max(
            1.0,
            float(extra.get("http_read_timeout_seconds") or total),
        )
    except (TypeError, ValueError):
        read = total

    return connect, read


def resolve_total_timeout(
    req: "LLMRequest",
    *,
    default_total: float = 240.0,
) -> float:
    extra = req.extra or {}
    try:
        return max(
            1.0,
            float(extra.get("http_timeout_seconds") or default_total),
        )
    except (TypeError, ValueError):
        return max(1.0, float(default_total))


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
    stream_cb: Optional[Callable[[str], None]] = None

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
    raw: Dict[str, Any] = field(default_factory=dict)


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
    uses_custom_messages_handler: bool = False

    @abstractmethod
    def is_applicable(self, req: LLMRequest) -> bool:
        pass

    @abstractmethod
    def generate(self, req: LLMRequest) -> LLMResponse:
        pass


__all__ = [
    "LLMRequest",
    "LLMUsage",
    "LLMResponse",
    "BaseProvider",
    "RequestCancellation",
    "RequestCancelledError",
    "check_request_cancelled",
    "get_request_cancellation",
    "register_cancellable_resource",
    "resolve_total_timeout",
    "normalize_usage_payload",
    "LLMProviderError",
]
