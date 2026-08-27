"""Regression: AI Hub RAG cards list concrete models and install what they show.

Раньше карточка RAG в AI Hub имела замороженный заголовок из статического
манифеста ("Qwen/Qwen3-Embedding-0.6B"), а ставила модель, выбранную в
настройках RAG (напр. e5-small) — «подмена». Теперь каждая модель пресета —
своя карточка, и заголовок карточки совпадает с реально скачиваемой моделью.
"""
from __future__ import annotations

import managers.rag.model_catalog as mc
from installables.catalog_manifest import CATALOG_BY_ID, entries_for_category
from managers.rag.install_spec import (
    RagModelInstallableComponent,
    build_model_install_plan,
    create_rag_installable_components,
)


def test_grid_lists_per_model_cards_and_hides_aggregates():
    grid = entries_for_category("rag")
    grid_ids = {e.id for e in grid}

    # По карточке на каждую embed/reranker модель пресета.
    for spec in mc.all_model_specs():
        assert spec["id"] in grid_ids, spec["id"]

    # Агрегаты доступны для lookup (settings-driven), но НЕ в сетке.
    assert "rag:embeddings" not in grid_ids
    assert "rag:reranker" not in grid_ids
    assert "rag:embeddings" in CATALOG_BY_ID
    assert "rag:reranker" in CATALOG_BY_ID


def test_card_title_matches_installed_model(monkeypatch, tmp_path):
    # Настройки RAG указывают на ОДНУ модель...
    import handlers.embedding_presets as ep

    monkeypatch.setattr(ep, "resolve_full_config", lambda: {"hf_name": "BAAI/bge-m3", "provider_name": "local"})

    # ...а карточка e5-small всё равно относится к e5-small.
    comp = RagModelInstallableComponent("embeddings", "intfloat/multilingual-e5-small")
    assert comp.id == "rag:embeddings:intfloat-multilingual-e5-small"
    assert comp.item_id == "embeddings"  # общий env-слот
    assert comp.metadata().title == "intfloat/multilingual-e5-small"

    # Пустой кэш → план качает ИМЕННО модель карточки, а не модель из настроек.
    monkeypatch.setenv("NEUROMITA_CHECKPOINTS_DIR", str(tmp_path))
    plan = build_model_install_plan("embeddings", "intfloat/multilingual-e5-small", timeout_sec=60)
    downloads = [str(a.description) for a in plan.actions if "Downloading model" in str(a.description)]
    assert downloads == ["Downloading model: intfloat/multilingual-e5-small"]


def test_all_model_cards_share_environment_slot():
    for comp in create_rag_installable_components():
        if isinstance(comp, RagModelInstallableComponent):
            assert comp.item_id in ("embeddings", "reranker")


def test_custom_active_model_gets_live_card(monkeypatch):
    import handlers.embedding_presets as ep

    # Активная кастомная локальная модель (HF id, не из пресетов).
    monkeypatch.setattr(
        ep, "resolve_full_config",
        lambda: {"hf_name": "my-org/custom-embed-v1", "provider_name": "local"},
    )
    specs = mc.custom_active_model_specs()
    ids = {s["id"] for s in specs}
    assert "rag:embeddings:my-org-custom-embed-v1" in ids

    grid_ids = {e.id for e in entries_for_category("rag")}
    assert "rag:embeddings:my-org-custom-embed-v1" in grid_ids


def test_custom_card_skips_local_path_and_api_provider(monkeypatch):
    import handlers.embedding_presets as ep

    # Локальный путь — скачивать неоткуда, карточки нет.
    monkeypatch.setattr(
        ep, "resolve_full_config",
        lambda: {"hf_name": r"C:/models/local_folder", "provider_name": "local"},
    )
    assert all(s["kind"] != mc.KIND_EMBEDDINGS for s in mc.custom_active_model_specs())

    # API-провайдер (не local) — тоже без embed-карточки.
    monkeypatch.setattr(
        ep, "resolve_full_config",
        lambda: {"hf_name": "text-embedding-3-small", "provider_name": "openai_compat"},
    )
    assert all(s["kind"] != mc.KIND_EMBEDDINGS for s in mc.custom_active_model_specs())
