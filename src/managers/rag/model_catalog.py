"""Каталог конкретных RAG-моделей для AI Hub.

Единый источник правды о том, какие embed/reranker модели показывать в AI Hub
отдельными карточками. Строится из тех же пресетов, что использует выбор модели
в настройках RAG (`EMBED_MODEL_PRESETS`, `CE_PRESETS`), поэтому список карточек и
то, что реально скачивается, не расходятся.

Модуль намеренно лёгкий (только два словаря пресетов, без torch/transformers),
чтобы его можно было импортировать в фазе GUI-оболочки при сборке каталога
устанавливаемых компонентов.
"""
from __future__ import annotations

import re
from typing import Any

from handlers.embedding_presets import EMBED_MODEL_PRESETS
from managers.rag.pipeline.config import CE_PRESETS

KIND_EMBEDDINGS = "embeddings"
KIND_RERANKER = "reranker"


def slugify_model(hf_id: str) -> str:
    """HF id → стабильный slug для id компонента (`rag:embeddings:<slug>`)."""
    return re.sub(r"[^a-z0-9]+", "-", str(hf_id or "").lower()).strip("-")


def component_id_for(kind: str, slug: str) -> str:
    return f"rag:{str(kind).strip().lower()}:{slug}"


def _dedup_specs(kind: str, pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """pairs = [(display, hf_id)] → уникальные по hf_id спеки в порядке пресетов."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for display, hf_id in pairs:
        hf = str(hf_id or "").strip()
        if not hf or hf in seen:
            continue
        seen.add(hf)
        out.append(
            {
                "kind": kind,
                "hf_id": hf,
                "display": str(display or hf).strip(),
                "slug": slugify_model(hf),
                "id": component_id_for(kind, slugify_model(hf)),
            }
        )
    return out


def embedding_model_specs() -> list[dict[str, Any]]:
    return _dedup_specs(
        KIND_EMBEDDINGS,
        [(name, cfg.get("hf_name")) for name, cfg in EMBED_MODEL_PRESETS.items()],
    )


def reranker_model_specs() -> list[dict[str, Any]]:
    # "Custom" в CE_PRESETS указывает на пустой id — его в каталог не выводим.
    return _dedup_specs(
        KIND_RERANKER,
        [(name, hf_id) for name, hf_id in CE_PRESETS.items()],
    )


def all_model_specs() -> list[dict[str, Any]]:
    return embedding_model_specs() + reranker_model_specs()


def _looks_like_hf_id(value: str) -> bool:
    """HF repo id вида `org/name` (а не локальный путь к папке модели).

    Кастомную модель имеет смысл выводить карточкой (скачать с HF) только если
    это repo id. Локальный путь скачивать неоткуда — карточку не создаём.
    """
    import os
    import re

    text = str(value or "").strip()
    if not text or os.path.sep in text.replace("/", os.path.sep) and os.path.exists(text):
        # Существующий локальный путь — не HF id.
        return False
    if "\\" in text or text.startswith(".") or (len(text) > 1 and text[1] == ":"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", text))


def _spec_for(kind: str, hf_id: str) -> dict[str, Any]:
    slug = slugify_model(hf_id)
    return {
        "kind": kind,
        "hf_id": str(hf_id).strip(),
        "display": str(hf_id).strip(),
        "slug": slug,
        "id": component_id_for(kind, slug),
        "custom": True,
    }


def custom_active_model_specs() -> list[dict[str, Any]]:
    """Спеки для АКТИВНЫХ моделей из настроек RAG, которых нет в пресетах.

    Позволяет AI Hub показать карточку и для кастомной локальной модели (HF id),
    выбранной пользователем вручную. Дёшево: resolve_full_config кэшируется.
    """
    out: list[dict[str, Any]] = []

    try:
        from handlers.embedding_presets import resolve_full_config

        cfg = resolve_full_config()
        if str(cfg.get("provider_name") or "local").strip().lower() == "local":
            hf = str(cfg.get("hf_name") or "").strip()
            known = {s["hf_id"] for s in embedding_model_specs()}
            if hf and hf not in known and _looks_like_hf_id(hf):
                out.append(_spec_for(KIND_EMBEDDINGS, hf))
    except Exception:
        pass

    try:
        from managers.rag.pipeline.config import resolve_ce_model

        hf = str(resolve_ce_model() or "").strip()
        known = {s["hf_id"] for s in reranker_model_specs()}
        if hf and hf not in known and _looks_like_hf_id(hf):
            out.append(_spec_for(KIND_RERANKER, hf))
    except Exception:
        pass

    return out


def spec_for_hf(kind: str, hf_id: str) -> dict[str, Any] | None:
    kind = str(kind or "").strip().lower()
    hf_id = str(hf_id or "").strip()
    specs = embedding_model_specs() if kind == KIND_EMBEDDINGS else reranker_model_specs()
    for spec in specs:
        if spec["hf_id"] == hf_id:
            return spec
    return None
