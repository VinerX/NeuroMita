# src/handlers/llm_providers/openrouter_provider.py
from __future__ import annotations

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class OpenRouterProvider(OpenAIHTTPProviderBase):
    name = "openrouter"
    priority = 25

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)