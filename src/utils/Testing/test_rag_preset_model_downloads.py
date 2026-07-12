from unittest.mock import patch


def test_preset_model_check_only_returns_enabled_targets_with_missing_models():
    from ui.settings import rag_memory_settings as rag_settings

    statuses = {
        rag_settings.TARGET_EMBEDDINGS: {"download_models": ["Qwen/Qwen3-Embedding-0.6B"]},
        rag_settings.TARGET_RERANKER: {"download_models": ["Qwen/Qwen3-Reranker-0.6B"]},
    }

    with (
        patch.object(
            rag_settings.SettingsManager,
            "get",
            side_effect=lambda key, default=None: {
                "RAG_VECTOR_SEARCH_ENABLED": True,
                "RAG_CROSS_ENCODER_ENABLED": False,
            }.get(key, default),
        ),
        patch.object(rag_settings, "get_install_status", side_effect=lambda target: statuses[target]) as status,
    ):
        result = rag_settings._missing_preset_model_targets()

    assert result == [(rag_settings.TARGET_EMBEDDINGS, ["Qwen/Qwen3-Embedding-0.6B"])]
    status.assert_called_once_with(rag_settings.TARGET_EMBEDDINGS)


def test_preset_model_check_ignores_missing_python_dependencies():
    from ui.settings import rag_memory_settings as rag_settings

    with (
        patch.object(rag_settings.SettingsManager, "get", return_value=True),
        patch.object(rag_settings, "get_install_status", return_value={"download_models": []}),
    ):
        result = rag_settings._missing_preset_model_targets()

    assert result == []
