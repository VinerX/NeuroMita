"""Пресеты моделей эмбеддингов для RAG."""
from __future__ import annotations

from typing import Dict, List, Optional

from managers.settings_manager import SettingsManager


EMBED_MODEL_PRESETS: Dict[str, dict] = {
    # ── Light (~100-300MB, CPU-friendly) ─────────────────────────────────
    "multilingual-e5-small (118M, fast)": {
        "hf_name": "intfloat/multilingual-e5-small",
        "query_prefix": "query: ",
        "dimensions": 384,
    },
    "multilingual-e5-base (278M)": {
        "hf_name": "intfloat/multilingual-e5-base",
        "query_prefix": "query: ",
        "dimensions": 768,
    },
    "paraphrase-multilingual-MiniLM-L12 (118M)": {
        "hf_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "query_prefix": "",
        "dimensions": 384,
    },
    # ── Medium (~300-700MB, recommended) ─────────────────────────────────
    "GTE multilingual base (620M, 2024)": {
        "hf_name": "Alibaba-NLP/gte-multilingual-base",
        "query_prefix": "",
        "dimensions": 768,
    },
    "BAAI/bge-m3 (570M, 2024)": {
        "hf_name": "BAAI/bge-m3",
        "query_prefix": "",
        "dimensions": 1024,
    },
    "deepvk/USER-bge-m3 (570M, RU-tuned)": {
        "hf_name": "deepvk/USER-bge-m3",
        "query_prefix": "",
        "dimensions": 1024,
    },
    "Snowflake Arctic M v2.0 (300M, EN)": {
        "hf_name": "Snowflake/snowflake-arctic-embed-m-v2.0",
        "query_prefix": "query: ",
        "dimensions": 768,
    },
    "Qwen3-Embedding-0.6B (600M, 2025)": {
        "hf_name": "Qwen/Qwen3-Embedding-0.6B",
        "query_prefix": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        "dimensions": 1024,
    },
    # ── Large (1GB+, better quality) ─────────────────────────────────────
    "multilingual-e5-large-instruct (1.3G)": {
        "hf_name": "intfloat/multilingual-e5-large-instruct",
        "query_prefix": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        "dimensions": 1024,
    },
    "GTE Qwen2 1.5B instruct (3.3G)": {
        "hf_name": "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "query_prefix": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        "dimensions": 1536,
    },
    # ── Backwards-compat aliases ──────────────────────────────────────────
    "BAAI/bge-m3": {
        "hf_name": "BAAI/bge-m3",
        "query_prefix": "",
        "dimensions": 1024,
    },
    "Snowflake Arctic M v2.0": {
        "hf_name": "Snowflake/snowflake-arctic-embed-m-v2.0",
        "query_prefix": "query: ",
        "dimensions": 768,
    },
    "multilingual-e5-large-instruct": {
        "hf_name": "intfloat/multilingual-e5-large-instruct",
        "query_prefix": "query: ",
        "dimensions": 1024,
    },
    "nomic-embed-text-v1.5": {
        "hf_name": "nomic-ai/nomic-embed-text-v1.5",
        "query_prefix": "search_query: ",
        "dimensions": 768,
    },
}

_CUSTOM = "Custom"


def get_preset(name: str) -> Optional[dict]:
    return EMBED_MODEL_PRESETS.get(name)


def list_preset_names() -> List[str]:
    return list(EMBED_MODEL_PRESETS.keys()) + [_CUSTOM]


def resolve_model_settings() -> dict:
    """Resolve current embedding model settings from SettingsManager.

    Returns dict with keys: hf_name, query_prefix, dimensions.
    """
    chosen = str(SettingsManager.get("RAG_EMBED_MODEL", "GTE multilingual base (620M, 2024)") or "").strip()
    preset = get_preset(chosen)
    if preset:
        return dict(preset)

    # Custom model
    hf_name = str(SettingsManager.get("RAG_EMBED_MODEL_CUSTOM", "") or "").strip()
    if not hf_name:
        # fallback to default
        return dict(EMBED_MODEL_PRESETS["GTE multilingual base (620M, 2024)"])

    return {
        "hf_name": hf_name,
        "query_prefix": str(SettingsManager.get("RAG_EMBED_QUERY_PREFIX", "") or ""),
        "dimensions": 0,  # unknown until loaded
    }
