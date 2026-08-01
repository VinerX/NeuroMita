"""Готовность RAG как единый факт для UI.

Индикатор в шапке и строка «Статус» раньше показывали настройку RAG_ENABLED —
то есть «включён», а не «работает». Модели (эмбеддер и реранкер) поднимаются
позже: эмбеддер прогревается в фоне на старте, реранкер — лениво при первом
реранке, и до этого первый запрос упирается в минутную загрузку весов. Здесь
собирается настоящее состояние, чтобы плашка не обещала готовность заранее.
"""
from __future__ import annotations

from dataclasses import dataclass

from managers.settings_manager import SettingsManager


# Состояния частей: "not_needed" — деталь не нужна при текущих настройках.
NOT_NEEDED = "not_needed"
LOADING = "loading"
READY = "ready"
ERROR = "error"

# Состояния RAG целиком.
OFF = "off"


@dataclass(frozen=True, slots=True)
class RagReadiness:
    state: str = OFF
    embeddings: str = NOT_NEEDED
    reranker: str = NOT_NEEDED


def _b(value, default: bool = False) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(value)
    except Exception:
        return default


def _map_state(state) -> str:
    from services.contracts import ModelState

    if state is ModelState.ERROR:
        return ERROR
    if state is ModelState.READY:
        return READY
    if state is ModelState.DISABLED:
        return NOT_NEEDED
    return LOADING


def _embeddings_state() -> str:
    from core.services import services
    from services.contracts import EmbeddingService

    embedder = services().get_optional(EmbeddingService)
    if embedder is None:
        # Модель нужна, а сервиса нет — эмбеддингов не будет.
        return ERROR

    return _map_state(embedder.readiness().state)


def _reranker_state() -> str:
    from managers.rag.pipeline.config import resolve_ce_model
    from managers.rag.pipeline.cross_encoder import CrossEncoderReranker

    return _map_state(CrossEncoderReranker.readiness(resolve_ce_model()).state)


def rag_readiness() -> RagReadiness:
    if not _b(SettingsManager.get("RAG_ENABLED", False)):
        return RagReadiness()

    # Какие модели вообще нужны текущей конфигурации, решает установщик —
    # чтобы статус, прогрев и докачка не разошлись в трактовке настроек.
    from managers.rag.install_spec import (
        TARGET_EMBEDDINGS,
        TARGET_RERANKER,
        required_model_targets,
    )

    targets = required_model_targets()
    embeddings = _embeddings_state() if TARGET_EMBEDDINGS in targets else NOT_NEEDED
    reranker = _reranker_state() if TARGET_RERANKER in targets else NOT_NEEDED

    if ERROR in (embeddings, reranker):
        state = ERROR
    elif LOADING in (embeddings, reranker):
        state = LOADING
    else:
        state = READY

    return RagReadiness(state=state, embeddings=embeddings, reranker=reranker)
