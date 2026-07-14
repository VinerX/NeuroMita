from __future__ import annotations

from typing import Any, Optional


def get_engine(timeout: float = 0.8):
    # Через типизированный сервис, а не sync EventBus RPC: get_embeddings зовётся на
    # hot-path (пул 'generation'), где синхронный сбор ответов шины запрещён
    # guardrail'ом. timeout сохранён для совместимости сигнатуры, но не нужен.
    try:
        from core.services import use
        from services.contracts import AIEngineService
        return use(AIEngineService).get_engine()
    except Exception:
        return None


def _call(method: str, payload: Optional[dict] = None, *, timeout_sec: float = 30.0):
    engine = get_engine()
    if engine is None:
        raise RuntimeError("AI engine not available")
    future = engine.call("rag", method, payload or {})
    return future.result(timeout=max(1.0, float(timeout_sec or 0.0)))


def warmup_embeddings(model_name: str, query_prefix: str = "", *, timeout_sec: float = 3600.0) -> bool:
    return bool(
        _call(
            "warmup_embeddings",
            {
                "model_name": str(model_name or ""),
                "query_prefix": str(query_prefix or ""),
            },
            timeout_sec=timeout_sec,
        )
    )


def get_embeddings(
    texts: list[str],
    *,
    model_name: str,
    query_prefix: str = "",
    prefix: str = "",
    batch_size: Optional[int] = None,
    timeout_sec: Optional[float] = None,
    priority: str = "hot",
):
    """priority: "hot" — эмбеддинг запроса пользователя (его ждёт ответ Миты),
    "bulk" — фоновая индексация, уступает hot в очереди к устройству."""
    n = len(texts or [])
    if timeout_sec is None:
        timeout_sec = max(30.0, min(3600.0, float(max(1, n)) * 20.0))
    res = _call(
        "get_embeddings",
        {
            "texts": list(texts or []),
            "model_name": str(model_name or ""),
            "query_prefix": str(query_prefix or ""),
            "prefix": str(prefix or ""),
            "batch_size": batch_size,
            "priority": str(priority or "hot"),
        },
        timeout_sec=timeout_sec,
    )
    return res if isinstance(res, list) else []


def rerank_candidates(
    *,
    model_name: str,
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    alpha: float,
    early_exit_score: float,
    total_candidates: int,
    timeout_sec: Optional[float] = None,
) -> dict[str, Any]:
    n = len(candidates or [])
    if timeout_sec is None:
        timeout_sec = max(30.0, min(3600.0, float(max(1, n)) * 10.0))
    res = _call(
        "rerank",
        {
            "model_name": str(model_name or ""),
            "query": str(query or ""),
            "candidates": list(candidates or []),
            "top_k": int(top_k or 0),
            "alpha": float(alpha or 0.0),
            "early_exit_score": float(early_exit_score or 0.0),
            "total_candidates": int(total_candidates or 0),
        },
        timeout_sec=timeout_sec,
    )
    return res if isinstance(res, dict) else {}


def get_reranker_status(model_name: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    res = _call(
        "get_reranker_status",
        {"model_name": str(model_name or "")},
        timeout_sec=timeout_sec,
    )
    return res if isinstance(res, dict) else {}
