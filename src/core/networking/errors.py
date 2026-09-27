from __future__ import annotations

import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


_SECRET_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "key",
        "password",
        "secret",
        "token",
    }
)


def sanitize_url(url: str | httpx.URL | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(str(url))
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
        query = urlencode(
            [
                (key, "<redacted>" if key.lower() in _SECRET_QUERY_KEYS else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
    except Exception:
        return "<invalid-url>"


@dataclass
class NetworkRequestError(RuntimeError):
    service_id: str
    message: str
    code: str = "network.request"
    phase: str = "request"
    method: str | None = None
    url: str | None = None
    retryable: bool = False
    status_code: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        self.url = sanitize_url(self.url)
        RuntimeError.__init__(self, self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "network_error",
            "service": self.service_id,
            "message": self.message,
            "code": self.code,
            "phase": self.phase,
            "method": self.method,
            "url": self.url,
            "retryable": bool(self.retryable),
            "status_code": self.status_code,
            "detail": self.detail,
        }


class NetworkUnavailableError(NetworkRequestError):
    pass


class NetworkTimeoutError(NetworkRequestError):
    pass


class NetworkConnectionError(NetworkRequestError):
    pass


class HttpResponseError(NetworkRequestError):
    pass


def classify_network_error(
    service_id: str,
    exc: BaseException,
    *,
    method: str | None = None,
    url: str | httpx.URL | None = None,
) -> NetworkRequestError:
    if isinstance(exc, NetworkRequestError):
        return exc

    request = getattr(exc, "request", None)
    response = getattr(exc, "response", None)
    resolved_method = method or getattr(request, "method", None)
    resolved_url = url or getattr(request, "url", None) or getattr(response, "url", None)
    detail = _compact_detail(exc)

    tls_error = _find_tls_error(exc)
    if tls_error is not None:
        certificate_failure = _is_certificate_verification_error(tls_error)
        return NetworkConnectionError(
            service_id=service_id,
            message=(
                "Не удалось проверить SSL-сертификат сервера."
                if certificate_failure
                else "Не удалось установить защищённое SSL/TLS-соединение."
            ),
            code="network.tls.certificate" if certificate_failure else "network.tls.handshake",
            phase="connect",
            method=resolved_method,
            url=str(resolved_url) if resolved_url else None,
            retryable=False,
            detail=_tls_error_detail(tls_error),
        )

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = getattr(response, "status_code", None)
        return HttpResponseError(
            service_id=service_id,
            message=f"Сервер вернул HTTP {status_code or 'error'}.",
            code="http.status",
            phase="response",
            method=resolved_method,
            url=str(resolved_url) if resolved_url else None,
            retryable=bool(status_code in {408, 409, 425, 429, 500, 502, 503, 504}),
            status_code=status_code,
            detail=detail,
        )

    if isinstance(exc, httpx.TimeoutException):
        phase = _timeout_phase(exc)
        return NetworkTimeoutError(
            service_id=service_id,
            message=_timeout_message(phase),
            code=f"network.timeout.{phase}",
            phase=phase,
            method=resolved_method,
            url=str(resolved_url) if resolved_url else None,
            retryable=phase in {"connect", "pool"},
            detail=detail,
        )

    if isinstance(exc, (httpx.ConnectError, httpx.ProxyError)):
        dns_failure = _contains_dns_error(exc)
        return NetworkUnavailableError(
            service_id=service_id,
            message=(
                "Не удалось разрешить адрес сервиса. Проверьте подключение к интернету."
                if dns_failure
                else "Сеть или удалённый сервис недоступны."
            ),
            code="network.dns" if dns_failure else "network.connect",
            phase="connect",
            method=resolved_method,
            url=str(resolved_url) if resolved_url else None,
            retryable=True,
            detail=detail,
        )

    if isinstance(exc, httpx.TransportError):
        phase = _transport_phase(exc)
        return NetworkConnectionError(
            service_id=service_id,
            message="Сетевое соединение было прервано.",
            code=f"network.{phase}",
            phase=phase,
            method=resolved_method,
            url=str(resolved_url) if resolved_url else None,
            retryable=phase in {"connect", "pool", "read"},
            detail=detail,
        )

    return NetworkRequestError(
        service_id=service_id,
        message="Ошибка во время сетевого запроса.",
        code="network.request",
        phase="request",
        method=resolved_method,
        url=str(resolved_url) if resolved_url else None,
        retryable=False,
        detail=detail,
    )


def _contains_dns_error(exc: BaseException) -> bool:
    for current in _iter_exception_chain(exc):
        if isinstance(current, socket.gaierror):
            return True
        text = str(current).lower()
        if any(marker in text for marker in ("getaddrinfo", "name resolution", "nodename nor servname")):
            return True
    return False


def _iter_exception_chain(exc: BaseException):
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


_CERTIFICATE_ERROR_MARKERS = (
    "certificate_verify_failed",
    "certificate verify failed",
    "unable to get local issuer certificate",
    "self signed certificate",
    "hostname mismatch",
    "certificate has expired",
)


def _is_certificate_verification_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _CERTIFICATE_ERROR_MARKERS)


def _find_tls_error(exc: BaseException) -> BaseException | None:
    for cause in _iter_exception_chain(exc):
        if isinstance(cause, ssl.SSLError):
            return cause
        if any(marker in str(cause).lower() for marker in _CERTIFICATE_ERROR_MARKERS):
            return cause
    return None


def _tls_error_detail(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    for marker in _CERTIFICATE_ERROR_MARKERS:
        if marker in lowered:
            return marker

    detail = _compact_detail(exc)
    return _redact_sensitive_text(detail)[:500]


def _redact_sensitive_text(text: str) -> str:
    secret_keys = "|".join(re.escape(key) for key in _SECRET_QUERY_KEYS)
    return re.sub(
        rf"(?i)\b({secret_keys})(=|%3d)([^&\s,]+)",
        r"\1\2<redacted>",
        text,
    )


def _compact_detail(exc: BaseException) -> str:
    return _redact_sensitive_text(" ".join(str(exc or "").split()))[:500]


def _timeout_phase(exc: httpx.TimeoutException) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect"
    if isinstance(exc, httpx.WriteTimeout):
        return "write"
    if isinstance(exc, httpx.ReadTimeout):
        return "read"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool"
    return "request"


def _transport_phase(exc: httpx.TransportError) -> str:
    if isinstance(exc, (httpx.ConnectError, httpx.ProxyError)):
        return "connect"
    if isinstance(exc, httpx.WriteError):
        return "write"
    if isinstance(exc, httpx.ReadError):
        return "read"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool"
    if isinstance(exc, httpx.ProtocolError):
        return "protocol"
    return "transport"


def _timeout_message(phase: str) -> str:
    return {
        "connect": "Не удалось подключиться к сервису вовремя.",
        "write": "Не удалось отправить запрос вовремя.",
        "read": "Сервер не ответил вовремя.",
        "pool": "Все сетевые соединения этого сервиса заняты.",
    }.get(phase, "Сетевой запрос не завершился вовремя.")


__all__ = [
    "HttpResponseError",
    "NetworkConnectionError",
    "NetworkRequestError",
    "NetworkTimeoutError",
    "NetworkUnavailableError",
    "classify_network_error",
    "sanitize_url",
]
