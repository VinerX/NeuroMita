from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from core.networking import ManagedHttpClient, shared_http_client_registry
from .base import BaseEmbeddingProvider, EmbeddingRequest
from main_logger import logger

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_HTTP_CLIENT = shared_http_client_registry().acquire(
    "rag-openai-compatible",
    client_options={"follow_redirects": True},
)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI /embeddings endpoint (batch supported).

    Works for: OpenRouter, any OpenAI-compatible local server (ollama, vLLM, llama.cpp), etc.
    """
    name = "openai_compat"

    def __init__(self, http_client: ManagedHttpClient | None = None) -> None:
        self._http_client = http_client or _HTTP_CLIENT

    def is_applicable(self, req: EmbeddingRequest) -> bool:
        return bool(req.api_url)

    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        all_keys = [req.api_key or ""] + [k for k in (req.reserve_keys or []) if k]

        url = req.api_url.rstrip("/")
        # If url already ends with /embeddings keep it, otherwise append
        if not url.endswith("/embeddings"):
            url = url + "/embeddings"

        texts = req.texts
        if not texts:
            return []
        timeout_sec = float((req.extra or {}).get("timeout_sec") or 60.0)
        backoff_sec = float((req.extra or {}).get("retry_backoff_sec") or 0.5)
        max_retries_cfg = int((req.extra or {}).get("max_retries") or 3)

        # Prepend query prefix when is_query
        if req.is_query and req.query_prefix:
            texts = [req.query_prefix + t for t in texts]

        payload: dict = {
            "model": req.model,
            "input": texts,
            "encoding_format": "float",
        }
        if req.dimensions:
            payload["dimensions"] = req.dimensions

        logger.info(
            f"[EmbedAPI][openai_compat] model={req.model} | url={url} | texts={len(texts)}"
        )
        last_exc: Optional[Exception] = None
        max_attempts = max(1, max_retries_cfg + 1)
        for attempt in range(max_attempts):
            key = all_keys[attempt % len(all_keys)]
            headers = {
                "Content-Type": "application/json",
                **req.headers,
            }
            if key:
                headers["Authorization"] = f"Bearer {key}"

            try:
                resp = self._http_client.post(url, json=payload, headers=headers, timeout=timeout_sec)

                if resp.status_code in _RETRY_STATUS and attempt < max_attempts - 1:
                    logger.warning(
                        f"[EmbedAPI][openai_compat] HTTP {resp.status_code} key #{attempt+1}, retrying"
                    )
                    retry_after = resp.headers.get("Retry-After") if "resp" in locals() else None
                    try:
                        delay = float(retry_after) if retry_after else backoff_sec * (2 ** attempt)
                    except (TypeError, ValueError):
                        delay = backoff_sec * (2 ** attempt)
                    time.sleep(delay)
                    continue

                self._http_client.raise_for_status(resp)
                data = resp.json()
                items = data.get("data") or []
                # sort by index to preserve order
                items_sorted = sorted(items, key=lambda x: x.get("index", 0))
                results: List[Optional[np.ndarray]] = []
                for item in items_sorted:
                    raw = item.get("embedding")
                    if raw is None:
                        results.append(None)
                    else:
                        vec = np.array(raw, dtype=np.float32)
                        results.append(_l2_normalize(vec))
                return results

            except Exception as e:
                last_exc = e
                logger.warning(
                    f"[EmbedAPI][openai_compat] attempt {attempt+1} failed: {e}"
                )
                if attempt < max_attempts - 1:
                    time.sleep(backoff_sec * (2 ** attempt))
                    continue

        logger.error(f"[EmbedAPI][openai_compat] all attempts failed. Last error: {last_exc}", exc_info=True)
        return [None] * len(req.texts)
