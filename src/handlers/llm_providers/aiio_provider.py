# src/handlers/llm_providers/aiio_provider.py
from __future__ import annotations

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class AiIOProvider(OpenAIHTTPProviderBase):
    name = "aiio"
    priority = 26

    supports_tools_native = False

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def _supports_tools_for_req(self, req: LLMRequest) -> bool:
        return False