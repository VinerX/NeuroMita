from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Optional

from main_logger import logger
from services.contracts import AIEngineService


class InProcessAIEngine(AIEngineService):
    """Синхронный in-process движок для headless-контекстов (RAG-тестер, offline-CLI),
    где отдельный engine-процесс не поднимается.

    Выполняет rag-методы прямо в текущем процессе через те же ``RAGService._*_sync``
    обработчики, что и worker, — поэтому векторы/реранк идентичны боевым. Пригоден
    только там, где backend (torch/transformers) импортируется напрямую (Venv).

    В боевом приложении НЕ используется: там в ServiceRegistry регистрируется
    настоящий ``AIEngineController`` с worker-процессами.
    """

    def __init__(self) -> None:
        self._rag = None

    def _rag_service(self):
        if self._rag is None:
            from handlers.ai_engine.services.rag_service import RAGService

            self._rag = RAGService(emit_event=lambda *a, **k: None)
        return self._rag

    # AIEngineService API ---------------------------------------------------
    def get_engine(self) -> "InProcessAIEngine":
        return self

    def call(
        self,
        service: str,
        method: str,
        payload: Optional[dict] = None,
        *,
        timeout: float | None = None,
    ) -> Future:
        f: Future = Future()
        try:
            f.set_result(self._dispatch(service, method, payload or {}))
        except Exception as e:  # noqa: BLE001 — future переносит исключение вызывающему
            f.set_exception(e)
        return f

    def wait_ready(self, service: str, timeout: float = 3.0) -> bool:
        return str(service or "").strip().lower() == "rag"

    # ----------------------------------------------------------------------
    def _dispatch(self, service: str, method: str, payload: dict) -> Any:
        s = str(service or "").strip().lower()
        m = str(method or "").strip().lower()
        if s != "rag":
            raise RuntimeError(f"InProcessAIEngine: сервис '{service}' не поддерживается")

        rag = self._rag_service()

        if m == "ping":
            return True

        if m == "get_embeddings":
            query_prefix = str(payload.get("query_prefix") or "")
            prefix = payload.get("prefix")
            prefix = query_prefix if prefix is None else str(prefix or "")
            return rag._get_embeddings_sync(
                list(payload.get("texts") or []),
                str(payload.get("model_name") or "").strip(),
                query_prefix,
                prefix,
                payload.get("batch_size"),
            )

        if m == "rerank":
            candidates = list(payload.get("candidates") or [])
            return rag._rerank_sync(
                str(payload.get("model_name") or "").strip(),
                str(payload.get("query") or ""),
                candidates,
                int(payload.get("top_k") or 0),
                float(payload.get("alpha") or 0.0),
                float(payload.get("early_exit_score") or 0.0),
                int(payload.get("total_candidates") or len(candidates)),
            )

        if m == "get_reranker_status":
            return rag._reranker_status_sync(str(payload.get("model_name") or "").strip())

        if m == "warmup_embeddings":
            return rag._warmup_embeddings_sync(
                str(payload.get("model_name") or "").strip(),
                str(payload.get("query_prefix") or ""),
            )

        if m == "warmup_reranker":
            return rag._warmup_reranker_sync(str(payload.get("model_name") or "").strip())

        raise RuntimeError(f"InProcessAIEngine: неизвестный rag-метод '{method}'")


def register_inprocess_engine() -> InProcessAIEngine:
    """Регистрирует in-process движок как AIEngineService для headless-контекста.

    Если уже зарегистрирован живой движок (боевой AIEngineController) — ничего не
    делает и возвращает его. Идемпотентна.
    """
    from core.services import services
    from services.contracts import AIEngineService

    existing = services().get_optional(AIEngineService)
    if existing is not None:
        try:
            if existing.get_engine() is not None and not isinstance(existing, InProcessAIEngine):
                return existing  # боевой движок уже поднят — не подменяем
        except Exception:
            pass
        if isinstance(existing, InProcessAIEngine):
            return existing

    engine = InProcessAIEngine()
    services().register(AIEngineService, engine, replace=True)
    logger.info("InProcessAIEngine зарегистрирован как AIEngineService (headless-режим)")
    return engine
