from functools import lru_cache

import qtawesome as qta
from ui.svg_icons import svg_icon


def template_provider(name: str, protocol_id: str = "") -> str:
    return {
        "Mistral AI": "mistral", "OpenRouter": "openrouter",
        "Google AI Studio": "google", "Ai.iO": "aiio",
        "ProxyAPI": "proxyapi", "Groq": "groq", "Together AI": "together",
        "Chutes": "chutes", "KodikRouter": "kodikrouter",
        "LM Studio": "lmstudio", "Ollama": "ollama",
    }.get(name, protocol_provider(protocol_id))


def protocol_provider(protocol_id: str) -> str:
    return {
        "google_gemini_default": "gemini",
        "openai_compatible_default": "",
        "openrouter_default": "openrouter",
        "mistral_default": "mistral",
        "lmstudio_default": "lmstudio",
    }.get(protocol_id, "")


@lru_cache(maxsize=32)
def provider_icon(provider: str):
    svg_names = {
        "google": "google", "gemini": "google", "openai": "openai",
        "mistral": "mistral-color", "openrouter": "openrouter", "groq": "groq",
        "together": "together-color", "chutes": "chutes", "aiio": "aiio",
        "proxyapi": "proxyapi", "kodikrouter": "kodikrouter",
        "lmstudio": "lmstudio", "ollama": "ollama",
    }
    name = svg_names.get(str(provider).lower())
    if name:
        color = {"openrouter": "#c8ff00", "groq": "#f43e01"}.get(str(provider).lower())
        return svg_icon("providers/" + name, color=color)
    names = {
        "gemini": ("fa5b.google", "#4285f4"),
        "google": ("fa5b.google", "#4285f4"),
        "openai": ("fa6b.openai", "#e8edf5"),
        "openrouter": ("fa5s.route", "#a991e8"),
        "mistral": ("fa5s.wind", "#eea052"),
        "deepseek": ("fa5s.water", "#619afa"),
        "lmstudio": ("fa5s.desktop", "#9cbde6"),
    }
    name, color = names.get(str(provider).lower(), ("fa5s.plug", "#aab2c5"))
    try:
        return qta.icon(name, color=color)
    except Exception:
        return qta.icon("fa5s.robot" if provider == "openai" else "fa5s.plug", color=color)


