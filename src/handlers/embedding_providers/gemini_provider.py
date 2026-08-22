from __future__ import annotations

import re
import time
from threading import Lock
from typing import List, Optional

import numpy as np

from core.networking import ManagedHttpClient, shared_http_client_registry
from .base import BaseEmbeddingProvider, EmbeddingRequest
from main_logger import logger

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:key|api[_-]?key|apikey|token|access_token)=)[^&\s]+",
    re.IGNORECASE,
)
_HTTP_CLIENT = shared_http_client_registry().acquire(
    "rag-gemini",
    client_options={"follow_redirects": True},
)


def _safe_error_text(exc: BaseException | None, secrets) -> str:
    """Return an exception string safe for logs."""
    if exc is None:
        return "unknown error"
    text = str(exc)
    for secret in secrets or ():
        secret_text = str(secret or "")
        if secret_text:
            text = text.replace(secret_text, "<redacted>")
    return _SECRET_QUERY_RE.sub(r"\1<redacted>", text)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini batchEmbedContents API.

    Supports task_type RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT based on is_query.
    Reserve keys rotated on 429/5xx.
    """
    name = "gemini"
    # Keep REST payloads bounded; RagEmbedder may chunk before this provider too.
    _BATCH_LIMIT = 100

    def __init__(self, http_client: ManagedHttpClient | None = None) -> None:
        self._key_distribution_lock = Lock()
        self._next_key_index = 0
        self._http_client = http_client or _HTTP_CLIENT

    def is_applicable(self, req: EmbeddingRequest) -> bool:
        return bool(req.api_key or req.reserve_keys)

    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        supplied_keys = [req.api_key or ""] + [k for k in (req.reserve_keys or []) if k]
        all_keys = list(dict.fromkeys(k for k in supplied_keys if k))
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
        logger.info(
            f"[EmbedAPI][gemini] model={model} | texts={len(texts)} | batch_limit={self._BATCH_LIMIT}"
        )

        # Process in batches of _BATCH_LIMIT
        for batch_start in range(0, len(texts), self._BATCH_LIMIT):
            batch_texts = texts[batch_start: batch_start + self._BATCH_LIMIT]
            batch_result = self._embed_batch(
                all_keys,
                base_url,
                model,
                task_type,
                batch_texts,
                req,
                initial_key_index=self._initial_key_index(all_keys, req.reserve_keys_distribute),
            )
            for j, vec in enumerate(batch_result):
                results[batch_start + j] = vec

        return results

    def _initial_key_index(self, all_keys, distribute: bool) -> int:
        if not distribute or len(all_keys) <= 1:
            return 0
        with self._key_distribution_lock:
            index = self._next_key_index % len(all_keys)
            self._next_key_index += 1
            return index

    def _embed_batch(
        self,
        all_keys,
        base_url,
        model,
        task_type,
        texts,
        req: EmbeddingRequest,
        *,
        initial_key_index: int = 0,
    ):
        timeout_sec = float((req.extra or {}).get("timeout_sec") or 60.0)
        backoff_sec = float((req.extra or {}).get("retry_backoff_sec") or 0.5)
        max_retries_cfg = int((req.extra or {}).get("max_retries") or 3)
        max_attempts = max(1, max_retries_cfg + 1)
        requests_list = [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]}, "taskType": task_type}
            for t in texts
        ]
        payload = {"requests": requests_list}

        last_exc: Optional[Exception] = None
        for attempt in range(max_attempts):
            key_index = (initial_key_index + attempt) % len(all_keys)
            key = all_keys[key_index]
            # Keep credentials out of URLs because HTTPError strings include response URLs.
            url = f"{base_url}/models/{model}:batchEmbedContents"
            headers = dict(req.headers or {})
            headers["Content-Type"] = "application/json"
            headers["x-goog-api-key"] = key
            try:
                resp = self._http_client.post(url, json=payload, headers=headers, timeout=timeout_sec)

                if resp.status_code in _RETRY_STATUS and attempt < max_attempts - 1:
                    logger.warning(
                        f"[EmbedAPI][gemini] HTTP {resp.status_code} key #{key_index + 1}/{len(all_keys)}, retrying"
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
                logger.warning(f"[EmbedAPI][gemini] attempt {attempt+1} failed: {_safe_error_text(e, all_keys)}")
                if attempt < max_attempts - 1:
                    time.sleep(backoff_sec * (2 ** attempt))
                    continue

        logger.error(f"[EmbedAPI][gemini] all attempts failed. Last: {_safe_error_text(last_exc, all_keys)}")
        return [None] * len(texts)
