from __future__ import annotations

import time
from threading import Lock, Thread
from typing import List, Optional

import numpy as np

from core.events import Event, Events, get_event_bus
from handlers.ai_engine.rag_client import (
    get_embeddings as rag_get_embeddings,
    warmup_embeddings as rag_warmup_embeddings,
)
from handlers.embedding_presets import (
    invalidate_embedding_config_cache,
    resolve_full_config,
    resolve_model_settings,
)
from main_logger import logger
from managers.settings_manager import SettingsManager
from services.contracts import EmbeddingService


EMBED_EVENT_NAME = Events.RAG.GET_EMBEDDING
EMBEDS_EVENT_NAME = Events.RAG.GET_EMBEDDINGS


class EmbeddingController(EmbeddingService):
    """
    EventBus bridge for RAG embeddings.

    The public contract stays the same (`rag_get_embedding(s)`), but the local
    backend now lives inside `ai_engine` service='rag' instead of the main
    process.
    """

    # Раньше стояло 3600с: «вечное» ожидание маскировало зависший worker.
    # Эмбеддинг запроса пользователя не имеет смысла ждать дольше самой генерации.
    _HOT_TIMEOUT_SEC = 60.0

    _EMBED_SETTING_KEYS = frozenset({
        "RAG_EMBED_MODEL",
        "RAG_EMBED_MODEL_CUSTOM",
        "RAG_EMBED_QUERY_PREFIX",
        "HF_TOKEN",
        "RAG_VECTOR_SEARCH_ENABLED",
        "RAG_EMBED_PRESET_ID",
    })

    def __init__(self) -> None:
        self.event_bus = get_event_bus()
        self.handler: object | None = None
        self._handler_failed: bool = False
        self._init_lock = Lock()

        self._subscribe_to_events()

        if not SettingsManager.get("RAG_ENABLED", False):
            logger.info("RAG is disabled in settings. Embedding backend warmup skipped.")
            return

        self._maybe_start_warmup(reason="startup")

    def _should_warmup(self) -> bool:
        """Модель эмбеддингов нужна, когда включён векторный поиск (либо явный
        preload). Тогда её стоит грузить в фоне заранее — иначе первый RAG-запрос
        упирается в таймаут на «холодной» загрузке/скачивании весов с HuggingFace."""
        if not SettingsManager.get("RAG_ENABLED", False):
            return False
        if self._provider_name() != "local":
            return False
        preload = bool(SettingsManager.get("RAG_PRELOAD_EMBEDDINGS_MODEL", False))
        vector = bool(SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", False))
        return preload or vector

    def _maybe_start_warmup(self, *, reason: str) -> None:
        if not self._should_warmup():
            return
        if self.handler is not None or self._handler_failed:
            return
        Thread(
            target=self._warmup_local_backend,
            name=f"embed-warmup-{reason}",
            daemon=True,
        ).start()

    def _provider_name(self) -> str:
        try:
            cfg = resolve_full_config()
            return str(cfg.get("provider_name") or "local").strip().lower()
        except Exception:
            return "local"

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(EMBED_EVENT_NAME, self._on_get_embedding, weak=False)
        self.event_bus.subscribe(EMBEDS_EVENT_NAME, self._on_get_embeddings, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self.event_bus.subscribe(Events.RAG.MODEL_CHANGED, self._on_model_changed, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_finished, weak=False)
        # Содержимое пресета могло измениться при том же id — сигнатура настроек
        # этого не поймает, поэтому сбрасываем кэш конфига явно.
        self.event_bus.subscribe(Events.EmbeddingPresets.PRESET_SAVED, self._on_preset_mutated, weak=False)
        self.event_bus.subscribe(Events.EmbeddingPresets.PRESET_DELETED, self._on_preset_mutated, weak=False)
        logger.notify(
            f"EmbeddingController подписался на события: {EMBED_EVENT_NAME}, {EMBEDS_EVENT_NAME}"
        )

    def _warmup_local_backend(self) -> None:
        # AI engine может подняться позже контроллера, а первый запуск модели —
        # тянуть веса с HF (~минуты). Поэтому ретраим до готовности движка, чтобы
        # прогрев состоялся в фоне, а не сорвался из-за стартовой гонки.
        for _ in range(150):  # ~5 минут ожидания движка (загрузка идёт уже в нём)
            if self.handler is not None or self._handler_failed:
                return
            if not self._should_warmup():
                return
            try:
                if self._ensure_local_backend():
                    return
            except Exception:
                pass
            time.sleep(2.0)

    def _ensure_local_backend(self) -> bool:
        if self._handler_failed:
            return False
        if not SettingsManager.get("RAG_ENABLED", False):
            return False
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", False):
            return False
        if self._provider_name() != "local":
            with self._init_lock:
                self.handler = None
            logger.debug("EmbeddingController: non-local provider, AI engine warmup skipped")
            return False
        if self.handler is not None:
            return True

        with self._init_lock:
            if self.handler is None and not self._handler_failed:
                try:
                    ms = resolve_model_settings()
                    rag_warmup_embeddings(
                        model_name=ms["hf_name"],
                        query_prefix=ms["query_prefix"],
                    )
                    self.handler = object()
                except Exception as e:
                    if "AI engine not available" in str(e):
                        # Движок ещё не поднялся — не окончательный провал, фоновый
                        # прогрев повторит попытку позже.
                        logger.debug(
                            "EmbeddingController: AI engine ещё не готов для прогрева эмбеддингов, повторю позже"
                        )
                        return False
                    logger.error(
                        f"EmbeddingController: не удалось прогреть local embedding backend: {e}",
                        exc_info=True,
                    )
                    self._handler_failed = True
                    return False
        return True

    def _on_preset_mutated(self, _event: Event) -> None:
        invalidate_embedding_config_cache()

    def _on_model_changed(self, event: Event) -> None:
        data = event.data or {}
        invalidate_embedding_config_cache()
        logger.info(f"EmbeddingController: MODEL_CHANGED event received: {data}")

    def _on_setting_changed(self, event: Event) -> None:
        data = event.data or {}
        key = data.get("key", "")
        if key not in self._EMBED_SETTING_KEYS:
            return

        logger.info(f"EmbeddingController: настройка '{key}' изменилась, сбрасываю local backend cache")
        invalidate_embedding_config_cache()
        with self._init_lock:
            self.handler = None
            self._handler_failed = False

        if key in ("RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM"):
            self.event_bus.emit(Events.RAG.MODEL_CHANGED, {
                "key": key,
                "value": data.get("value"),
            })

        # Включили векторный поиск / сменили модель — прогреваем в фоне сразу,
        # чтобы первый запрос не ждал холодную загрузку.
        self._maybe_start_warmup(reason=f"setting:{key}")

    def _on_install_task_finished(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        task_id = str(data.get("task_id") or "")
        if meta.get("kind") != "rag" and not task_id.startswith("rag:"):
            return

        invalidate_embedding_config_cache()
        with self._init_lock:
            self.handler = None
            self._handler_failed = False

        # Модель эмбеддингов только что доустановлена — прогреем в фоне.
        self._maybe_start_warmup(reason="install_finished")

    def _on_get_embedding(self, event: Event) -> Optional[np.ndarray]:
        data = event.data or {}
        future = data.get("future")
        vec = self.embed_one(text=data.get("text") or "", prefix=data.get("prefix") or "")
        if future is not None:
            try:
                future.set_result(vec)
            except Exception:
                pass
        return vec

    def _on_get_embeddings(self, event: Event) -> List[Optional[np.ndarray]]:
        data = event.data or {}
        future = data.get("future")
        results = self.embed_many(
            texts=data.get("texts") or [],
            prefix=data.get("prefix") or "",
            batch_size=data.get("batch_size"),
            priority=str(data.get("priority") or "hot"),
        )
        if future is not None:
            try:
                future.set_result(results)
            except Exception:
                pass
        return results

    def embed_one(self, text: str, prefix: str = "") -> Optional[np.ndarray]:
        if not text or self._provider_name() != "local":
            return None
        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            # Никакого _infer_lock: конкуренцию за устройство разруливает
            # приоритетный планировщик внутри AI-worker'а. Локальный лок здесь
            # просто заставлял эмбеддинг запроса ждать фоновую индексацию.
            results = rag_get_embeddings(
                [str(text)],
                model_name=ms["hf_name"],
                query_prefix=ms["query_prefix"],
                prefix=str(prefix or ""),
                batch_size=1,
                timeout_sec=self._HOT_TIMEOUT_SEC,
                priority="hot",
            )
            return results[0] if results else None
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка embed_one via AI engine: {e}", exc_info=True)
            return None

    def embed_many(
        self,
        texts: List[str],
        prefix: str = "",
        batch_size: Optional[int] = None,
        priority: str = "hot",
    ) -> List[Optional[np.ndarray]]:
        if not texts or self._provider_name() != "local":
            return []
        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            bs = int(batch_size) if batch_size is not None else 32
            if bs <= 0:
                bs = 32

            return rag_get_embeddings(
                list(texts),
                model_name=ms["hf_name"],
                query_prefix=ms["query_prefix"],
                prefix=str(prefix or ""),
                batch_size=bs,
                timeout_sec=(None if priority == "bulk" else self._HOT_TIMEOUT_SEC),
                priority=priority,
            )
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка embed_many via AI engine: {e}", exc_info=True)
            return []
