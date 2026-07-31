"""Индикатор RAG обязан показывать «работает», а не «включено в настройках».

Готовность считается по тем же целям (``required_model_targets``), по которым
установщик решает, что качать, а контроллеры — что прогревать. Здесь проверяется,
что статус не обещает готовность, пока нужные модели не подняты, и не требует
моделей, которых текущая конфигурация не использует.
"""
from unittest.mock import patch

from services.contracts import EmbeddingReadiness


def _settings(**overrides):
    values = {
        "RAG_ENABLED": True,
        "RAG_VECTOR_SEARCH_ENABLED": True,
        "RAG_CROSS_ENCODER_ENABLED": False,
    }
    values.update(overrides)

    class _SettingsManager:
        @staticmethod
        def get(key, default=None):
            return values.get(key, default)

    return _SettingsManager


class _Embedder:
    def __init__(self, **kwargs):
        self._readiness = EmbeddingReadiness(**kwargs)

    def readiness(self):
        return self._readiness


def _run(settings, embedder, *, ce_loaded=False, ce_failed=False, local_provider=True):
    from managers.rag import install_spec
    from managers.rag import readiness as mod
    from managers.rag.pipeline.cross_encoder import RerankerReadiness

    class _Registry:
        @staticmethod
        def get_optional(_contract):
            return embedder

    with patch.object(mod, "SettingsManager", settings), \
         patch.object(install_spec, "SettingsManager", settings), \
         patch.object(install_spec, "_local_provider_enabled", return_value=local_provider), \
         patch.object(install_spec, "resolve_ce_model", return_value="owner/reranker"), \
         patch("core.services.services", return_value=_Registry()), \
         patch("managers.rag.pipeline.cross_encoder.CrossEncoderReranker.readiness",
               return_value=RerankerReadiness(model_loaded=ce_loaded, failed=ce_failed)), \
         patch("managers.rag.pipeline.config.resolve_ce_model", return_value="owner/reranker"):
        return mod.rag_readiness()


def test_disabled_rag_is_off():
    state = _run(_settings(RAG_ENABLED=False), _Embedder())
    assert state.state == "off"


def test_enabled_but_model_not_loaded_is_loading():
    state = _run(_settings(), _Embedder(model_loaded=False))
    assert state.state == "loading"
    assert state.embeddings == "loading"


def test_loaded_model_without_reranker_is_ready():
    state = _run(_settings(), _Embedder(model_loaded=True))
    assert state.state == "ready"
    assert state.reranker == "not_needed"


def test_reranker_not_warmed_keeps_rag_not_ready():
    state = _run(
        _settings(RAG_CROSS_ENCODER_ENABLED=True),
        _Embedder(model_loaded=True),
        ce_loaded=False,
    )
    assert state.state == "loading"
    assert state.reranker == "loading"

    state = _run(
        _settings(RAG_CROSS_ENCODER_ENABLED=True),
        _Embedder(model_loaded=True),
        ce_loaded=True,
    )
    assert state.state == "ready"


def test_reranker_counts_without_vector_search():
    """Cross-encoder переранжирует и keyword-кандидатов — векторный поиск ему
    не нужен (RAGManager гейтит его только по cross_encoder_enabled)."""
    state = _run(
        _settings(RAG_VECTOR_SEARCH_ENABLED=False, RAG_CROSS_ENCODER_ENABLED=True),
        _Embedder(),
        ce_loaded=False,
    )
    assert state.embeddings == "not_needed"
    assert state.reranker == "loading"
    assert state.state == "loading"


def test_keyword_only_mode_needs_no_models():
    state = _run(
        _settings(RAG_VECTOR_SEARCH_ENABLED=False, RAG_CROSS_ENCODER_ENABLED=False),
        _Embedder(),
    )
    assert state.state == "ready"
    assert state.embeddings == "not_needed"
    assert state.reranker == "not_needed"


def test_remote_embedding_provider_needs_no_local_model():
    state = _run(_settings(), _Embedder(provider="gemini"), local_provider=False)
    assert state.embeddings == "not_needed"
    assert state.state == "ready"


def test_broken_reranker_is_error_not_endless_loading():
    """Упавший реранкер не должен вечно висеть как «загружается»."""
    state = _run(
        _settings(RAG_CROSS_ENCODER_ENABLED=True),
        _Embedder(model_loaded=True),
        ce_failed=True,
    )
    assert state.reranker == "error"
    assert state.state == "error"


def test_failed_warmup_is_error():
    state = _run(_settings(), _Embedder(failed=True))
    assert state.state == "error"
