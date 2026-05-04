from __future__ import annotations

import asyncio
from typing import Any, Callable


class RAGService:
    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event

    async def shutdown(self):
        await asyncio.to_thread(self._shutdown_sync)

    async def handle(self, method: str, payload: dict):
        m = str(method or "").strip().lower()

        if m == "ping":
            return True

        if m == "warmup_embeddings":
            model_name = str(payload.get("model_name") or "").strip()
            query_prefix = str(payload.get("query_prefix") or "")
            return await asyncio.to_thread(self._warmup_embeddings_sync, model_name, query_prefix)

        if m == "get_embeddings":
            texts = payload.get("texts") or []
            model_name = str(payload.get("model_name") or "").strip()
            query_prefix = str(payload.get("query_prefix") or "")
            prefix = payload.get("prefix")
            prefix = query_prefix if prefix is None else str(prefix or "")
            batch_size = payload.get("batch_size")
            return await asyncio.to_thread(
                self._get_embeddings_sync,
                list(texts or []),
                model_name,
                query_prefix,
                prefix,
                batch_size,
            )

        if m == "rerank":
            from handlers.ai_engine.rag_runtime import WorkerCrossEncoderReranker

            model_name = str(payload.get("model_name") or "").strip()
            query = str(payload.get("query") or "")
            candidates = list(payload.get("candidates") or [])
            top_k = int(payload.get("top_k") or 0)
            alpha = float(payload.get("alpha") or 0.0)
            early_exit_score = float(payload.get("early_exit_score") or 0.0)
            total_candidates = int(payload.get("total_candidates") or len(candidates))

            reranker = WorkerCrossEncoderReranker.get(model_name)
            return await asyncio.to_thread(
                reranker.rerank_payload,
                query,
                candidates,
                top_k=top_k,
                alpha=alpha,
                early_exit_score=early_exit_score,
                total_candidates=total_candidates,
            )

        if m == "get_reranker_status":
            from handlers.ai_engine.rag_runtime import WorkerCrossEncoderReranker

            model_name = str(payload.get("model_name") or "").strip()
            return WorkerCrossEncoderReranker.status(model_name)

        raise RuntimeError(f"Unknown rag method: {method}")

    def _warmup_embeddings_sync(self, model_name: str, query_prefix: str) -> bool:
        from handlers.embedding_handler import EmbeddingModelHandler
        from managers.rag.install_spec import TARGET_EMBEDDINGS, ensure_runtime_ready

        ensure_runtime_ready(TARGET_EMBEDDINGS)
        EmbeddingModelHandler.shared(
            model_name=model_name,
            query_prefix=query_prefix,
        )
        return True

    def _get_embeddings_sync(
        self,
        texts: list[str],
        model_name: str,
        query_prefix: str,
        prefix: str,
        batch_size,
    ):
        from handlers.embedding_handler import EmbeddingModelHandler
        from managers.rag.install_spec import TARGET_EMBEDDINGS, ensure_runtime_ready

        ensure_runtime_ready(TARGET_EMBEDDINGS)
        handler = EmbeddingModelHandler.shared(
            model_name=model_name,
            query_prefix=query_prefix,
        )
        bs = 32
        try:
            if batch_size is not None:
                bs = max(1, int(batch_size))
        except Exception:
            bs = 32
        return handler.get_embeddings(list(texts or []), prefix=str(prefix or ""), batch_size=bs)

    def _shutdown_sync(self) -> None:
        from handlers.ai_engine.rag_runtime import shutdown_rag_runtime

        shutdown_rag_runtime()
