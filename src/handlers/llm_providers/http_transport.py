from __future__ import annotations

import importlib.util
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

import httpx

from main_logger import logger

from .request_lifecycle import (
    check_request_cancelled,
    record_response_headers_received,
    register_cancellable_resource,
)


class LLMRequestLike(Protocol):
    api_url: str | None
    extra: dict[str, Any]


class TransportProfile(str, Enum):
    REMOTE = "remote"
    LOCAL = "local"


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


class LLMHttpTransport:
    def __init__(
        self,
        *,
        enable_http2: bool = True,
        client_factory: OptionalClientFactory = None,
    ) -> None:
        self._enable_http2 = bool(enable_http2)
        self._client_factory = client_factory
        self._http2_available = importlib.util.find_spec("h2") is not None
        self._clients: dict[TransportProfile, httpx.Client] = {}
        self._lock = threading.RLock()
        self._closed = False
        if self._enable_http2 and not self._http2_available:
            logger.warning(
                "LLM HTTP/2 support is unavailable because the optional 'h2' package is not installed; "
                "HTTP/1.1 will be used."
            )

    @property
    def http2_enabled(self) -> bool:
        return self._enable_http2 and self._http2_available

    def client_for_url(self, url: str) -> httpx.Client:
        profile = TransportProfile.LOCAL if is_loopback_url(url) else TransportProfile.REMOTE
        with self._lock:
            if self._closed:
                raise RuntimeError("LLM HTTP transport is closed")
            client = self._clients.get(profile)
            if client is None:
                client = self._create_client(profile)
                self._clients[profile] = client
            return client

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
        client = self.client_for_url(url)
        payload_size = estimate_json_size(payload)
        timeout = LLMTimeoutPolicy.for_request(req, payload_size_bytes=payload_size)
        request = client.build_request(
            "POST",
            url,
            headers=dict(headers or {}),
            json=payload,
            timeout=timeout.to_httpx(),
        )
        response = client.send(request, stream=True)
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
            "LLM HTTP response | profile=%s | protocol=%s | status=%s | payload_bytes=%s",
            TransportProfile.LOCAL.value if is_loopback_url(url) else TransportProfile.REMOTE.value,
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
        client = self.client_for_url(url)
        response = client.get(
            url,
            headers=dict(headers or {}),
            timeout=timeout,
        )
        logger.debug(
            "LLM metadata HTTP response | profile=%s | protocol=%s | status=%s",
            TransportProfile.LOCAL.value if is_loopback_url(url) else TransportProfile.REMOTE.value,
            response.http_version,
            response.status_code,
        )
        return response

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = tuple(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:
                logger.debug("Failed to close LLM HTTP client", exc_info=True)

    def _create_client(self, profile: TransportProfile) -> httpx.Client:
        is_local = profile is TransportProfile.LOCAL
        if self._client_factory is not None:
            return self._client_factory(profile, bool(self.http2_enabled and not is_local))
        return httpx.Client(
            http1=True,
            http2=bool(self.http2_enabled and not is_local),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=8 if is_local else 16,
                max_keepalive_connections=4 if is_local else 8,
                keepalive_expiry=30.0,
            ),
            # Local model servers must never inherit a broken corporate/system proxy.
            # Remote providers still respect HTTP(S)_PROXY and certificate settings.
            trust_env=not is_local,
        )


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    return max(0.1, result)


OptionalClientFactory = Callable[[TransportProfile, bool], httpx.Client] | None


__all__ = [
    "LLMHttpTransport",
    "LLMTimeoutPolicy",
    "TransportProfile",
    "estimate_json_size",
    "is_loopback_url",
    "resolve_httpx_timeout",
]
