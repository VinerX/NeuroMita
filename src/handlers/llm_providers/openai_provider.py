# src/handlers/llm_providers/openai_provider.py
from __future__ import annotations

from openai import OpenAI
from main_logger import logger

from .base import LLMRequest
from .openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    priority = 10

    def is_applicable(self, req: LLMRequest) -> bool:
        if req.make_request:
            return False
        if req.g4f_flag:
            return False
        model_lower = (req.model or "").lower()
        return any(prefix in model_lower for prefix in ["gpt-", "deepseek-", "o1-", "chatgpt"])

    def _get_client(self, req: LLMRequest):
        if not req.api_key:
            logger.error("OpenAI API key is not available.")
            return None
        try:
            if req.api_url:
                return OpenAI(api_key=req.api_key, base_url=req.api_url)
            return OpenAI(api_key=req.api_key)
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
            return None