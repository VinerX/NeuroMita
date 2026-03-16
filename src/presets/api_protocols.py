# src/presets/api_protocols.py
from __future__ import annotations


class Dialects:
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"
    G4F = "g4f"


API_PROTOCOLS_DATA = [
    {
        "id": "mistral_default",
        "name": "Mistral (OpenAI-compatible)",
        "dialect": Dialects.OPENAI_CHAT_COMPLETIONS,
        "provider": "common",
        "auth": {"mode": "bearer"},
        "headers": {},
        "capabilities": {"tools_native": True, "streaming": True, "streaming_with_tools": False, "structured_output": True},
        "transforms": [
            {"id": "merge_system_messages"},
            {"id": "ensure_last_message_user", "params": {"fallback_user_text": "."}},
        ],
    },
    {
        "id": "openrouter_default",
        "name": "OpenRouter (OpenAI-compatible)",
        "dialect": Dialects.OPENAI_CHAT_COMPLETIONS,
        "provider": "common",
        "auth": {"mode": "bearer"},
        "headers": {"HTTP-Referer": "https://github.com/Atm4x/NeuroMita", "X-Title": "NeuroMita"},
        # OpenRouter aggregates many providers — not all support json_schema,
        # so use json_object (softer mode, relies on prompt) to avoid 400 errors.
        "capabilities": {"tools_native": True, "streaming": True, "streaming_with_tools": False, "structured_output": True, "structured_output_mode": "json_object"},
        "transforms": [{"id": "merge_system_messages"}],
    },
    {
        "id": "openai_compatible_default",
        "name": "OpenAI-compatible (Generic)",
        "dialect": Dialects.OPENAI_CHAT_COMPLETIONS,
        "provider": "common",
        "auth": {"mode": "bearer"},
        "headers": {},
        "capabilities": {"tools_native": True, "streaming": True, "streaming_with_tools": False, "structured_output": True},
        "transforms": [{"id": "merge_system_messages"}],
    },
    {
        "id": "aiio_default",
        "name": "Ai.iO (OpenAI-compatible)",
        "dialect": Dialects.OPENAI_CHAT_COMPLETIONS,
        "provider": "common",
        "auth": {"mode": "bearer"},
        "headers": {},
        "capabilities": {"tools_native": False, "streaming": True, "streaming_with_tools": False, "structured_output": False},
        "transforms": [{"id": "system_to_user_prefix", "params": {"tag": "[SYSTEM CONTEXT]"}}],
    },
    {
        "id": "google_gemini_default",
        "name": "Google Gemini API (generateContent)",
        "dialect": Dialects.GEMINI_GENERATE_CONTENT,
        "provider": "gemini",
        "auth": {"mode": "query", "param": "key"},
        "headers": {"Content-Type": "application/json"},
        "capabilities": {"tools_native": True, "streaming": True, "streaming_with_tools": False, "structured_output": True},
        "transforms": [],
    },
    {
        "id": "g4f_default",
        "name": "GPT4Free",
        "dialect": Dialects.G4F,
        "provider": "g4f",
        "auth": {"mode": "none"},
        "headers": {},
        "capabilities": {"tools_native": False, "streaming": False, "streaming_with_tools": False, "structured_output": False},
        "transforms": [],
    },
]