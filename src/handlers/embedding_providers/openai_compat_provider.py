from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from .base import BaseEmbeddingProvider, EmbeddingRequest
from main_logger import logger

_RETRY_STATUS = {401, 429, 500, 502, 503}


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI /embeddings endpoint (batch supported).

    Works for: OpenRouter, any OpenAI-compatible local server (ollama, vLLM, llama.cpp), etc.
    """
    name = "openai_compat"

    def is_applicable(self, req: EmbeddingRequest) -> bool:
        return bool(req.api_url)

    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        import requests as _req

        all_keys = [req.api_key or ""] + [k for k in (req.reserve_keys or []) if k]

        url = req.api_url.rstrip("/")
        # If url already ends with /embeddings keep it, otherwise append
        if not url.endswith("/embeddings"):
            url = url + "/embeddings"

        texts = req.texts
        if not texts:
            return []

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

        last_exc: Optional[Exception] = None
        for attempt, key in enumerate(all_keys):
            headers = {
                "Content-Type": "application/json",
                **req.headers,
            }
            if key:
                headers["Authorization"] = f"Bearer {key}"

            try:
                resp = _req.post(url, json=payload, headers=headers, timeout=60)

                if resp.status_code in _RETRY_STATUS and attempt < len(all_keys) - 1:
                    logger.warning(
                        f"OpenAICompatEmbedding: HTTP {resp.status_code} with key #{attempt+1}, retrying with reserve key"
                    )
                    time.sleep(0.5)
                    continue

                resp.raise_for_status()
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
                    f"OpenAICompatEmbedding: attempt {attempt+1} failed: {e}"
                )
                if attempt < len(all_keys) - 1:
                    time.sleep(0.5)
                    continue

        logger.error(f"OpenAICompatEmbedding: all attempts failed. Last error: {last_exc}", exc_info=True)
        return [None] * len(req.texts)
