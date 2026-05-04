# src/presets/embedding_provider_presets.py
"""Built-in embedding provider presets (Gemini, OpenRouter, Custom API, Custom Local)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Each preset:
#   id          str   — unique key referenced by RAG_EMBED_PRESET_ID
#   name        str   — display name
#   provider    str   — 'local' | 'openai_compat' | 'gemini'
#   auth_mode   str   — 'bearer' | 'query' | 'none'
#   default_url str   — pre-filled API URL (empty for local/custom)
#   default_model str — pre-filled model name
#   known_models list — suggestions shown in combobox
#   default_dimensions int — hint for storage; 0 = unknown
#   default_headers    dict
#   key_url     str   — where to get an API key (shown as link in UI)
#   is_custom   bool  — if True, all fields are user-editable
#   is_local    bool  — if True, model field = HF id or local path

BUILTIN_EMBED_PROVIDER_PRESETS: List[Dict[str, Any]] = [
    # ── Local (HuggingFace / file path) ──────────────────────────────────────
    {
        "id": "local_hf",
        "name": "Local (HuggingFace / путь)",
        "provider": "local",
        "auth_mode": "none",
        "default_url": "",
        "default_model": "Qwen3-Embedding-0.6B (600M, 2025)",
        "known_models": [],
        "default_dimensions": 0,
        "default_headers": {},
        "default_extra": {
            "batch_size": 8,
            "request_delay_sec": 0.0,
            "timeout_sec": 60.0,
            "max_retries": 2,
            "retry_backoff_sec": 0.5,
        },
        "key_url": "",
        "is_custom": False,
        "is_local": True,
    },
    # ── Google Gemini ─────────────────────────────────────────────────────────
    {
        "id": "google_gemini_embed",
        "name": "Google Gemini Embeddings",
        "provider": "gemini",
        "auth_mode": "query",
        "default_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-embedding-001",
        "known_models": [
            "gemini-embedding-001",
            "text-embedding-004",
        ],
        "default_dimensions": 3072,
        "default_headers": {},
        "default_extra": {
            "batch_size": 100,
            "request_delay_sec": 0.25,
            "timeout_sec": 60.0,
            "max_retries": 3,
            "retry_backoff_sec": 0.7,
        },
        "key_url": "https://aistudio.google.com/app/apikey",
        "is_custom": False,
        "is_local": False,
    },
    # ── OpenRouter ────────────────────────────────────────────────────────────
    {
        "id": "openrouter_embed",
        "name": "OpenRouter Embeddings",
        "provider": "openai_compat",
        "auth_mode": "bearer",
        "default_url": "https://openrouter.ai/api/v1/embeddings",
        "default_model": "google/gemini-embedding-001",
        "known_models": [
            "google/gemini-embedding-001",
            "openai/text-embedding-3-small",
            "openai/text-embedding-3-large",
        ],
        "default_dimensions": 0,
        "default_headers": {
            "HTTP-Referer": "https://github.com/Atm4x/NeuroMita",
            "X-OpenRouter-Title": "NeuroMita",
        },
        "default_extra": {
            "batch_size": 128,
            "request_delay_sec": 0.35,
            "timeout_sec": 60.0,
            "max_retries": 3,
            "retry_backoff_sec": 0.7,
        },
        "key_url": "https://openrouter.ai/keys",
        "is_custom": False,
        "is_local": False,
    },
    # ── Custom OpenAI-compatible API ─────────────────────────────────────────
    {
        "id": "custom_openai_embed",
        "name": "Custom OpenAI-compatible API",
        "provider": "openai_compat",
        "auth_mode": "bearer",
        "default_url": "",
        "default_model": "",
        "known_models": [],
        "default_dimensions": 0,
        "default_headers": {},
        "default_extra": {
            "batch_size": 128,
            "request_delay_sec": 0.35,
            "timeout_sec": 60.0,
            "max_retries": 2,
            "retry_backoff_sec": 0.5,
        },
        "key_url": "",
        "is_custom": True,
        "is_local": False,
    },
    # ── Custom Local (HF id or filesystem path) ───────────────────────────────
    {
        "id": "custom_local",
        "name": "Custom Local (HF id или путь к папке)",
        "provider": "local",
        "auth_mode": "none",
        "default_url": "",
        "default_model": "",
        "known_models": [],
        "default_dimensions": 0,
        "default_headers": {},
        "default_extra": {
            "batch_size": 8,
            "request_delay_sec": 0.0,
            "timeout_sec": 60.0,
            "max_retries": 1,
            "retry_backoff_sec": 0.2,
        },
        "key_url": "",
        "is_custom": True,
        "is_local": True,
    },
]

# Fast lookup by id
_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in BUILTIN_EMBED_PROVIDER_PRESETS}


def get_builtin_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    return _BY_ID.get(preset_id)


def list_builtin_preset_ids() -> List[str]:
    return [p["id"] for p in BUILTIN_EMBED_PROVIDER_PRESETS]


def list_builtin_presets() -> List[Dict[str, Any]]:
    return list(BUILTIN_EMBED_PROVIDER_PRESETS)
