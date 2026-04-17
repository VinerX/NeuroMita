from __future__ import annotations

import time
from typing import List, Optional

import numpy as np

from .base import BaseEmbeddingProvider, EmbeddingRequest
from main_logger import logger

_RETRY_STATUS = {429, 500, 502, 503}
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini batchEmbedContents API.

    Supports task_type RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT based on is_query.
    Reserve keys rotated on 429/5xx.
    """
    name = "gemini"
    # Gemini API limit: 100 texts per batchEmbedContents call
    _BATCH_LIMIT = 100

    def is_applicable(self, req: EmbeddingRequest) -> bool:
        return bool(req.api_key or req.reserve_keys)

    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        import requests as _req

        all_keys = [req.api_key or ""] + [k for k in (req.reserve_keys or []) if k]
        all_keys = [k for k in all_keys if k]  # drop blanks
        if not all_keys:
            logger.error("GeminiEmbeddingProvider: no API key provided")
            return [None] * len(req.texts)

        base_url = (req.api_url or _GEMINI_BASE).rstrip("/")
        model = req.model or "text-embedding-004"
        task_type = "RETRIEVAL_QUERY" if req.is_query else "RETRIEVAL_DOCUMENT"

        texts = req.texts
        if not texts:
            return []

        results: List[Optional[np.ndarray]] = [None] * len(texts)

        # Process in batches of _BATCH_LIMIT
        for batch_start in range(0, len(texts), self._BATCH_LIMIT):
            batch_texts = texts[batch_start: batch_start + self._BATCH_LIMIT]
            batch_result = self._embed_batch(
                _req, all_keys, base_url, model, task_type, batch_texts
            )
            for j, vec in enumerate(batch_result):
                results[batch_start + j] = vec

        return results

    def _embed_batch(self, requests_lib, all_keys, base_url, model, task_type, texts):
        requests_list = [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]}, "taskType": task_type}
            for t in texts
        ]
        payload = {"requests": requests_list}

        last_exc: Optional[Exception] = None
        for attempt, key in enumerate(all_keys):
            url = f"{base_url}/models/{model}:batchEmbedContents?key={key}"
            headers = {"Content-Type": "application/json"}
            try:
                resp = requests_lib.post(url, json=payload, headers=headers, timeout=60)

                if resp.status_code in _RETRY_STATUS and attempt < len(all_keys) - 1:
                    logger.warning(
                        f"GeminiEmbedding: HTTP {resp.status_code} key #{attempt+1}, retrying reserve key"
                    )
                    time.sleep(0.5)
                    continue

                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings") or []
                batch_results = []
                for emb in embeddings:
                    vals = emb.get("values")
                    if vals is None:
                        batch_results.append(None)
                    else:
                        vec = np.array(vals, dtype=np.float32)
                        batch_results.append(_l2_normalize(vec))
                # Pad with None if API returned fewer than requested
                while len(batch_results) < len(texts):
                    batch_results.append(None)
                return batch_results

            except Exception as e:
                last_exc = e
                logger.warning(f"GeminiEmbedding: attempt {attempt+1} failed: {e}")
                if attempt < len(all_keys) - 1:
                    time.sleep(0.5)
                    continue

        logger.error(f"GeminiEmbedding: all attempts failed. Last: {last_exc}", exc_info=True)
        return [None] * len(texts)
