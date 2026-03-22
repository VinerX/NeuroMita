"""Пресеты моделей эмбеддингов для RAG."""
from __future__ import annotations

from typing import Dict, List, Optional

from managers.settings_manager import SettingsManager


EMBED_MODEL_PRESETS: Dict[str, dict] = {
    "Snowflake Arctic M v2.0": {
        "hf_name": "Snowflake/snowflake-arctic-embed-m-v2.0",
        "query_prefix": "query: ",
        "dimensions": 768,
    },
    "BAAI/bge-m3": {
        "hf_name": "BAAI/bge-m3",
        "query_prefix": "",
        "dimensions": 1024,
    },
    "multilingual-e5-large-instruct": {
        "hf_name": "intfloat/multilingual-e5-large-instruct",
        "query_prefix": "query: ",
        "dimensions": 1024,
    },
    "deepvk/USER-bge-m3": {
        "hf_name": "deepvk/USER-bge-m3",
        "query_prefix": "",
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
    chosen = str(SettingsManager.get("RAG_EMBED_MODEL", "Snowflake Arctic M v2.0") or "").strip()
    preset = get_preset(chosen)
    if preset:
        return dict(preset)

    # Custom model
    hf_name = str(SettingsManager.get("RAG_EMBED_MODEL_CUSTOM", "") or "").strip()
    if not hf_name:
        # fallback to default
        return dict(EMBED_MODEL_PRESETS["Snowflake Arctic M v2.0"])

    return {
        "hf_name": hf_name,
        "query_prefix": str(SettingsManager.get("RAG_EMBED_QUERY_PREFIX", "") or ""),
        "dimensions": 0,  # unknown until loaded
    }
