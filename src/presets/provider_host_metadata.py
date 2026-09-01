from __future__ import annotations

from urllib.parse import urlparse


_RUB_HOST_SUFFIXES = (
    "proxyapi.ru",
    "kodikrouter.ru",
)


def infer_provider_currency(api_url: str, explicit_currency: str = "") -> str:
    currency = str(explicit_currency or "").strip().upper()
    if currency:
        return currency

    host = urlparse(str(api_url or "")).netloc.lower()
    for suffix in _RUB_HOST_SUFFIXES:
        if host == suffix or host.endswith(f".{suffix}"):
            return "RUB"
    return ""
