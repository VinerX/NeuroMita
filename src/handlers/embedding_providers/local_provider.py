from __future__ import annotations

from typing import List, Optional

import numpy as np

from .base import BaseEmbeddingProvider, EmbeddingRequest
from main_logger import logger


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """Delegates to EmbeddingModelHandler (sentence_transformers).

    api_url field carries the HF id or local filesystem path to the model.
    """
    name = "local"

    def is_applicable(self, req: EmbeddingRequest) -> bool:
        return True  # always last-resort fallback

    def embed(self, req: EmbeddingRequest) -> List[Optional[np.ndarray]]:
        from handlers.embedding_handler import EmbeddingModelHandler

        model_id = (req.api_url or "").strip() or (req.model or "").strip()
        prefix = req.query_prefix if req.is_query else ""

        try:
            handler = EmbeddingModelHandler.shared(
                model_name=model_id,
                query_prefix=req.query_prefix,
            )
        except Exception as e:
            logger.error(f"LocalEmbeddingProvider: failed to load model '{model_id}': {e}", exc_info=True)
            return [None] * len(req.texts)

        return handler.get_embeddings(req.texts, prefix=prefix)
