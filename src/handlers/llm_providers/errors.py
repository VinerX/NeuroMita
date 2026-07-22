from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import httpx

from utils import _, mask_sensitive


_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _compact_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_status_code(text: str) -> Optional[int]:
    if not text:
        return None

    patterns = (
        r"Error code:\s*(\d{3})",
        r"HTTP\s+(\d{3})",
        r"\bstatus(?:_code)?['\":=\s]+(\d{3})\b",
        r"\bcode['\":=\s]+(\d{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _extract_provider_message(payload: Any) -> str:
    candidates = list(_iter_provider_message_candidates(payload))
    for candidate in candidates:
        if not _looks_like_generic_provider_wrapper(candidate):
            return candidate
    return candidates[0] if candidates else _compact_text(payload)


def _parse_embedded_payload(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text or text[0] not in "{[":
        return value

    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except Exception:
            continue
    return value


def _looks_like_generic_provider_wrapper(text: str) -> bool:
    low = _compact_text(text).lower()
    return low in {
        "",
        "provider returned error",
        "provider error",
        "bad request from provider.",
        "unknown provider error.",
    }


def _iter_provider_message_candidates(payload: Any, *, _depth: int = 0):
    if payload is None or _depth > 4:
        return

    if isinstance(payload, str):
        text = _compact_text(payload)
        if text:
            yield text
        parsed = _parse_embedded_payload(payload)
        if parsed is not payload:
            yield from _iter_provider_message_candidates(parsed, _depth=_depth + 1)
        return

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            metadata = err.get("metadata")
            if isinstance(metadata, dict) and metadata.get("raw") is not None:
                yield from _iter_provider_message_candidates(metadata.get("raw"), _depth=_depth + 1)
            for key in ("message", "detail", "error", "title", "type"):
                text = _compact_text(err.get(key))
                if text:
                    yield text
            yield from _iter_provider_message_candidates(err, _depth=_depth + 1)
        elif err:
            yield from _iter_provider_message_candidates(err, _depth=_depth + 1)

        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and metadata.get("raw") is not None:
            yield from _iter_provider_message_candidates(metadata.get("raw"), _depth=_depth + 1)

        for key in ("message", "detail", "error_description", "title", "type"):
            text = _compact_text(payload.get(key))
            if text:
                yield text
        return

    text = _compact_text(payload)
    if text:
        yield text


def _extract_retry_after_seconds(
    *,
    response_headers: Any = None,
    payload: Any = None,
    provider_message: str = "",
) -> Optional[float]:
    header_value = None
    if response_headers is not None:
        try:
            header_value = response_headers.get("Retry-After")
        except Exception:
            header_value = None

    if header_value is not None:
        text = _compact_text(header_value)
        if text.isdigit():
            try:
                return max(0.0, float(text))
            except Exception:
                pass
        try:
            retry_dt = parsedate_to_datetime(text)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delay)
        except Exception:
            pass

    candidates = []
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            candidates.extend(
                err.get(key)
                for key in ("retry_after", "retry_after_seconds", "retryAfter", "retryAfterSeconds")
            )
        candidates.extend(
            payload.get(key)
            for key in ("retry_after", "retry_after_seconds", "retryAfter", "retryAfterSeconds")
        )

    for value in candidates:
        try:
            if value is None or value == "":
                continue
            return max(0.0, float(value))
        except Exception:
            continue

    message = _compact_text(provider_message)
    if not message:
        return None

    patterns = (
        r"retry after\s+(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
        r"try again in\s+(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
        r"please wait\s+(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except Exception:
                return None

    return None


def _should_surface_provider_message(friendly_message: str, provider_message: str) -> bool:
    detail = _compact_text(provider_message)
    friendly = _compact_text(friendly_message)
    if not detail:
        return False

    low = detail.lower()
    if low in {friendly.lower(), "bad request from provider.", "unauthorized request.", "access forbidden.", "endpoint not found."}:
        return False
    if len(detail) > 180:
        return False
    if any(marker in detail for marker in ("Traceback", "provider=", "retryable=", "url=", "\n")):
        return False
    if detail.startswith("{") or detail.startswith("["):
        return False
    if detail.count(":") > 4:
        return False
    if "error during generation attempt" in low or "json parse error" in low:
        return False
    if friendly and low in friendly.lower():
        return False
    return True


def _looks_like_unsupported_thinking_error(status_code: Optional[int], provider_message: str) -> bool:
    if status_code != 422:
        return False

    low = (provider_message or "").lower()
    return (
        "thinking" in low
        and (
            "extra_forbidden" in low
            or "extra inputs are not permitted" in low
            or "not permitted" in low
        )
    )


def _friendly_message(status_code: Optional[int], provider_message: str) -> tuple[str, str]:
    low = (provider_message or "").lower()

    if (
        "user location is not supported" in low
        or "location is not supported for the api use" in low
        or "unsupported country" in low
        or "unsupported region" in low
    ):
        return (
            _(
                "Провайдер отклонил запрос по региональному ограничению. Для этого пресета нужен другой провайдер, прокси или маршрут.",
                "The provider rejected the request due to a regional restriction. This preset needs a different provider, proxy, or route.",
            ),
            _("Provider is blocked for this region.", "Provider is blocked for this region."),
        )

    if (
        "provider not configured" in low
        or "api provider not configured" in low
        or "api preset not configured" in low
        or "missing api url" in low
        or "missing api model" in low
        or "no provider can handle this request" in low
    ):
        return (
            _(
                "API-провайдер не настроен. Откройте Настройки -> API и заполните пресет.",
                "The API provider is not configured. Open Settings -> API and complete the preset.",
            ),
            _("Provider configuration is missing.", "Provider configuration is missing."),
        )

    if _looks_like_unsupported_thinking_error(status_code, provider_message):
        return (
            _(
                "Провайдер не поддерживает параметр thinking. Отключите режим мышления для этого пресета.",
                "This provider does not support the thinking parameter. Disable thinking mode for this preset.",
            ),
            _("Unsupported thinking parameter.", "Unsupported thinking parameter."),
        )

    if status_code == 400:
        return (
            _("Ошибка 400 - Проверьте API-ключ и endpoint.", "Error 400 - Check the API key and endpoint."),
            _("Bad request from provider.", "Bad request from provider."),
        )
    if status_code == 401:
        return (
            _("Ошибка 401 - Неверный API-ключ.", "Error 401 - Invalid API key."),
            _("Unauthorized request.", "Unauthorized request."),
        )
    if status_code == 403:
        return (
            _("Ошибка 403 - Нет доступа. Проверьте права API-ключа.", "Error 403 - Access denied. Check API key permissions."),
            _("Access forbidden.", "Access forbidden."),
        )
    if status_code == 404:
        return (
            _("Ошибка 404 - Endpoint не найден.", "Error 404 - Endpoint not found."),
            _("Endpoint not found.", "Endpoint not found."),
        )
    if status_code == 408:
        return (
            _("Ошибка 408 - Сервер не ответил вовремя.", "Error 408 - The server did not respond in time."),
            _("Request timeout.", "Request timeout."),
        )
    if status_code == 429:
        return (
            _("Ошибка 429 - Rate limit. Подождите и повторите позже.", "Error 429 - Rate limit. Wait and try again later."),
            _("Rate limit exceeded.", "Rate limit exceeded."),
        )
    if status_code is not None and 500 <= status_code < 600:
        return (
            _("Ошибка сервера API. Попробуйте позже или смените endpoint.", "API server error. Try again later or change the endpoint."),
            _("Provider server error.", "Provider server error."),
        )

    if "api key" in low or "unauthorized" in low or "invalid key" in low:
        return (
            _("Проверьте API-ключ.", "Check the API key."),
            _("API key issue.", "API key issue."),
        )
    if "endpoint" in low or "not found" in low or "404" in low:
        return (
            _("Проверьте endpoint.", "Check the endpoint."),
            _("Endpoint issue.", "Endpoint issue."),
        )
    if "rate limit" in low or "quota" in low or "too many requests" in low:
        return (
            _("Превышен лимит запросов. Подождите и повторите позже.", "Request limit exceeded. Wait and try again later."),
            _("Rate limit exceeded.", "Rate limit exceeded."),
        )
    if "timed out" in low or "timeout" in low:
        return (
            _("Сервер не ответил вовремя. Попробуйте позже.", "The server did not respond in time. Try again later."),
            _("Request timeout.", "Request timeout."),
        )
    if "connection" in low or "dns" in low or "name resolution" in low:
        return (
            _("Не удалось подключиться к API. Проверьте интернет и endpoint.", "Could not connect to the API. Check the internet connection and endpoint."),
            _("Connection failed.", "Connection failed."),
        )

    return (
        _("Не удалось получить ответ от модели.", "Failed to get a response from the model."),
        _("Unknown provider error.", "Unknown provider error."),
    )


@dataclass
class LLMProviderError(RuntimeError):
    provider: str
    friendly_message: str
    status_code: Optional[int] = None
    provider_message: str = ""
    raw_payload: Any = None
    retryable: bool = False
    retry_after_seconds: Optional[float] = None
    code: Optional[str] = None
    phase: Optional[str] = None
    url: Optional[str] = None

    def __post_init__(self):
        super().__init__(self.friendly_message)

    def to_user_message(self) -> str:
        if _should_surface_provider_message(self.friendly_message, self.provider_message):
            return _(
                "{friendly} Причина: {detail}",
                "{friendly} Reason: {detail}",
            ).format(
                friendly=self.friendly_message,
                detail=mask_sensitive(_compact_text(self.provider_message)),
            )
        return self.friendly_message

    def to_console_summary(self) -> str:
        parts = [f"provider={self.provider}"]
        if self.status_code is not None:
            parts.insert(0, f"HTTP {self.status_code}")
        else:
            parts.insert(0, "Provider error")

        friendly = _compact_text(self.friendly_message)
        detail = mask_sensitive(_compact_text(self.provider_message))
        if friendly:
            parts.append(f"user_message={friendly}")
        if detail:
            parts.append(f"provider_message={detail}")
        if self.phase:
            parts.append(f"phase={self.phase}")
        parts.append(f"retryable={'yes' if self.retryable else 'no'}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after={self.retry_after_seconds:.3f}s")
        if self.url:
            parts.append(f"url={mask_sensitive(self.url)}")
        return " | ".join(parts)

    def to_payload(self) -> dict[str, Any]:
        """Serializable provider failure shared by UI and external clients."""
        return {
            "kind": "provider_error",
            "provider": self.provider,
            "message": self.to_user_message(),
            "reason": mask_sensitive(_compact_text(self.provider_message)),
            "status_code": self.status_code,
            "code": self.code,
            "phase": self.phase,
            "retryable": bool(self.retryable),
            "retry_after_seconds": self.retry_after_seconds,
            "url": mask_sensitive(self.url) if self.url else None,
        }


def build_provider_error(
    provider: str,
    *,
    status_code: Optional[int] = None,
    payload: Any = None,
    provider_message: Optional[str] = None,
    response_headers: Any = None,
    code: Optional[str] = None,
    phase: Optional[str] = None,
    url: Optional[str] = None,
) -> LLMProviderError:
    message = _compact_text(provider_message) or _extract_provider_message(payload)
    if status_code is None:
        status_code = _extract_status_code(message)

    friendly_message, _ = _friendly_message(status_code, message)
    retryable = bool(status_code in _RETRYABLE_STATUS_CODES)
    retry_after_seconds = _extract_retry_after_seconds(
        response_headers=response_headers,
        payload=payload,
        provider_message=message,
    )

    return LLMProviderError(
        provider=provider,
        friendly_message=friendly_message,
        status_code=status_code,
        provider_message=message,
        raw_payload=payload,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        code=code,
        phase=phase,
        url=url,
    )


def build_configuration_error(
    provider: str,
    provider_message: str,
    *,
    url: Optional[str] = None,
) -> LLMProviderError:
    return build_provider_error(
        provider,
        provider_message=provider_message,
        url=url,
    )


def build_stream_error(
    provider: str,
    *,
    payload: Any = None,
    provider_message: Optional[str] = None,
    code: str = "stream.provider_error",
    url: Optional[str] = None,
) -> LLMProviderError:
    status_code = None
    source = payload.get("error", payload) if isinstance(payload, dict) else payload
    if isinstance(source, dict):
        for key in ("status_code", "status", "http_status", "code"):
            try:
                candidate = int(source.get(key))
            except (TypeError, ValueError):
                continue
            if 100 <= candidate <= 599:
                status_code = candidate
                break
    error = build_provider_error(
        provider,
        status_code=status_code,
        payload=payload,
        provider_message=provider_message,
        code=code,
        phase="stream",
        url=url,
    )
    error.retryable = False
    return error


def coerce_provider_error(provider: str, exc: Exception, *, url: Optional[str] = None) -> LLMProviderError:
    if isinstance(exc, LLMProviderError):
        return exc

    transport_error = _find_httpx_transport_error(exc)
    if isinstance(transport_error, httpx.TimeoutException):
        phase = _httpx_error_phase(transport_error)
        return LLMProviderError(
            provider=provider,
            friendly_message=_timeout_friendly_message(phase),
            provider_message=_compact_text(str(transport_error)) or f"{phase or 'network'} timeout",
            retryable=phase in {"connect", "pool"},
            code=f"timeout.{phase or 'network'}",
            phase=phase,
            url=url,
        )

    if isinstance(transport_error, httpx.TransportError):
        phase = _httpx_error_phase(transport_error)
        return LLMProviderError(
            provider=provider,
            friendly_message=_("Ошибка сети - Проверьте интернет и endpoint.", "Network error - Check the internet connection and endpoint."),
            provider_message=_compact_text(str(transport_error)) or "Connection failed",
            retryable=phase in {"connect", "pool"},
            code=f"network.{phase or 'transport'}",
            phase=phase,
            url=url,
        )

    status_code = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    response = getattr(exc, "response", None)

    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    payload = body
    if payload is None and response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = getattr(response, "text", None)

    provider_message = _compact_text(getattr(exc, "message", None)) or _compact_text(str(exc))
    return build_provider_error(
        provider,
        status_code=status_code,
        payload=payload,
        provider_message=provider_message,
        response_headers=getattr(response, "headers", None),
        code=str(code) if code is not None else None,
        url=url,
    )


def _find_httpx_transport_error(exc: BaseException) -> Optional[httpx.TransportError]:
    current: Optional[BaseException] = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, httpx.TransportError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _httpx_error_phase(exc: httpx.TransportError) -> Optional[str]:
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError, httpx.ProxyError)):
        return "connect"
    if isinstance(exc, (httpx.WriteTimeout, httpx.WriteError)):
        return "write"
    if isinstance(exc, (httpx.ReadTimeout, httpx.ReadError)):
        return "read"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool"
    if isinstance(exc, httpx.ProtocolError):
        return "protocol"
    return None


def _timeout_friendly_message(phase: Optional[str]) -> str:
    if phase == "write":
        return _(
            "Ошибка сети - Не удалось отправить запрос вовремя. Возможно, слишком медленная отдача.",
            "Network error - The request could not be uploaded in time. The upload connection may be too slow.",
        )
    if phase == "connect":
        return _(
            "Ошибка сети - Не удалось подключиться к API вовремя.",
            "Network error - Could not connect to the API in time.",
        )
    if phase == "pool":
        return _(
            "Сетевые соединения заняты другими запросами.",
            "Network connections are busy with other requests.",
        )
    return _(
        "Ошибка сети - Сервер не ответил вовремя.",
        "Network error - The server did not respond in time.",
    )
