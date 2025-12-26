# src/handlers/llm_providers/openrouter_provider.py
from __future__ import annotations

from typing import Dict

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class OpenRouterProvider(OpenAIHTTPProviderBase):
    name = "openrouter"
    priority = 25  # раньше common, позже gemini/openai

    def is_applicable(self, req: LLMRequest) -> bool:
        if req.g4f_flag:
            return False
        if not req.make_request:
            return False
        if req.gemini_case:
            return False
        url = (req.api_url or "").lower()
        return "openrouter.ai" in url

    def _headers(self, req: LLMRequest) -> Dict[str, str]:
        headers = super()._headers(req)
        # рекомендуемые OpenRouter headers
        headers.setdefault("HTTP-Referer", "https://github.com/Atm4x/NeuroMita")
        headers.setdefault("X-Title", "NeuroMita")
        return headers