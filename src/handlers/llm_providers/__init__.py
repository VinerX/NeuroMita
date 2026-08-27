from __future__ import annotations

from importlib import import_module

from .base import BaseProvider, LLMRequest, LLMResponse

_LAZY_EXPORTS = {
    "OpenAIProvider": ("handlers.llm_providers.openai_provider", "OpenAIProvider"),
    "GeminiProvider": ("handlers.llm_providers.gemini_provider", "GeminiProvider"),
    "CommonProvider": ("handlers.llm_providers.common_provider", "CommonProvider"),
    "G4FProvider": ("handlers.llm_providers.g4f_provider", "G4FProvider"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = [
    "BaseProvider",
    "LLMRequest",
    "LLMResponse",
    *sorted(_LAZY_EXPORTS),
]
