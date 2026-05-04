from __future__ import annotations

from threading import Lock, Thread
from typing import List, Optional

import numpy as np

from core.events import Event, Events, get_event_bus
from handlers.ai_engine.rag_client import (
    get_embeddings as rag_get_embeddings,
    warmup_embeddings as rag_warmup_embeddings,
)
from handlers.embedding_presets import resolve_full_config, resolve_model_settings
from main_logger import logger
from managers.settings_manager import SettingsManager


EMBED_EVENT_NAME = Events.RAG.GET_EMBEDDING
EMBEDS_EVENT_NAME = Events.RAG.GET_EMBEDDINGS


class EmbeddingController:
    """
    EventBus bridge for RAG embeddings.

    The public contract stays the same (`rag_get_embedding(s)`), but the local
    backend now lives inside `ai_engine` service='rag' instead of the main
    process.
    """

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
        self._infer_lock = Lock()

        self._subscribe_to_events()

        if not SettingsManager.get("RAG_ENABLED", False):
            logger.info("RAG is disabled in settings. Embedding backend warmup skipped.")
            return

        preload = SettingsManager.get("RAG_PRELOAD_EMBEDDINGS_MODEL", False)
        provider_name = self._provider_name()
        if bool(preload) and provider_name == "local":
            Thread(target=self._warmup_local_backend, daemon=True).start()
        else:
            logger.debug(
                f"EmbeddingController: preload skipped (preload={bool(preload)}, provider='{provider_name}')"
            )

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
        logger.notify(
            f"EmbeddingController подписался на события: {EMBED_EVENT_NAME}, {EMBEDS_EVENT_NAME}"
        )

    def _warmup_local_backend(self) -> None:
        try:
            self._ensure_local_backend()
        except Exception:
            pass

    def _ensure_local_backend(self) -> bool:
        if self._handler_failed:
            return False
        if not SettingsManager.get("RAG_ENABLED", False):
            return False
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", True):
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
                    logger.error(
                        f"EmbeddingController: не удалось прогреть local embedding backend: {e}",
                        exc_info=True,
                    )
                    self._handler_failed = True
                    return False
        return True

    def _on_model_changed(self, event: Event) -> None:
        data = event.data or {}
        logger.info(f"EmbeddingController: MODEL_CHANGED event received: {data}")

    def _on_setting_changed(self, event: Event) -> None:
        data = event.data or {}
        key = data.get("key", "")
        if key not in self._EMBED_SETTING_KEYS:
            return

        logger.info(f"EmbeddingController: настройка '{key}' изменилась, сбрасываю local backend cache")
        with self._init_lock:
            self.handler = None
            self._handler_failed = False

        if key in ("RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM"):
            self.event_bus.emit(Events.RAG.MODEL_CHANGED, {
                "key": key,
                "value": data.get("value"),
            })

    def _on_install_task_finished(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        task_id = str(data.get("task_id") or "")
        if meta.get("kind") != "rag" and not task_id.startswith("rag:"):
            return

        with self._init_lock:
            self.handler = None
            self._handler_failed = False

    def _on_get_embedding(self, event: Event) -> Optional[np.ndarray]:
        data = event.data or {}
        text = data.get("text") or ""
        prefix = data.get("prefix") or ""
        future = data.get("future")

        if not text or self._provider_name() != "local":
            if future is not None:
                try:
                    future.set_result(None)
                except Exception:
                    pass
            return None

        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            with self._infer_lock:
                results = rag_get_embeddings(
                    [str(text)],
                    model_name=ms["hf_name"],
                    query_prefix=ms["query_prefix"],
                    prefix=str(prefix or ""),
                    batch_size=1,
                    timeout_sec=3600.0,
                )
            vec = results[0] if results else None

            if future is not None:
                try:
                    future.set_result(vec)
                except Exception:
                    pass

            return vec
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка get_embedding via AI engine: {e}", exc_info=True)
            if future is not None:
                try:
                    future.set_result(None)
                except Exception:
                    pass
            return None

    def _on_get_embeddings(self, event: Event) -> List[Optional[np.ndarray]]:
        data = event.data or {}
        texts = data.get("texts") or []
        prefix = data.get("prefix") or ""
        batch_size = data.get("batch_size")
        future = data.get("future")

        if not texts or self._provider_name() != "local":
            if future is not None:
                try:
                    future.set_result([])
                except Exception:
                    pass
            return []

        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            bs = int(batch_size) if batch_size is not None else 32
            if bs <= 0:
                bs = 32

            with self._infer_lock:
                results = rag_get_embeddings(
                    list(texts),
                    model_name=ms["hf_name"],
                    query_prefix=ms["query_prefix"],
                    prefix=str(prefix or ""),
                    batch_size=bs,
                    timeout_sec=3600.0,
                )

            if future is not None:
                try:
                    future.set_result(results)
                except Exception:
                    pass

            return results
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка get_embeddings via AI engine: {e}", exc_info=True)
            if future is not None:
                try:
                    future.set_result([])
                except Exception:
                    pass
            return []
