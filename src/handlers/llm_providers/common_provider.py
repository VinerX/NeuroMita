# src/handlers/llm_providers/common_provider.py
from __future__ import annotations

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class CommonProvider(OpenAIHTTPProviderBase):
    name = "common"
    priority = 30
    supports_tools_native = True

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)