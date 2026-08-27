"""Слой получения эмбеддингов RAG (этап 2 декомпозиции RAGManager).

`RagEmbedder` инкапсулирует ВЫЧИСЛЕНИЕ векторов и запись их в BLOB:
резолв активной конфигурации эмбеддингов, hot-path через `EmbeddingService`
(мост к AI-engine) с фолбэком на провайдер-систему, батчинг и кодирование
в bytes для SQLite. Не знает про history/memory-таблицы — это разделяемый
фундамент, на который опираются индексация и ретрив.

Поведение перенесено 1:1 из соответствующих приватных методов RAGManager;
RAGManager держит тонкие делегаторы ради обратной совместимости внутренних
вызовов (см. rag_manager.py).
"""
from __future__ import annotations
from core.error_utils import format_exception

import time as _time
from typing import List, Optional

import numpy as np

from core.services import use
from handlers.embedding_presets import resolve_full_config
from main_logger import logger
from managers.rag.rag_utils import rag_clean_text
from managers.settings_manager import SettingsManager
from services.contracts import EmbeddingService


class RagEmbedder:
    """Вычисление эмбеддингов и кодирование их в BLOB. Без состояния персонажа."""

    # --- активная конфигурация ------------------------------------------- #
    def current_model_name(self) -> str:
        """DB-ключ для тегирования строк эмбеддингов (provider:model или голый hf_name)."""
        cfg = resolve_full_config()
        return str(cfg.get("db_model_key") or cfg.get("hf_name") or cfg.get("model") or "")

    def current_dimensions(self) -> int:
        cfg = resolve_full_config()
        return int(cfg.get("dimensions") or 0)

    # --- кодек ------------------------------------------------------------ #
    def array_to_blob(self, array: np.ndarray) -> bytes:
        """Конвертирует numpy array в байты для сохранения."""
        return array.astype(np.float32).tobytes()

    # --- провайдерный путь ------------------------------------------------ #
    def embed_via_provider(
        self,
        texts: List[str],
        is_query: bool = False,
        prefix: str = "",
    ) -> List[Optional[np.ndarray]]:
        """Embed texts through the configured embedding provider."""
        from handlers.embedding_providers.registry import get_provider_for, build_request

        cfg = resolve_full_config()
        if prefix:
            cfg = dict(cfg)
            cfg["query_prefix"] = prefix
        provider = get_provider_for(cfg)
        req = build_request(cfg, texts=texts, is_query=is_query)
        return provider.embed(req)

    # --- получение векторов ---------------------------------------------- #
    def get_embedding(self, text: str, prefix: str = "", use_event_bus: bool = True) -> Optional[np.ndarray]:
        """
        1) Пытаемся получить эмбеддинг через EventBus (EmbeddingController).
        2) Если не вышло — fallback на Singleton EmbeddingModelHandler().
        """
        if not text or not SettingsManager.get("RAG_ENABLED", False):
            return None
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", False):
            return None

        # Очистка от тегов
        text = rag_clean_text(text)
        cfg = resolve_full_config()
        provider_name = str(cfg.get("provider_name") or "local").strip().lower()
        can_use_local_service = bool(use_event_bus and provider_name == "local")
        logger.debug(
            f"[RAG][embed_one] provider={provider_name} | model={cfg.get('db_model_key') or cfg.get('model') or cfg.get('hf_name')}"
        )

        if can_use_local_service:
            try:
                vec = use(EmbeddingService).embed_one(text, prefix)
                if vec is not None:
                    return vec
            except Exception as e:
                # Не валим RAG из-за сервиса — просто откатываемся на прямой вызов провайдера
                logger.warning(f"RAGManager: EmbeddingService не сработал, fallback на провайдер. Причина: {format_exception(e)}")

        try:
            results = self.embed_via_provider([text], is_query=bool(prefix), prefix=prefix)
            return results[0] if results else None
        except Exception as e:
            logger.error(f"RAGManager: ошибка провайдера эмбеддинга: {format_exception(e)}", exc_info=True)
            return None

    def get_embeddings(
        self,
        texts: List[str],
        prefix: str = "",
        use_event_bus: bool = True,
        batch_size: Optional[int] = None,
        allow_when_rag_disabled: bool = False,
        priority: str = "hot",
    ) -> List[Optional[np.ndarray]]:
        """
        Массовое получение эмбеддингов:
        1) EventBus batch (rag.get_embeddings) — меньше overhead и lock'ов.
        2) Fallback на ленивый singleton EmbeddingModelHandler, если EventBus недоступен.
        """
        if not texts:
            return []
        if (not allow_when_rag_disabled) and (not SettingsManager.get("RAG_ENABLED", False)):
            return []
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", False):
            return [None] * len(texts)

        cleaned: List[str] = []
        for t in texts:
            if not t:
                cleaned.append("")
            else:
                cleaned.append(rag_clean_text(str(t)))

        cfg = resolve_full_config()
        cfg_extra = dict(cfg.get("extra") or {})
        bs = int(batch_size or cfg_extra.get("batch_size") or self._int_setting("RAG_EMBED_BATCH_SIZE", 16))
        if bs <= 0:
            bs = len(cleaned)

        out: List[Optional[np.ndarray]] = []
        provider_name = str(cfg.get("provider_name") or "local").strip().lower()
        can_use_local_service = bool(use_event_bus and provider_name == "local")
        req_delay_sec = float(cfg_extra.get("request_delay_sec") or self._float_setting("RAG_EMBED_REQUEST_DELAY_SEC", 0.0))
        if req_delay_sec < 0.0:
            req_delay_sec = 0.0
        logger.debug(
            f"[RAG][embed_batch] provider={provider_name} | model={cfg.get('db_model_key') or cfg.get('model') or cfg.get('hf_name')} | "
            f"texts={len(cleaned)} | batch_size={bs} | delay={req_delay_sec:.3f}s | local_service={can_use_local_service}"
        )

        if can_use_local_service:
            try:
                embedder = use(EmbeddingService)
                _service_ok = False
                for i in range(0, len(cleaned), bs):
                    chunk = cleaned[i:i + bs]
                    vecs = embedder.embed_many(chunk, prefix=prefix, batch_size=bs, priority=priority)
                    if not isinstance(vecs, list):
                        vecs = []
                    # выравниваем длину под входной chunk
                    if len(vecs) != len(chunk):
                        vecs = (vecs + [None] * len(chunk))[:len(chunk)]
                    # Local-путь иногда возвращает только None/[] (например handler не инициализировался).
                    # В этом случае считаем батч неуспешным и падаем в provider fallback.
                    if not vecs or all(v is None for v in vecs):
                        logger.warning(
                            "[RAG][embed_batch] EmbeddingService returned empty/None-only batch; switching to provider fallback"
                        )
                        out.clear()
                        _service_ok = False
                        break
                    out.extend(vecs)
                    _service_ok = True
                    if req_delay_sec > 0.0 and (i + bs) < len(cleaned):
                        try:
                            _time.sleep(req_delay_sec)
                        except Exception:
                            pass
                if _service_ok:
                    return out
            except Exception as e:
                logger.warning(
                    f"RAGManager: EmbeddingService batch не сработал, fallback на провайдер. Причина: {format_exception(e)}"
                )
                out.clear()

        # Fallback: через провайдер-систему
        try:
            merged: List[Optional[np.ndarray]] = []
            for i in range(0, len(cleaned), bs):
                chunk = cleaned[i:i + bs]
                vecs = self.embed_via_provider(chunk, is_query=False, prefix=prefix)
                if not isinstance(vecs, list):
                    vecs = []
                if len(vecs) != len(chunk):
                    vecs = (vecs + [None] * len(chunk))[:len(chunk)]
                merged.extend(vecs)
                if req_delay_sec > 0.0 and (i + bs) < len(cleaned):
                    try:
                        _time.sleep(req_delay_sec)
                    except Exception:
                        pass
            return merged
        except Exception as e:
            logger.error(f"RAGManager: ошибка fallback batch эмбеддингов: {format_exception(e)}", exc_info=True)
            return [None] * len(cleaned)

    # --- локальные setting-хелперы --------------------------------------- #
    @staticmethod
    def _int_setting(key: str, default: int) -> int:
        try:
            return int(SettingsManager.get(key, default))
        except Exception:
            return int(default)

    @staticmethod
    def _float_setting(key: str, default: float) -> float:
        try:
            return float(SettingsManager.get(key, default))
        except Exception:
            return float(default)
