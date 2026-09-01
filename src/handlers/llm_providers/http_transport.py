from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

import httpx

from core.networking import HttpClientRegistry, ManagedHttpClient, shared_http_client_registry
from main_logger import logger

from .request_lifecycle import (
    check_request_cancelled,
    record_response_headers_received,
    register_cancellable_resource,
)


class LLMRequestLike(Protocol):
    api_url: str | None
    extra: dict[str, Any]


def is_loopback_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).hostname or "").strip("[]").lower()
    except Exception:
        return False
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


@dataclass(frozen=True)
class LLMTimeoutPolicy:
    connect: float
    write: float
    read: float
    pool: float
    attempt_deadline: float

    def to_httpx(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect,
            write=self.write,
            read=self.read,
            pool=self.pool,
        )

    @classmethod
    def for_request(
        cls,
        req: LLMRequestLike,
        *,
        payload_size_bytes: int = 0,
        default_total: float = 240.0,
    ) -> "LLMTimeoutPolicy":
        extra = req.extra or {}
        total = _positive_float(extra.get("http_timeout_seconds"), default_total)
        local = is_loopback_url(req.api_url or "")

        connect_default = min(total, 5.0 if local else 30.0)
        pool_default = min(total, 5.0 if local else 10.0)

        if payload_size_bytes >= 512 * 1024:
            estimated_upload = 30.0 + (payload_size_bytes / (16 * 1024))
            write_default = min(total, max(120.0, min(180.0, estimated_upload)))
        else:
            write_default = min(total, 60.0)

        return cls(
            connect=_positive_float(extra.get("http_connect_timeout_seconds"), connect_default),
            write=_positive_float(extra.get("http_write_timeout_seconds"), write_default),
            read=_positive_float(extra.get("http_read_timeout_seconds"), total),
            pool=_positive_float(extra.get("http_pool_timeout_seconds"), pool_default),
            attempt_deadline=total,
        )


def estimate_json_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def resolve_httpx_timeout(req: LLMRequestLike, *, payload_size_bytes: int = 0) -> httpx.Timeout:
    return LLMTimeoutPolicy.for_request(
        req,
        payload_size_bytes=payload_size_bytes,
    ).to_httpx()


class LLMHttpClient:
    def __init__(
        self,
        *,
        enable_http2: bool = True,
        client_factory: OptionalClientFactory = None,
        registry: HttpClientRegistry | None = None,
        service_id: str = "llm",
    ) -> None:
        self._enable_http2 = bool(enable_http2)
        self._client_factory = client_factory
        self._http2_available = importlib.util.find_spec("h2") is not None
        self._owns_registry = registry is None and client_factory is not None
        self._registry = registry or (
            HttpClientRegistry() if self._owns_registry else shared_http_client_registry()
        )
        self._service_id = str(service_id or "llm").strip().lower()
        if self._enable_http2 and not self._http2_available:
            logger.warning(
                "LLM HTTP/2 support is unavailable because the optional 'h2' package is not installed; "
                "HTTP/1.1 will be used."
            )
        self._http_client = self._registry.acquire(
            self._service_id,
            client_factory=self._create_client,
        )

    @property
    def http2_enabled(self) -> bool:
        return self._enable_http2 and self._http2_available

    def client_for_url(self, url: str) -> httpx.Client:
        return self._http_client.client_for_sdk()

    def post_json(
        self,
        req: LLMRequestLike,
        url: str,
        *,
        headers: Mapping[str, str] | None,
        payload: Any,
        stream: bool,
    ) -> httpx.Response:
        check_request_cancelled(req)
        payload_size = estimate_json_size(payload)
        timeout = LLMTimeoutPolicy.for_request(req, payload_size_bytes=payload_size)
        request = self._http_client.build_request(
            "POST",
            url,
            headers=dict(headers or {}),
            json=payload,
            timeout=timeout.to_httpx(),
        )
        response = self._http_client.send(request, stream=True)
        record_response_headers_received(req)
        register_cancellable_resource(req, response)
        if not stream:
            try:
                response.read()
            except Exception:
                response.close()
                raise
        check_request_cancelled(req)
        logger.debug(
            "LLM HTTP response | destination=%s | protocol=%s | status=%s | payload_bytes=%s",
            "loopback" if is_loopback_url(url) else "remote",
            response.http_version,
            response.status_code,
            payload_size,
        )
        return response

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout = 30.0,
    ) -> httpx.Response:
        response = self._http_client.get(
            url,
            headers=dict(headers or {}),
            timeout=timeout,
        )
        logger.debug(
            "LLM metadata HTTP response | destination=%s | protocol=%s | status=%s",
            "loopback" if is_loopback_url(url) else "remote",
            response.http_version,
            response.status_code,
        )
        return response

    def close(self) -> None:
        self._http_client.close()
        if self._owns_registry:
            self._registry.close()

    def _create_client(self) -> httpx.Client:
        if self._client_factory is not None:
            return self._client_factory(self._service_id, self.http2_enabled)
        return httpx.Client(
            http1=True,
            http2=self.http2_enabled,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=16,
                max_keepalive_connections=8,
                keepalive_expiry=30.0,
            ),
            trust_env=True,
        )


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    return max(0.1, result)


OptionalClientFactory = Callable[[str, bool], httpx.Client] | None


__all__ = [
    "LLMHttpClient",
    "LLMTimeoutPolicy",
    "estimate_json_size",
    "is_loopback_url",
    "resolve_httpx_timeout",
]
