from __future__ import annotations

from typing import Any, Dict

from .base import BaseEmbeddingProvider, EmbeddingRequest
from .local_provider import LocalEmbeddingProvider
from .openai_compat_provider import OpenAICompatibleEmbeddingProvider
from .gemini_provider import GeminiEmbeddingProvider


class EmbeddingProviderError(RuntimeError):
    pass


_PROVIDERS: Dict[str, BaseEmbeddingProvider] = {
    "local": LocalEmbeddingProvider(),
    "openai_compat": OpenAICompatibleEmbeddingProvider(),
    "gemini": GeminiEmbeddingProvider(),
}


def get_provider_for(cfg: Dict[str, Any]) -> BaseEmbeddingProvider:
    """Return the right provider based on cfg['provider_name']."""
    name = str(cfg.get("provider_name") or "local").strip()
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise EmbeddingProviderError(f"Unknown embedding provider: {name}")
    return provider


def build_request(cfg: Dict[str, Any], texts: list, is_query: bool = False) -> EmbeddingRequest:
    """Build an EmbeddingRequest from a resolved config dict."""
    return EmbeddingRequest(
        texts=texts,
        is_query=is_query,
        model=str(cfg.get("model") or cfg.get("hf_name") or ""),
        api_key=cfg.get("api_key") or cfg.get("key") or None,
        api_url=cfg.get("api_url") or cfg.get("url") or cfg.get("hf_name") or None,
        reserve_keys=list(cfg.get("reserve_keys") or []),
        reserve_keys_distribute=bool(cfg.get("reserve_keys_distribute", False)),
        headers=dict(cfg.get("headers") or {}),
        query_prefix=str(cfg.get("query_prefix") or ""),
        dimensions=int(cfg.get("dimensions") or 0),
        extra=dict(cfg.get("extra") or {}),
    )
