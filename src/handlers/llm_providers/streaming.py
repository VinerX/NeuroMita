from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Optional

from main_logger import logger
from services.llm_stream import LLMStreamEvent, LLMStreamEventType

from .base import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    RequestCancellation,
    StreamChannel,
    get_request_cancellation,
    record_response_body_started,
    resolve_content_and_reasoning,
)


@dataclass(frozen=True)
class StreamDeadlinePolicy:
    first_meaningful_event: float = 300.0
    idle_after_started: float = 120.0
    maximum_duration: float = 1800.0
    poll_interval: float = 0.25

    @classmethod
    def for_request(cls, req: LLMRequest) -> "StreamDeadlinePolicy":
        extra = req.extra or {}
        return cls(
            first_meaningful_event=_positive_float(extra.get("stream_first_meaningful_timeout_seconds"), 300.0),
            idle_after_started=_positive_float(extra.get("stream_idle_timeout_seconds"), 120.0),
            maximum_duration=_positive_float(extra.get("stream_max_duration_seconds"), 1800.0),
            poll_interval=_positive_float(extra.get("stream_watchdog_poll_seconds"), 0.25),
        )


class StreamDeadlineExceeded(TimeoutError):
    pass


class StreamSupervisor:
    def __init__(self, cancellation: RequestCancellation, policy: StreamDeadlinePolicy) -> None:
        self.cancellation = cancellation
        self.policy = policy

    @property
    def poll_interval(self) -> float:
        return self.policy.poll_interval

    def raise_if_expired(self, *, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else float(now)
        started_at, first_event_at, last_event_at = self.cancellation.stream_activity()
        elapsed = current - started_at
        if elapsed >= self.policy.maximum_duration:
            raise StreamDeadlineExceeded(
                f"Stream exceeded maximum duration of {self.policy.maximum_duration:.1f}s."
            )
        if first_event_at is None and elapsed >= self.policy.first_meaningful_event:
            raise StreamDeadlineExceeded(
                "Stream produced no meaningful event within "
                f"{self.policy.first_meaningful_event:.1f}s."
            )
        if last_event_at is not None and (current - last_event_at) >= self.policy.idle_after_started:
            raise StreamDeadlineExceeded(
                "Stream became idle for more than "
                f"{self.policy.idle_after_started:.1f}s."
            )


class StreamEventChannel:
    def __init__(self, req: LLMRequest) -> None:
        self.request_id = str((req.extra or {}).get("request_id") or "")
        self.callback = req.stream_event_cb
        self._sequence = 0
        self._started = False
        self._terminal = False
        self._lock = threading.RLock()

    def start(self, *, provider: str, model: str) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._emit_locked(LLMStreamEventType.STARTED, provider=provider, model=model)

    def emit(self, event_type: LLMStreamEventType, *, provider: str, model: str, **kwargs: Any) -> LLMStreamEvent:
        with self._lock:
            if self._terminal:
                raise RuntimeError("Cannot emit after terminal stream event")
            return self._emit_locked(event_type, provider=provider, model=model, **kwargs)

    def complete(self, response: LLMResponse) -> None:
        with self._lock:
            if self._terminal:
                return
            if not self._started:
                self._started = True
                self._emit_locked(
                    LLMStreamEventType.STARTED,
                    provider=str(response.provider_name or ""),
                    model=str(response.model or ""),
                )
            if response.usage is not None:
                self._emit_locked(
                    LLMStreamEventType.USAGE,
                    provider=str(response.provider_name or ""),
                    model=str(response.model or ""),
                    usage=response.usage,
                )
            self._emit_locked(
                LLMStreamEventType.COMPLETED,
                provider=str(response.provider_name or ""),
                model=str(response.model or ""),
                finish_reason=response.finish_reason,
            )
            self._terminal = True

    def fail(self, error: Any) -> None:
        with self._lock:
            if self._terminal:
                return
            if not self._started:
                self._started = True
                self._emit_locked(
                    LLMStreamEventType.STARTED,
                    provider=str(getattr(error, "provider", "") or ""),
                    model="",
                )
            self._emit_locked(
                LLMStreamEventType.FAILED,
                provider=str(getattr(error, "provider", "") or ""),
                model="",
                retryable=bool(getattr(error, "retryable", False)),
                error_code=getattr(error, "code", None),
                raw_provider_code=getattr(error, "code", None),
                metadata={"message": getattr(error, "to_user_message", lambda: str(error))()},
            )
            self._terminal = True

    def _emit_locked(
        self,
        event_type: LLMStreamEventType,
        *,
        provider: str,
        model: str,
        **kwargs: Any,
    ) -> LLMStreamEvent:
        self._sequence += 1
        event = LLMStreamEvent(
            type=event_type,
            request_id=self.request_id,
            provider=provider,
            model=model,
            sequence=self._sequence,
            **kwargs,
        )
        if callable(self.callback):
            try:
                self.callback(event)
            except Exception:
                logger.exception("LLM stream consumer failed and was detached")
                self.callback = None
        return event


class StreamAccumulator:
    def __init__(self, req: LLMRequest, *, provider: str, model: str) -> None:
        self.req = req
        self.provider = str(provider or "")
        self.model = str(model or req.model or "")
        self.text_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.usage: Optional[LLMUsage] = None
        self.finish_reason: Optional[str] = None
        channel = (req.extra or {}).get("_stream_event_channel")
        if not isinstance(channel, StreamEventChannel):
            channel = StreamEventChannel(req)
            req.extra["_stream_event_channel"] = channel
        self.channel = channel
        self.channel.start(provider=self.provider, model=self.model)

    def emit(self, event_type: LLMStreamEventType, **kwargs: Any) -> LLMStreamEvent:
        event = self.channel.emit(
            event_type,
            provider=self.provider,
            model=self.model,
            **kwargs,
        )
        if event.type in {
            LLMStreamEventType.TEXT_DELTA,
            LLMStreamEventType.REASONING_DELTA,
            LLMStreamEventType.TOOL_CALL_STARTED,
            LLMStreamEventType.TOOL_CALL_DELTA,
            LLMStreamEventType.TOOL_CALL_COMPLETED,
            LLMStreamEventType.COMPLETED,
            LLMStreamEventType.FAILED,
        }:
            cancellation = get_request_cancellation(self.req)
            if cancellation is not None:
                cancellation.record_meaningful_stream_event()
        return event

    def add_text(self, text: Any) -> None:
        value = str(text or "")
        if not value:
            return
        self.text_parts.append(value)
        self.emit(LLMStreamEventType.TEXT_DELTA, text=value)
        if callable(self.req.stream_cb):
            self.req.stream_cb(value, StreamChannel.CONTENT)

    def add_reasoning(self, text: Any) -> None:
        value = str(text or "")
        if not value:
            return
        self.reasoning_parts.append(value)
        self.emit(LLMStreamEventType.REASONING_DELTA, text=value)
        if callable(self.req.stream_cb):
            # Канал, а не <think>-обёртка: подписчику незачем парсить теги, чтобы
            # понять, что пришло — иначе мысли снова окажутся в тексте ответа.
            self.req.stream_cb(value, StreamChannel.REASONING)

    def set_usage(self, usage: Optional[LLMUsage]) -> None:
        if usage is None:
            return
        self.usage = usage

    def tool_call_started(self, *, tool_call_id: str, tool_name: str) -> None:
        self.emit(
            LLMStreamEventType.TOOL_CALL_STARTED,
            tool_call_id=str(tool_call_id or ""),
            tool_name=str(tool_name or ""),
        )

    def tool_call_delta(self, *, tool_call_id: str, tool_name: str, arguments_delta: str) -> None:
        self.emit(
            LLMStreamEventType.TOOL_CALL_DELTA,
            tool_call_id=str(tool_call_id or ""),
            tool_name=str(tool_name or ""),
            text=str(arguments_delta or ""),
        )

    def tool_call_completed(self, *, tool_call_id: str, tool_name: str) -> None:
        self.emit(
            LLMStreamEventType.TOOL_CALL_COMPLETED,
            tool_call_id=str(tool_call_id or ""),
            tool_name=str(tool_name or ""),
        )

    def complete(self, *, finish_reason: Optional[str] = None, model: Optional[str] = None) -> LLMResponse:
        if model:
            self.model = str(model)
        self.finish_reason = finish_reason or self.finish_reason
        # text — только то, что видит игрок; мысли уезжают отдельным полем.
        # Аварийный фолбэк на случай, когда модель кладёт весь ответ в
        # reasoning-канал и оставляет content пустым.
        visible, reasoning = resolve_content_and_reasoning(
            "".join(self.text_parts),
            "".join(self.reasoning_parts),
            provider_name=self.provider,
        )
        return LLMResponse(
            text=visible or None,
            usage=self.usage,
            model=self.model or None,
            provider_name=self.provider,
            finish_reason=self.finish_reason,
            reasoning=reasoning or None,
        )


def iter_sse_data(lines: Iterable[str | bytes]) -> Iterator[str]:
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if field != "data":
            continue
        if separator and value.startswith(" "):
            value = value[1:]
        data_lines.append(value)
    if data_lines:
        yield "\n".join(data_lines)


def track_response_body(req: LLMRequest, chunks: Iterable[Any]) -> Iterator[Any]:
    for chunk in chunks:
        record_response_body_started(req)
        yield chunk


def iter_json_values(chunks: Iterable[str | bytes]) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    buffer = ""
    for raw_chunk in chunks:
        buffer += raw_chunk.decode("utf-8", errors="replace") if isinstance(raw_chunk, bytes) else str(raw_chunk)
        while buffer.strip():
            stripped = buffer.lstrip()
            try:
                value, index = decoder.raw_decode(stripped)
            except json.JSONDecodeError:
                break
            yield value
            buffer = stripped[index:]
    if buffer.strip():
        raise json.JSONDecodeError("Incomplete or invalid JSON stream payload", buffer, 0)


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    return max(0.05, result)


__all__ = [
    "LLMStreamEvent",
    "LLMStreamEventType",
    "StreamAccumulator",
    "StreamEventChannel",
    "StreamDeadlinePolicy",
    "StreamDeadlineExceeded",
    "StreamSupervisor",
    "iter_json_values",
    "iter_sse_data",
    "track_response_body",
]
