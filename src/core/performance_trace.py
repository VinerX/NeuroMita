"""Low-overhead, in-memory performance tracing for one logical request.

The module deliberately has no dependency on controllers or services.  A trace
can therefore cross worker threads, asyncio tasks, and event-bus callbacks.
Telemetry is best-effort: tracing failures must never affect the application
request that is being measured.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from math import ceil
from statistics import median
from threading import RLock
from typing import Any, Iterator

from main_logger import logger


ACTIVE_TRACE_TTL_SEC = 600.0


_SENSITIVE_ATTRIBUTE_PARTS = (
    "prompt",
    "input",
    "output",
    "content",
    "argument",
    "secret",
    "token",
    "password",
    "api_key",
    "url",
)


def _safe_attributes(values: dict[str, Any]) -> dict[str, Any]:
    """Keep trace metadata small and free of conversation/provider secrets."""
    safe: dict[str, Any] = {}
    for key, value in values.items():
        normalized_key = str(key)
        lowered_key = normalized_key.lower()
        is_safe_numeric_metric = isinstance(value, (bool, int, float)) and lowered_key.endswith(
            ("_chars", "_count", "_sec", "_ms")
        )
        if any(part in lowered_key for part in _SENSITIVE_ATTRIBUTE_PARTS) and not is_safe_numeric_metric:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            safe[normalized_key] = value
        elif isinstance(value, str):
            safe[normalized_key] = value[:160]
        else:
            safe[normalized_key] = str(value)[:160]
    return safe


@dataclass(slots=True)
class PerfSpan:
    name: str
    started_ns: int
    ended_ns: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end_ns = self.ended_ns if self.ended_ns is not None else time.perf_counter_ns()
        return max(0.0, (end_ns - self.started_ns) / 1_000_000.0)


@dataclass(slots=True)
class PerfMark:
    name: str
    at_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)


class PerformanceTrace:
    """Thread-safe timing data for one user or system request."""

    def __init__(
        self,
        trace_id: str,
        source: str,
        *,
        attributes: dict[str, Any] | None = None,
        started_ns: int | None = None,
    ) -> None:
        self.trace_id = str(trace_id)
        self.source = str(source or "unknown")
        self.started_ns = started_ns if started_ns is not None else time.perf_counter_ns()
        self.last_activity_ns = self.started_ns
        self.finished_ns: int | None = None
        self.status = "active"
        self.error_stage = ""
        self.error_type = ""
        self.attributes = _safe_attributes(attributes or {})
        self._spans: list[PerfSpan] = []
        self._active_spans: dict[int, PerfSpan] = {}
        self._marks: list[PerfMark] = []
        self._mark_names: set[str] = set()
        self._next_span_token = 0
        self._lock = RLock()

    def start_span(self, name: str, **attrs: Any) -> int:
        try:
            with self._lock:
                self._next_span_token += 1
                token = self._next_span_token
                span_started_ns = time.perf_counter_ns()
                self.last_activity_ns = span_started_ns
                span = PerfSpan(
                    name=str(name),
                    started_ns=span_started_ns,
                    attributes=_safe_attributes(attrs),
                )
                self._spans.append(span)
                self._active_spans[token] = span
                return token
        except Exception:
            return -1

    def finish_span(self, token: int, **attrs: Any) -> None:
        if token < 0:
            return
        try:
            with self._lock:
                span = self._active_spans.pop(token, None)
                if span is None:
                    return
                span.ended_ns = time.perf_counter_ns()
                self.last_activity_ns = span.ended_ns
                span.attributes.update(_safe_attributes(attrs))
        except Exception:
            return

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        token = self.start_span(name, **attrs)
        try:
            yield None
        except Exception as exc:
            self.finish_span(token, result="error", error_type=type(exc).__name__)
            raise
        else:
            self.finish_span(token, result="success")

    def mark(self, name: str, **attrs: Any) -> None:
        try:
            with self._lock:
                mark_at_ns = time.perf_counter_ns()
                self.last_activity_ns = mark_at_ns
                self._marks.append(
                    PerfMark(
                        name=str(name),
                        at_ns=mark_at_ns,
                        attributes=_safe_attributes(attrs),
                    )
                )
        except Exception:
            return

    def mark_once(self, name: str, **attrs: Any) -> bool:
        try:
            with self._lock:
                normalized_name = str(name)
                mark_at_ns = time.perf_counter_ns()
                self.last_activity_ns = mark_at_ns
                if normalized_name in self._mark_names:
                    return False
                self._mark_names.add(normalized_name)
                self._marks.append(
                    PerfMark(
                        name=normalized_name,
                        at_ns=mark_at_ns,
                        attributes=_safe_attributes(attrs),
                    )
                )
                return True
        except Exception:
            return False

    def set_attribute(self, key: str, value: Any) -> None:
        try:
            with self._lock:
                self.last_activity_ns = time.perf_counter_ns()
                self.attributes.update(_safe_attributes({str(key): value}))
        except Exception:
            return

    def finish(
        self,
        status: str = "ok",
        *,
        error_stage: str = "",
        error_type: str = "",
    ) -> None:
        try:
            with self._lock:
                if self.finished_ns is not None:
                    return
                now_ns = time.perf_counter_ns()
                for span in self._active_spans.values():
                    span.ended_ns = now_ns
                    span.attributes.setdefault("result", "unfinished")
                self._active_spans.clear()
                self.finished_ns = now_ns
                self.status = str(status or "ok")
                self.error_stage = str(error_stage or "")
                self.error_type = str(error_type or "")
        except Exception:
            return

    def total_ms(self) -> float:
        try:
            with self._lock:
                end_ns = self.finished_ns if self.finished_ns is not None else time.perf_counter_ns()
                return max(0.0, (end_ns - self.started_ns) / 1_000_000.0)
        except Exception:
            return 0.0

    def snapshot(self) -> dict[str, Any]:
        try:
            with self._lock:
                marks = list(self._marks)
                spans = list(self._spans)
                return {
                    "trace_id": self.trace_id,
                    "source": self.source,
                    "status": self.status,
                    "error_stage": self.error_stage,
                    "error_type": self.error_type,
                    "attributes": dict(self.attributes),
                    "started_ns": self.started_ns,
                    "last_activity_ns": self.last_activity_ns,
                    "finished_ns": self.finished_ns,
                    "total_ms": self.total_ms(),
                    "marks": [
                        {
                            "name": mark.name,
                            "at_ns": mark.at_ns,
                            "elapsed_ms": max(0.0, (mark.at_ns - self.started_ns) / 1_000_000.0),
                            "attributes": dict(mark.attributes),
                        }
                        for mark in marks
                    ],
                    "spans": [
                        {
                            "name": span.name,
                            "started_ns": span.started_ns,
                            "ended_ns": span.ended_ns,
                            "duration_ms": span.duration_ms,
                            "attributes": dict(span.attributes),
                        }
                        for span in spans
                    ],
                    "metrics": self._derived_metrics(marks, spans),
                }
        except Exception:
            return {
                "trace_id": self.trace_id,
                "source": self.source,
                "status": "telemetry_error",
                "total_ms": 0.0,
                "marks": [],
                "spans": [],
                "metrics": {},
            }

    def _derived_metrics(self, marks: list[PerfMark], spans: list[PerfSpan]) -> dict[str, float]:
        first_marks: dict[str, int] = {}
        for mark in marks:
            first_marks.setdefault(mark.name, mark.at_ns)

        metrics: dict[str, float] = {}
        pairs = {
            "generation_pool_wait_ms": ("generation.enqueued", "generation.worker_started"),
            "character_lock_wait_ms": (
                "generation.character_lock_wait_started",
                "generation.character_lock_acquired",
            ),
            "first_stream_event_ms": (None, "response.first_stream_event"),
            "first_visible_text_ms": (None, "response.first_visible_text"),
            "text_ready_ms": (None, "asr.text_ready"),
            "voice_ready_ms": (None, "tts.ready"),
            "playback_start_ms": (None, "audio.playback_started"),
        }
        for metric_name, (start_name, end_name) in pairs.items():
            end_ns = first_marks.get(end_name)
            if end_ns is None:
                continue
            start_ns = first_marks.get(start_name) if start_name else self.started_ns
            if start_ns is not None:
                metrics[metric_name] = max(0.0, (end_ns - start_ns) / 1_000_000.0)

        llm_span_objects = [span for span in spans if span.name == "llm.total"]
        llm_spans = [span.duration_ms for span in llm_span_objects]
        tts_spans = [
            span.duration_ms
            for span in spans
            if span.name in {"tts.synthesis", "tts.telegram"}
        ]
        if llm_spans:
            metrics["llm_total_ms"] = sum(llm_spans)

            # These are only emitted when the mark happened inside an LLM span.
            # Non-streaming UI dispatch happens after the span and is not TTFT.
            for metric_name, mark_name in (
                ("llm_first_event_ms", "response.first_stream_event"),
                ("llm_first_visible_text_ms", "response.first_visible_text"),
            ):
                mark_ns = first_marks.get(mark_name)
                if mark_ns is None:
                    continue
                for span in llm_span_objects:
                    if span.started_ns <= mark_ns and (
                        span.ended_ns is None or mark_ns <= span.ended_ns
                    ):
                        metrics[metric_name] = max(
                            0.0,
                            (mark_ns - span.started_ns) / 1_000_000.0,
                        )
                        break
        if tts_spans:
            metrics["tts_total_ms"] = sum(tts_spans)

        http_enqueued: dict[tuple[str, str, str], list[int]] = {}
        http_started: dict[tuple[str, str, str], list[int]] = {}
        for mark in marks:
            if mark.name not in {"llm.http_enqueued", "llm.http_started"}:
                continue
            attrs = mark.attributes
            key = (
                str(attrs.get("attempt_id") or attrs.get("attempt") or ""),
                str(attrs.get("provider") or ""),
                str(attrs.get("model") or ""),
            )
            target = http_enqueued if mark.name == "llm.http_enqueued" else http_started
            target.setdefault(key, []).append(mark.at_ns)
        queue_waits: list[float] = []
        for key, enqueued_times in http_enqueued.items():
            remaining_started = sorted(http_started.get(key, ()))
            for enqueued_ns in enqueued_times:
                for index, started_ns in enumerate(remaining_started):
                    if started_ns < enqueued_ns:
                        continue
                    remaining_started.pop(index)
                    queue_waits.append(max(0.0, (started_ns - enqueued_ns) / 1_000_000.0))
                    break
        if queue_waits:
            metrics["llm_http_pool_wait_ms"] = sum(queue_waits)
            metrics["llm_http_first_pool_wait_ms"] = queue_waits[0]
        if self.finished_ns is not None:
            metrics["full_pipeline_ms"] = self.total_ms()
        return metrics


class PerformanceTraceStore:
    """Bounded process-local storage for active and recently finished traces."""

    ACTIVE_TRACE_TTL_SEC = ACTIVE_TRACE_TTL_SEC

    def __init__(
        self,
        maxlen: int = 100,
        *,
        active_trace_ttl_sec: float = ACTIVE_TRACE_TTL_SEC,
    ) -> None:
        self._maxlen = max(1, int(maxlen))
        try:
            self._active_trace_ttl_sec = max(0.0, float(active_trace_ttl_sec))
        except (TypeError, ValueError):
            self._active_trace_ttl_sec = self.ACTIVE_TRACE_TTL_SEC
        self._finished: deque[dict[str, Any]] = deque(maxlen=self._maxlen)
        self._active: dict[str, PerformanceTrace] = {}
        self._lock = RLock()

    def _expire_stale_locked(self) -> None:
        """Close abandoned traces without needing a background cleanup thread."""
        if self._active_trace_ttl_sec <= 0:
            return
        now_ns = time.perf_counter_ns()
        ttl_ns = int(self._active_trace_ttl_sec * 1_000_000_000)
        stale_ids = [
            trace_id
            for trace_id, trace in self._active.items()
            if now_ns - trace.last_activity_ns >= ttl_ns
        ]
        for trace_id in stale_ids:
            trace = self._active.pop(trace_id, None)
            if trace is None:
                continue
            trace.finish("abandoned", error_stage="unknown", error_type="TraceTTLExpired")
            self._finished.append(trace.snapshot())

    def start(
        self,
        source: str,
        *,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        started_ns: int | None = None,
    ) -> PerformanceTrace:
        try:
            normalized_id = str(trace_id or uuid.uuid4().hex)
            with self._lock:
                self._expire_stale_locked()
                existing = self._active.get(normalized_id)
                if existing is not None:
                    return existing
                if trace_id and any(
                    str(snapshot.get("trace_id") or "") == normalized_id
                    for snapshot in self._finished
                ):
                    normalized_id = uuid.uuid4().hex
                trace = PerformanceTrace(
                    normalized_id,
                    source,
                    attributes=attributes,
                    started_ns=started_ns,
                )
                self._active[normalized_id] = trace
                return trace
        except Exception:
            # The fallback still gives callers an object with the normal API.
            return PerformanceTrace(str(trace_id or uuid.uuid4().hex), source, attributes=attributes)

    def get(self, trace_id: str | None) -> PerformanceTrace | None:
        if not trace_id:
            return None
        try:
            with self._lock:
                self._expire_stale_locked()
                return self._active.get(str(trace_id))
        except Exception:
            return None

    def snapshot(self, trace_id: str | None) -> dict[str, Any] | None:
        """Return a point-in-time snapshot for an active or recently finished trace."""
        if not trace_id:
            return None
        try:
            normalized_id = str(trace_id)
            with self._lock:
                self._expire_stale_locked()
                active = self._active.get(normalized_id)
                if active is not None:
                    return active.snapshot()
                for snapshot in reversed(self._finished):
                    if str(snapshot.get("trace_id") or "") == normalized_id:
                        return dict(snapshot)
        except Exception:
            return None
        return None

    def finish(
        self,
        trace_id: str,
        status: str = "ok",
        *,
        error_stage: str = "",
        error_type: str = "",
    ) -> dict[str, Any] | None:
        try:
            with self._lock:
                self._expire_stale_locked()
                trace = self._active.pop(str(trace_id), None)
                if trace is None:
                    return None
                trace.finish(status, error_stage=error_stage, error_type=error_type)
                snapshot = trace.snapshot()
                self._finished.append(snapshot)
            try:
                logger.debug(format_perf_summary(snapshot))
            except Exception:
                pass
            return snapshot
        except Exception:
            return None

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._lock:
                self._expire_stale_locked()
                count = max(0, int(limit))
                return list(reversed(list(self._finished)[-count:])) if count else []
        except Exception:
            return []

    def active(self) -> list[dict[str, Any]]:
        try:
            with self._lock:
                self._expire_stale_locked()
                return [trace.snapshot() for trace in self._active.values()]
        except Exception:
            return []

    def summary(self, limit: int = 50) -> dict[str, Any]:
        try:
            with self._lock:
                self._expire_stale_locked()
                count = max(0, int(limit))
                traces = list(reversed(list(self._finished)[-count:])) if count else []
                active_count = len(self._active)
        except Exception:
            traces = []
            active_count = 0

        def _stats(values: list[float]) -> dict[str, float | int]:
            if not values:
                return {}
            ordered = sorted(values)

            def _percentile(percent: float) -> float:
                index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percent) - 1))
                return ordered[index]

            return {
                "count": len(values),
                "avg_ms": sum(values) / len(values),
                "median_ms": float(median(ordered)),
                "p95_ms": _percentile(0.95),
                "max_ms": max(values),
            }

        latency_values: dict[str, list[float]] = {}
        span_values: dict[str, list[float]] = {}
        for trace in traces:
            for metric_name, value in (trace.get("metrics") or {}).items():
                try:
                    latency_values.setdefault(str(metric_name), []).append(float(value))
                except (TypeError, ValueError):
                    continue
            for span in trace.get("spans", []):
                try:
                    span_values.setdefault(str(span.get("name")), []).append(float(span.get("duration_ms", 0.0)))
                except (TypeError, ValueError):
                    continue
        span_stats = {name: _stats(values) for name, values in span_values.items() if values}
        return {
            "active_count": active_count,
            "finished_count": len(traces),
            "trace_count": len(traces),
            "traces": traces,
            "latency": {name: _stats(values) for name, values in latency_values.items() if values},
            "spans": span_stats,
            "span_stats": span_stats,
        }

    def clear(self) -> None:
        try:
            with self._lock:
                self._active.clear()
                self._finished.clear()
        except Exception:
            return


_STORE = PerformanceTraceStore()


def performance_traces() -> PerformanceTraceStore:
    return _STORE


def get_trace(trace_id: str | None) -> PerformanceTrace | None:
    return _STORE.get(trace_id)


def get_trace_snapshot(trace_id: str | None) -> dict[str, Any] | None:
    """Return agent-safe data for one active or recently finished trace."""
    return _STORE.snapshot(trace_id)


def perf_mark(trace_id: str | None, name: str, **attrs: Any) -> None:
    trace = get_trace(trace_id)
    if trace is not None:
        trace.mark(name, **attrs)


def perf_mark_once(trace_id: str | None, name: str, **attrs: Any) -> bool:
    trace = get_trace(trace_id)
    return trace.mark_once(name, **attrs) if trace is not None else False


@contextmanager
def perf_span(trace_id: str | None, name: str, **attrs: Any) -> Iterator[None]:
    trace = get_trace(trace_id)
    if trace is None:
        yield None
        return
    with trace.span(name, **attrs):
        yield None


def format_perf_summary(snapshot: dict[str, Any]) -> str:
    metrics = snapshot.get("metrics") or {}
    spans = snapshot.get("spans") or []
    trace_id = str(snapshot.get("trace_id") or "")[:12]
    source = str(snapshot.get("source") or "unknown")
    total = float(snapshot.get("total_ms") or 0.0) / 1000.0
    text = float(metrics.get("first_visible_text_ms") or 0.0) / 1000.0
    voice = float(metrics.get("voice_ready_ms") or 0.0) / 1000.0
    queue = float(metrics.get("generation_pool_wait_ms") or 0.0) / 1000.0
    lock = float(metrics.get("character_lock_wait_ms") or 0.0) / 1000.0
    context_ms = sum(
        float(span.get("duration_ms") or 0.0)
        for span in spans
        if str(span.get("name") or "") in {
            "generation.rag",
            "generation.image_description",
            "generation.prompt_build",
        }
    )
    llm = float(metrics.get("llm_total_ms") or 0.0) / 1000.0
    tts = float(metrics.get("tts_total_ms") or 0.0) / 1000.0
    character_id = str((snapshot.get("attributes") or {}).get("character_id") or "")
    character_part = f" character={character_id}" if character_id else ""
    return (
        f"[PERF] trace={trace_id} source={source}{character_part} status={snapshot.get('status', 'unknown')} "
        f"total={total:.3f}s text={text:.3f}s voice={voice:.3f}s "
        f"queue={queue:.3f}s lock={lock:.3f}s context={context_ms / 1000.0:.3f}s "
        f"llm={llm:.3f}s tts={tts:.3f}s"
    )


def format_perf_details(snapshot: dict[str, Any]) -> list[str]:
    """Format spans as compact DEBUG-friendly lines."""
    trace_id = str(snapshot.get("trace_id") or "")[:12]
    lines: list[str] = []
    for span in snapshot.get("spans", []):
        name = str(span.get("name") or "")
        duration = float(span.get("duration_ms") or 0.0)
        lines.append(f"[PERF:{trace_id}] {name:<36} {duration:>8.1f} ms")
    return lines
