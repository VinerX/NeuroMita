"""Пресеты моделей эмбеддингов для RAG.

Legacy API (resolve_model_settings) remains for backward compatibility.
New API: resolve_full_config() — returns provider_name + all connection fields.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.app_paths import settings_path
from threading import Lock
from typing import Any, Dict, List, Optional

try:
    from managers.settings_manager import SettingsManager
except Exception:
    class SettingsManager:
        instance = None

        @staticmethod
        def get(_key, default=None):
            return default

        @staticmethod
        def set(_key, _value):
            return None
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
_DEFAULT_LEGACY_MODEL = "Qwen3-Embedding-0.6B (600M, 2025)"
_LEGACY_WARNING_SHOWN: set[str] = set()


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
        "hf_name": cfg.get("hf_name") or cfg.get("model") or "",
        "query_prefix": cfg.get("query_prefix") or "",
        "dimensions": int(cfg.get("dimensions") or 0),
    }


_CONFIG_CACHE_KEYS = (
    "RAG_EMBED_PRESET_ID",
    "RAG_EMBED_MODEL",
    "RAG_EMBED_MODEL_CUSTOM",
    "RAG_EMBED_QUERY_PREFIX",
)

_config_lock = Lock()
_config_cache: Optional[tuple] = None  # (signature, cfg)


def _config_signature() -> tuple:
    return tuple(SettingsManager.get(key, None) for key in _CONFIG_CACHE_KEYS)


def invalidate_embedding_config_cache() -> None:
    """Сбросить кэш: содержимое пресета могло измениться при том же id."""
    global _config_cache
    with _config_lock:
        _config_cache = None


def resolve_full_config() -> Dict[str, Any]:
    """Кэширующая обёртка. Один RAG-поиск дёргал это 7 раз, а каждый вызов уходил
    в EventBus (sync EventBus RPC, timeout=2s) — то есть 7 потоков на запрос.

    Кэш самоинвалидируется по сигнатуре настроек; при правке содержимого пресета
    владельцы зовут invalidate_embedding_config_cache().
    """
    global _config_cache
    signature = _config_signature()

    with _config_lock:
        cached = _config_cache
    if cached is not None and cached[0] == signature:
        return dict(cached[1])

    cfg = _resolve_full_config_uncached()

    # Сигнатуру берём ПОСЛЕ резолва: он сам может мигрировать легаси-настройки
    # (проставить RAG_EMBED_PRESET_ID), и кэш под «старой» сигнатурой промахнулся бы.
    with _config_lock:
        _config_cache = (_config_signature(), cfg)
    return dict(cfg)


def _resolve_full_config_uncached() -> Dict[str, Any]:
    """Return full embedding config including provider routing info.

    Priority:
    1. RAG_EMBED_PRESET_ID set → look up in EmbeddingPresetsController via event bus
    2. Legacy RAG_EMBED_MODEL string (HF preset name or "Custom") → local provider
    """
    # --- New path: RAG_EMBED_PRESET_ID ---
    preset_id = SettingsManager.get("RAG_EMBED_PRESET_ID", None)
    if preset_id is not None:
        # 1) Fast path via типизированный сервис (без шины — hot-path).
        try:
            from core.services import use
            from services.contracts import EmbeddingPresetService
            cfg = use(EmbeddingPresetService).get_full(preset_id)
            if cfg and isinstance(cfg, dict):
                return cfg
        except Exception:
            pass

        # 2) Robust fallback без сервиса (важно для субпроцесса воркера / раннего старта)
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

    migrated_id = sync_legacy_settings_to_preset(log_migration=False)
    if migrated_id is not None:
        try:
            cfg = _resolve_from_preset_storage(migrated_id)
            if cfg:
                return cfg
        except Exception:
            pass

    # --- Legacy path: RAG_EMBED_MODEL string ---
    chosen = _legacy_model_name()
    _warn_legacy_fallback_once(chosen)
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
        default = EMBED_MODEL_PRESETS[_DEFAULT_LEGACY_MODEL]
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


def _legacy_model_name() -> str:
    chosen = str(SettingsManager.get("RAG_EMBED_MODEL", _DEFAULT_LEGACY_MODEL) or "").strip()
    return chosen or _DEFAULT_LEGACY_MODEL


def _warn_legacy_fallback_once(chosen: str) -> None:
    if chosen in _LEGACY_WARNING_SHOWN:
        return
    _LEGACY_WARNING_SHOWN.add(chosen)
    logger.warning(
        f"[EmbedPreset] Falling back to legacy embedding model settings (RAG_EMBED_MODEL='{chosen}')"
    )


def _load_preset_storage() -> Dict[str, Any]:
    path = settings_path("embedding_presets.json", create_parent=True)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_preset_storage(data: Dict[str, Any]) -> bool:
    path = settings_path("embedding_presets.json", create_parent=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def _build_legacy_override() -> tuple[str, Dict[str, Any]] | None:
    chosen = _legacy_model_name()
    custom_model = str(SettingsManager.get("RAG_EMBED_MODEL_CUSTOM", "") or "").strip()
    custom_prefix = str(SettingsManager.get("RAG_EMBED_QUERY_PREFIX", "") or "")

    if chosen == _CUSTOM:
        if custom_model:
            return "custom_local", {
                "model": custom_model,
                "query_prefix": custom_prefix,
                "dimensions": 0,
                "extra": {"manual_path": True},
            }
        chosen = _DEFAULT_LEGACY_MODEL

    preset = get_preset(chosen)
    if preset:
        return "local_hf", {
            "model": chosen,
            "query_prefix": str(preset.get("query_prefix") or ""),
            "dimensions": int(preset.get("dimensions") or 0),
            "extra": {"manual_path": False},
        }

    raw_model = custom_model or chosen
    if not raw_model:
        return None
    return "custom_local", {
        "model": raw_model,
        "query_prefix": custom_prefix,
        "dimensions": 0,
        "extra": {"manual_path": True},
    }


def sync_legacy_settings_to_preset(*, log_migration: bool = True, force: bool = False) -> Optional[str]:
    """Persist legacy local embedding settings into the new preset storage.

    Returns the resolved preset id when migration succeeded or already exists.
    """
    if SettingsManager.instance is None:
        return None

    preset_id = SettingsManager.get("RAG_EMBED_PRESET_ID", None)
    if preset_id is not None and not force:
        return str(preset_id)

    migration = _build_legacy_override()
    if migration is None:
        return None

    migrated_id, override = migration
    storage = _load_preset_storage()
    builtin_overrides = storage.get("builtin_overrides")
    if not isinstance(builtin_overrides, dict):
        builtin_overrides = {}
        storage["builtin_overrides"] = builtin_overrides
    if not isinstance(storage.get("presets"), dict):
        storage["presets"] = {}
    if not isinstance(storage.get("order"), list):
        storage["order"] = []

    current_override = builtin_overrides.get(migrated_id)
    if current_override != override:
        builtin_overrides[migrated_id] = override
        if not _save_preset_storage(storage):
            return None

    SettingsManager.set("RAG_EMBED_PRESET_ID", migrated_id)
    if log_migration:
        chosen = _legacy_model_name()
        logger.info(
            f"[EmbedPreset] Migrated legacy embedding settings to preset_id={migrated_id} "
            f"(RAG_EMBED_MODEL='{chosen}')"
        )
    return migrated_id


def _resolve_local_model_name(model: str) -> str:
    preset = get_preset(str(model or ""))
    if preset:
        return str(preset.get("hf_name") or model)
    return str(model or "")


def _resolve_from_preset_storage(preset_id: Any) -> Optional[Dict[str, Any]]:
    from presets.embedding_provider_presets import get_builtin_preset

    data: Dict[str, Any] = {}
    path = settings_path("embedding_presets.json", create_parent=True)
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
        resolved_model = _resolve_local_model_name(model) if provider == "local" else model
        return {
            "id": bp.get("id"),
            "name": bp.get("name"),
            "provider_name": provider,
            "model": model,
            "hf_name": resolved_model if provider == "local" else "",
            "api_url": url if provider != "local" else resolved_model,
            "api_key": ov.get("key") or None,
            "reserve_keys": list(ov.get("reserve_keys") or []),
            "headers": headers,
            "query_prefix": query_prefix,
            "dimensions": int(ov.get("dimensions") or bp.get("default_dimensions") or 0),
            "extra": extra,
            "db_model_key": f"{provider}:{model}" if provider != "local" else resolved_model,
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
    resolved_model = _resolve_local_model_name(model) if provider == "local" else model
    return {
        "id": pid,
        "name": str(raw.get("name") or f"Preset {pid}"),
        "provider_name": provider,
        "model": model,
        "hf_name": resolved_model if provider == "local" else "",
        "api_url": url if provider != "local" else resolved_model,
        "api_key": raw.get("key") or None,
        "reserve_keys": list(raw.get("reserve_keys") or []),
        "headers": headers,
        "query_prefix": str(raw.get("query_prefix") or ""),
        "dimensions": int(raw.get("dimensions") or (base.get("default_dimensions") if base else 0) or 0),
        "extra": extra,
        "db_model_key": f"{provider}:{model}" if provider != "local" else resolved_model,
    }
