from unittest.mock import patch


def test_required_model_targets_respects_global_rag_switch():
    from managers.rag import install_spec

    class _Settings:
        def __init__(self, enabled):
            self.enabled = enabled

        def get(self, key, default=None):
            return {
                "RAG_ENABLED": self.enabled,
                "RAG_VECTOR_SEARCH_ENABLED": True,
                "RAG_CROSS_ENCODER_ENABLED": True,
            }.get(key, default)

    with patch.object(install_spec, "_local_provider_enabled", return_value=True), \
         patch.object(install_spec, "resolve_ce_model", return_value="owner/reranker"):
        assert install_spec.required_model_targets(_Settings(False)) == []
        assert install_spec.required_model_targets(_Settings(True)) == [
            install_spec.TARGET_EMBEDDINGS,
            install_spec.TARGET_RERANKER,
        ]


def test_preset_model_check_only_returns_enabled_targets_with_missing_models():
    from controllers.gui import rag_memory_controller as rag_settings

    statuses = {
        rag_settings.TARGET_EMBEDDINGS: {"download_models": ["Qwen/Qwen3-Embedding-0.6B"]},
        rag_settings.TARGET_RERANKER: {"download_models": ["Qwen/Qwen3-Reranker-0.6B"]},
    }

    class _Settings:
        def get(self, key, default=None):
            return {
                "RAG_ENABLED": True,
                "RAG_VECTOR_SEARCH_ENABLED": True,
                "RAG_CROSS_ENCODER_ENABLED": False,
            }.get(key, default)

    with (
        patch.object(rag_settings, "use", return_value=_Settings()),
        patch.object(
            rag_settings,
            "required_model_targets",
            return_value=[rag_settings.TARGET_EMBEDDINGS],
        ) as targets,
        patch.object(rag_settings, "get_install_status", side_effect=lambda target: statuses[target]) as status,
    ):
        result = rag_settings._missing_preset_model_targets()

    assert result == [(rag_settings.TARGET_EMBEDDINGS, ["Qwen/Qwen3-Embedding-0.6B"])]
    targets.assert_called_once()
    status.assert_called_once_with(rag_settings.TARGET_EMBEDDINGS)


def test_preset_model_check_ignores_missing_python_dependencies():
    from controllers.gui import rag_memory_controller as rag_settings

    class _Settings:
        def get(self, _key, default=None):
            return default

    with (
        patch.object(rag_settings, "use", return_value=_Settings()),
        patch.object(rag_settings, "required_model_targets", return_value=[]),
        patch.object(rag_settings, "get_install_status", return_value={"download_models": []}),
    ):
        result = rag_settings._missing_preset_model_targets()

    assert result == []
