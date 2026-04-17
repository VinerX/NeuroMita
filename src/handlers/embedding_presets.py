"""Пресеты моделей эмбеддингов для RAG.

Legacy API (resolve_model_settings) remains for backward compatibility.
New API: resolve_full_config() — returns provider_name + all connection fields.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from managers.settings_manager import SettingsManager
from main_logger import logger


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
    Kept for backward compatibility — new code should use resolve_full_config().
    """
    cfg = resolve_full_config()
    return {
        "hf_name": cfg.get("model") or cfg.get("hf_name") or "",
        "query_prefix": cfg.get("query_prefix") or "",
        "dimensions": int(cfg.get("dimensions") or 0),
    }


def resolve_full_config() -> Dict[str, Any]:
    """Return full embedding config including provider routing info.

    Priority:
    1. RAG_EMBED_PRESET_ID set → look up in EmbeddingPresetsController via event bus
    2. Legacy RAG_EMBED_MODEL string (HF preset name or "Custom") → local provider
    """
    # --- New path: RAG_EMBED_PRESET_ID ---
    preset_id = SettingsManager.get("RAG_EMBED_PRESET_ID", None)
    if preset_id is not None:
        # 1) Fast path via controller/event bus
        try:
            from core.events import get_event_bus, Events
            bus = get_event_bus()
            results = bus.emit_and_wait(
                Events.EmbeddingPresets.GET_PRESET_FULL,
                {"id": preset_id},
                timeout=2.0,
            )
            cfg = results[0] if results else None
            if cfg and isinstance(cfg, dict):
                return cfg
        except Exception:
            pass

        # 2) Robust fallback without EventBus (important for worker/startup races)
        try:
            cfg = _resolve_from_preset_storage(preset_id)
            if cfg:
                logger.warning(
                    f"[EmbedPreset] EventBus lookup failed, using storage fallback for preset_id={preset_id} "
                    f"(provider={cfg.get('provider_name')}, model={cfg.get('model')})"
                )
                return cfg
        except Exception:
            pass

    # --- Legacy path: RAG_EMBED_MODEL string ---
    chosen = str(SettingsManager.get("RAG_EMBED_MODEL", "GTE multilingual base (620M, 2024)") or "").strip()
    logger.warning(
        f"[EmbedPreset] Falling back to legacy embedding model settings (RAG_EMBED_MODEL='{chosen}')"
    )
    preset = get_preset(chosen)
    if preset:
        hf = preset["hf_name"]
        return {
            "provider_name": "local",
            "model": hf,
            "hf_name": hf,
            "api_url": hf,
            "api_key": None,
            "reserve_keys": [],
            "headers": {},
            "query_prefix": preset.get("query_prefix", ""),
            "dimensions": int(preset.get("dimensions") or 0),
            "extra": {},
            "db_model_key": hf,  # used for tagging vectors in DB
        }

    # Custom legacy model
    hf_name = str(SettingsManager.get("RAG_EMBED_MODEL_CUSTOM", "") or "").strip()
    if not hf_name:
        default = EMBED_MODEL_PRESETS["GTE multilingual base (620M, 2024)"]
        hf = default["hf_name"]
        return {
            "provider_name": "local",
            "model": hf,
            "hf_name": hf,
            "api_url": hf,
            "api_key": None,
            "reserve_keys": [],
            "headers": {},
            "query_prefix": default.get("query_prefix", ""),
            "dimensions": int(default.get("dimensions") or 0),
            "extra": {},
            "db_model_key": hf,
        }

    return {
        "provider_name": "local",
        "model": hf_name,
        "hf_name": hf_name,
        "api_url": hf_name,
        "api_key": None,
        "reserve_keys": [],
        "headers": {},
        "query_prefix": str(SettingsManager.get("RAG_EMBED_QUERY_PREFIX", "") or ""),
        "dimensions": 0,
        "extra": {},
        "db_model_key": hf_name,
    }


def _resolve_from_preset_storage(preset_id: Any) -> Optional[Dict[str, Any]]:
    from presets.embedding_provider_presets import get_builtin_preset

    data: Dict[str, Any] = {}
    path = Path("Settings/embedding_presets.json")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    builtin_overrides = data.get("builtin_overrides") or {}
    custom_map = data.get("presets") or {}

    # Builtin preset id (string)
    bp = get_builtin_preset(str(preset_id))
    if bp:
        ov = builtin_overrides.get(str(preset_id)) or {}
        provider = str(bp.get("provider") or "local")
        model = str(ov.get("model") or bp.get("default_model") or "")
        url = str(ov.get("url") or bp.get("default_url") or "")
        query_prefix = str(ov.get("query_prefix") or "")
        headers = dict(bp.get("default_headers") or {})
        if isinstance(ov.get("headers"), dict):
            headers.update(dict(ov.get("headers") or {}))
        extra = dict(bp.get("default_extra") or {})
        if isinstance(ov.get("extra"), dict):
            extra.update(dict(ov.get("extra") or {}))
        return {
            "id": bp.get("id"),
            "name": bp.get("name"),
            "provider_name": provider,
            "model": model,
            "hf_name": model if provider == "local" else "",
            "api_url": url if provider != "local" else model,
            "api_key": ov.get("key") or None,
            "reserve_keys": list(ov.get("reserve_keys") or []),
            "headers": headers,
            "query_prefix": query_prefix,
            "dimensions": int(ov.get("dimensions") or bp.get("default_dimensions") or 0),
            "extra": extra,
            "db_model_key": f"{provider}:{model}" if provider != "local" else model,
        }

    # Custom preset id (numeric)
    try:
        pid = int(preset_id)
    except Exception:
        return None
    raw = custom_map.get(str(pid)) or {}
    if not isinstance(raw, dict):
        return None

    base_id = raw.get("base")
    base = get_builtin_preset(str(base_id)) if base_id else None
    provider = str(raw.get("provider_name") or (base.get("provider") if base else "local"))
    model = str(raw.get("model") or (base.get("default_model") if base else "") or "")
    url = str(raw.get("url") or (base.get("default_url") if base else "") or "")
    headers = dict(base.get("default_headers") or {}) if base else {}
    if isinstance(raw.get("headers"), dict):
        headers.update(dict(raw.get("headers") or {}))
    extra = dict(base.get("default_extra") or {}) if base else {}
    if isinstance(raw.get("extra"), dict):
        extra.update(dict(raw.get("extra") or {}))
    return {
        "id": pid,
        "name": str(raw.get("name") or f"Preset {pid}"),
        "provider_name": provider,
        "model": model,
        "hf_name": model if provider == "local" else "",
        "api_url": url if provider != "local" else model,
        "api_key": raw.get("key") or None,
        "reserve_keys": list(raw.get("reserve_keys") or []),
        "headers": headers,
        "query_prefix": str(raw.get("query_prefix") or ""),
        "dimensions": int(raw.get("dimensions") or (base.get("default_dimensions") if base else 0) or 0),
        "extra": extra,
        "db_model_key": f"{provider}:{model}" if provider != "local" else model,
    }
