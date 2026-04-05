from __future__ import annotations

from threading import Lock, Thread
from typing import List, Optional

import numpy as np

from core.events import get_event_bus, Events, Event
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from handlers.embedding_presets import resolve_model_settings
from main_logger import logger
from managers.settings_manager import SettingsManager


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


EMBED_EVENT_NAME = Events.RAG.GET_EMBEDDING
EMBEDS_EVENT_NAME = Events.RAG.GET_EMBEDDINGS


class EmbeddingController:
    """
    Controller для эмбеддингов (MVP):
    - здесь создаётся ЕДИНЫЙ экземпляр EmbeddingModelHandler
    - все запросы эмбеддингов идут через EventBus
    """

    def __init__(self) -> None:
        self.event_bus = get_event_bus()

        # ВАЖНО: сначала подписываемся на события, и только потом (опционально) прогреваем модель.
        # Иначе во время долгой загрузки модели подписчиков ещё нет -> RAGManager уходит в fallback и грузит вторую копию.
        self.handler: Optional[EmbeddingModelHandler] = None
        self._handler_failed: bool = False  # avoid retrying after permanent load failure

        # Разделяем блокировку инициализации и блокировку инференса,
        # чтобы не словить deadlock при ленивой загрузке.
        self._init_lock = Lock()
        self._infer_lock = Lock()

        self._subscribe_to_events()

        if not SettingsManager.get("RAG_ENABLED", False):
            logger.info("RAG is disabled in settings. EmbeddingModelHandler not loaded.")
            return

        # Опциональный прогрев (в фоне), чтобы первый запрос не блокировал пользователя.
        # По умолчанию включаем, чтобы сохранить прежнее поведение (модель грузилась при старте),
        # но теперь это безопасно относительно подписки.
        preload = SettingsManager.get("RAG_PRELOAD_EMBEDDINGS_MODEL", True)
        if bool(preload):
            Thread(target=self._ensure_handler, daemon=True).start()

    _EMBED_SETTING_KEYS = frozenset({
        "RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM", "RAG_EMBED_QUERY_PREFIX", "HF_TOKEN",
        "RAG_VECTOR_SEARCH_ENABLED",
    })

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(EMBED_EVENT_NAME, self._on_get_embedding, weak=False)
        self.event_bus.subscribe(EMBEDS_EVENT_NAME, self._on_get_embeddings, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self.event_bus.subscribe(Events.RAG.MODEL_CHANGED, self._on_model_changed, weak=False)
        logger.notify(
            f"EmbeddingController подписался на события: {EMBED_EVENT_NAME}, {EMBEDS_EVENT_NAME}"
        )

    def _on_model_changed(self, event) -> None:
        """Handle MODEL_CHANGED: log and optionally re-init handler."""
        data = event.data or {}
        logger.info(f"EmbeddingController: MODEL_CHANGED event received: {data}")

    def _on_setting_changed(self, event: Event) -> None:
        data = event.data or {}
        key = data.get("key", "")
        if key not in self._EMBED_SETTING_KEYS:
            return
        logger.info(f"EmbeddingController: настройка '{key}' изменилась, сбрасываю handler")
        with self._init_lock:
            self.handler = None
            self._handler_failed = False  # allow retry after settings change
        if key in ("RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM"):
            self.event_bus.emit(Events.RAG.MODEL_CHANGED, {
                "key": key,
                "value": data.get("value"),
            })

    def _ensure_handler(self) -> Optional[EmbeddingModelHandler]:
        """
        Ленивая инициализация модели.
        Использует EmbeddingModelHandler.shared(), чтобы гарантировать единственный экземпляр в процессе,
        даже если где-то сработал fallback.
        Читает модель из настроек через пресеты.
        """
        if self._handler_failed:
            return None
        if self.handler is not None:
            return self.handler
        if not SettingsManager.get("RAG_ENABLED", False):
            return None
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", True):
            return None

        with self._init_lock:
            if self.handler is None and not self._handler_failed:
                try:
                    ms = resolve_model_settings()
                    self.handler = EmbeddingModelHandler.shared(
                        model_name=ms["hf_name"],
                        query_prefix=ms["query_prefix"],
                    )
                except Exception as e:
                    logger.error(f"EmbeddingController: не удалось загрузить модель эмбеддингов: {e}", exc_info=True)
                    self._handler_failed = True
                    return None
        return self.handler

    def _on_get_embedding(self, event: Event) -> Optional[np.ndarray]:
        data = event.data or {}
        text = data.get("text") or ""
        prefix = data.get("prefix") or ""
        future = data.get("future")

        # NOTE: lazy init (как в _on_get_embeddings), иначе при выключенном/неуспевшем preload
        # все запросы будут возвращать None и RAG уйдёт в fallback.
        handler = self._ensure_handler()
        if handler is None:
            if future is not None:
                try:
                    future.set_result(None)
                except Exception:
                    pass
            return None

        try:
            with self._infer_lock:
                vec = handler.get_embedding(text, prefix=prefix)

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
        prefix = data.get("prefix") or ""
        batch_size = data.get("batch_size")  # optional
        future = data.get("future")

        handler = self._ensure_handler()
        if handler is None:
            if future is not None:
                try:
                    future.set_result([])
                except Exception:
                    pass
            return []

        results: List[Optional[np.ndarray]] = []
        try:
            # Используем настоящий batch API модели (одна токенизация/forward на батч),
            # это заметно быстрее, чем вызывать get_embedding() в цикле.
            bs = batch_size
            try:
                bs = int(bs) if bs is not None else 32
            except Exception:
                bs = 32

            with self._infer_lock:
                results = handler.get_embeddings(list(texts), prefix=prefix, batch_size=bs)

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