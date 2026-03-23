"""Cross-encoder reranker for RAG pipeline (optional second pass).

Loads a sequence-classification model (e.g. ms-marco-MiniLM-L-6-v2) that
scores (query, passage) pairs with a single relevance logit.  Runs on the
top-K candidates returned by the first LinearReranker pass and replaces
their scores in-place.

Model is loaded lazily and cached as a per-model-name singleton so it is
loaded at most once per process (same pattern as EmbeddingModelHandler).
"""
from __future__ import annotations

import os
import sys
from threading import Lock
from typing import Optional

from main_logger import logger


def _checkpoints_dir() -> str:
    return os.path.join(os.path.dirname(sys.executable), "checkpoints")


class CrossEncoderReranker:
    """Singleton per model_name.  Call CrossEncoderReranker.get(name)."""

    _instances: dict[str, "CrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._load_lock = Lock()
        self._failed = False  # skip retries after a permanent failure

    # ------------------------------------------------------------------ #
    @classmethod
    def get(cls, model_name: str) -> "CrossEncoderReranker":
        if model_name not in cls._instances:
            with cls._cls_lock:
                if model_name not in cls._instances:
                    cls._instances[model_name] = cls(model_name)
        return cls._instances[model_name]

    # ------------------------------------------------------------------ #
    def _ensure_loaded(self) -> bool:
        """Lazy load; returns True if model is ready."""
        if self._model is not None:
            return True
        if self._failed:
            return False
        with self._load_lock:
            if self._model is not None:
                return True
            if self._failed:
                return False
            try:
                from transformers import AutoTokenizer, AutoModelForSequenceClassification
                import torch

                cache_dir = _checkpoints_dir()
                logger.info(
                    f"[CrossEncoder] Loading '{self.model_name}' "
                    f"(cache: {cache_dir}) ..."
                )
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name, cache_dir=cache_dir
                )
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_name, cache_dir=cache_dir
                )
                self._model.eval()
                logger.info(f"[CrossEncoder] Model '{self.model_name}' ready.")
                return True
            except Exception as exc:
                logger.warning(
                    f"[CrossEncoder] Failed to load '{self.model_name}': {exc} "
                    "(cross-encoder reranking disabled)"
                )
                self._failed = True
                return False

    # ------------------------------------------------------------------ #
    def rerank(self, query: str, cands: list, top_k: int = 20) -> None:
        """Re-score cands[:top_k] in-place with cross-encoder logits.

        After this call the caller should re-sort cands by score.
        Candidates beyond top_k are left untouched (their original linear
        scores are kept so they stay below the re-ranked ones).
        """
        if not cands or not query:
            return
        if not self._ensure_loaded():
            return

        import torch

        to_score = cands[:top_k]
        pairs = [(query, str(c.content or "")) for c in to_score]

        try:
            enc = self._tokenizer(
                [p[0] for p in pairs],
                [p[1] for p in pairs],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**enc).logits  # (N, num_labels)

            # For binary models (num_labels=2) take positive-class logit;
            # for single-output models (num_labels=1) squeeze directly.
            if logits.shape[-1] == 1:
                raw = logits.squeeze(-1)
            else:
                raw = logits[:, -1]  # last logit = "relevant" class

            scores = raw.tolist()
            for c, s in zip(to_score, scores):
                c.score = float(s)
                if c.debug is None:
                    c.debug = {}
                c.debug["cross_encoder"] = float(s)

            logger.debug(
                f"[CrossEncoder] Re-scored {len(to_score)}/{len(cands)} candidates "
                f"(top score={max(scores):.3f})"
            )
        except Exception as exc:
            logger.warning(f"[CrossEncoder] predict failed (ignored): {exc}")
