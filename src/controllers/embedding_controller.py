from __future__ import annotations

from threading import Lock
from typing import List, Optional

import numpy as np

from core.events import get_event_bus, Events, Event
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from main_logger import logger


def _resolve_event_name(fallback: str, *path: str) -> str:
    """
    Пытается достать событие из Events по цепочке атрибутов (например Events.RAG.GET_EMBEDDING).
    Если такого нет — возвращает fallback-строку.
    """
    try:
        obj = Events
        for p in path:
            obj = getattr(obj, p)
        return obj
    except Exception:
        return fallback


EMBED_EVENT_NAME = _resolve_event_name("rag.get_embedding", "RAG", "GET_EMBEDDING")
EMBEDS_EVENT_NAME = _resolve_event_name("rag.get_embeddings", "RAG", "GET_EMBEDDINGS")


class EmbeddingController:
    """
    Controller для эмбеддингов (MVP):
    - здесь создаётся ЕДИНЫЙ экземпляр EmbeddingModelHandler
    - все запросы эмбеддингов идут через EventBus
    """

    def __init__(self) -> None:
        self.event_bus = get_event_bus()

        # Единый экземпляр handler создаётся здесь (а не в менеджерах)
        self.handler = EmbeddingModelHandler()

        # Чтобы не дергать модель параллельно из разных потоков EventBus
        self._lock = Lock()

        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(EMBED_EVENT_NAME, self._on_get_embedding, weak=False)
        self.event_bus.subscribe(EMBEDS_EVENT_NAME, self._on_get_embeddings, weak=False)
        logger.notify(
            f"EmbeddingController подписался на события: {EMBED_EVENT_NAME}, {EMBEDS_EVENT_NAME}"
        )

    def _on_get_embedding(self, event: Event) -> Optional[np.ndarray]:
        data = event.data or {}
        text = data.get("text") or ""
        prefix = data.get("prefix") or QUERY_PREFIX
        future = data.get("future")

        try:
            with self._lock:
                vec = self.handler.get_embedding(text, prefix=prefix)

            if future is not None:
                try:
                    future.set_result(vec)
                except Exception:
                    pass

            return vec
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка get_embedding: {e}", exc_info=True)
            if future is not None:
                try:
                    future.set_result(None)
                except Exception:
                    pass
            return None

    def _on_get_embeddings(self, event: Event) -> List[Optional[np.ndarray]]:
        """
        Batch-запрос: полезно для RAG index_all_missing, чтобы уменьшить overhead EventBus.
        """
        data = event.data or {}
        texts = data.get("texts") or []
        prefix = data.get("prefix") or QUERY_PREFIX
        batch_size = data.get("batch_size")  # optional
        future = data.get("future")

        results: List[Optional[np.ndarray]] = []
        try:
            with self._lock:
                for t in texts:
                    results.append(self.handler.get_embedding(t or "", prefix=prefix))

            if future is not None:
                try:
                    future.set_result(results)
                except Exception:
                    pass

            return results
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка get_embeddings: {e}", exc_info=True)
            if future is not None:
                try:
                    future.set_result([])
                except Exception:
                    pass
            return []