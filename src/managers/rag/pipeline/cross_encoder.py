"""AI-engine proxy for the optional RAG cross-encoder reranker."""
from __future__ import annotations

from threading import Lock

from handlers.ai_engine.rag_client import rerank_candidates
from main_logger import logger


class CrossEncoderReranker:
    """Singleton per model_name. Call CrossEncoderReranker.get(name)."""

    _instances: dict[str, "CrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()

    def __init__(self, model_name: str) -> None:
        self.model_name = str(model_name or "")
        self._model = None
        self._failed = False
        self._load_lock = Lock()

    @classmethod
    def get(cls, model_name: str) -> "CrossEncoderReranker":
        model_name = str(model_name or "")
        if model_name not in cls._instances:
            with cls._cls_lock:
                if model_name not in cls._instances:
                    cls._instances[model_name] = cls(model_name)
        return cls._instances[model_name]

    def rerank(
        self,
        query: str,
        cands: list,
        top_k: int = 20,
        alpha: float = 1.0,
        early_exit_score: float = 1.1,
    ) -> None:
        if not cands or not query:
            return

        top_k = min(len(cands), max(1, int(top_k or 1)))
        payload_candidates = []
        for candidate in cands[:top_k]:
            payload_candidates.append(
                {
                    "source": getattr(candidate, "source", ""),
                    "id": getattr(candidate, "id", 0),
                    "content": getattr(candidate, "content", ""),
                    "score": float(getattr(candidate, "score", 0.0) or 0.0),
                    "debug": dict(getattr(candidate, "debug", {}) or {}),
                }
            )

        try:
            result = rerank_candidates(
                model_name=self.model_name,
                query=str(query or ""),
                candidates=payload_candidates,
                top_k=top_k,
                alpha=float(alpha or 0.0),
                early_exit_score=float(early_exit_score or 0.0),
                total_candidates=len(cands),
            )
        except Exception as exc:
            logger.warning(f"[CrossEncoder] AI engine rerank failed (ignored): {exc}")
            self._failed = True
            return

        updates = result.get("updates") if isinstance(result, dict) else None
        if not isinstance(updates, list):
            updates = []

        for update in updates:
            try:
                idx = int(update.get("index", -1))
            except Exception:
                idx = -1
            if idx < 0 or idx >= top_k:
                continue

            candidate = cands[idx]
            try:
                candidate.score = float(update.get("score", candidate.score) or 0.0)
            except Exception:
                pass
            try:
                ce_score = float(update.get("cross_encoder"))
                if getattr(candidate, "debug", None) is None:
                    candidate.debug = {}
                candidate.debug["cross_encoder"] = ce_score
            except Exception:
                pass

        if bool(result.get("loaded", False)):
            with self._load_lock:
                self._model = True
                self._failed = False
