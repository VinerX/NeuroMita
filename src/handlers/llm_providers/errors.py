from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

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
    if payload is None:
        return ""

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            for key in ("message", "detail", "error", "title", "type"):
                text = _compact_text(err.get(key))
                if text:
                    return text
        elif err:
            text = _compact_text(err)
            if text:
                return text

        for key in ("message", "detail", "error_description", "title"):
            text = _compact_text(payload.get(key))
            if text:
                return text

    return _compact_text(payload)


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
    code: Optional[str] = None
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
        parts.append(f"retryable={'yes' if self.retryable else 'no'}")
        if self.url:
            parts.append(f"url={mask_sensitive(self.url)}")
        return " | ".join(parts)


def build_provider_error(
    provider: str,
    *,
    status_code: Optional[int] = None,
    payload: Any = None,
    provider_message: Optional[str] = None,
    code: Optional[str] = None,
    url: Optional[str] = None,
) -> LLMProviderError:
    message = _compact_text(provider_message) or _extract_provider_message(payload)
    if status_code is None:
        status_code = _extract_status_code(message)

    friendly_message, _ = _friendly_message(status_code, message)
    retryable = bool(status_code in _RETRYABLE_STATUS_CODES)

    return LLMProviderError(
        provider=provider,
        friendly_message=friendly_message,
        status_code=status_code,
        provider_message=message,
        raw_payload=payload,
        retryable=retryable,
        code=code,
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


def coerce_provider_error(provider: str, exc: Exception, *, url: Optional[str] = None) -> LLMProviderError:
    if isinstance(exc, LLMProviderError):
        return exc

    if isinstance(exc, requests.Timeout):
        return LLMProviderError(
            provider=provider,
            friendly_message=_("Ошибка сети - Сервер не ответил вовремя.", "Network error - The server did not respond in time."),
            provider_message=_compact_text(str(exc)) or "Request timed out",
            retryable=True,
            url=url,
        )

    if isinstance(exc, requests.ConnectionError):
        return LLMProviderError(
            provider=provider,
            friendly_message=_("Ошибка сети - Проверьте интернет и endpoint.", "Network error - Check the internet connection and endpoint."),
            provider_message=_compact_text(str(exc)) or "Connection failed",
            retryable=True,
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
        code=str(code) if code is not None else None,
        url=url,
    )
