# src/managers/provider_manager.py
from typing import List, Optional
from handlers.llm_providers.base import BaseProvider, LLMRequest
from handlers.llm_providers.openai_provider import OpenAIProvider
from handlers.llm_providers.gemini_provider import GeminiProvider
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.g4f_provider import G4FProvider
from handlers.llm_providers.openrouter_provider import OpenRouterProvider
from handlers.llm_providers.aiio_provider import AiIOProvider
from handlers.llm_providers.mistral_provider import MistralProvider

from main_logger import logger


from handlers.llm_providers.message_preprocessor import preprocess_messages_for_provider


class ProviderManager:
    def __init__(self):
        self._providers: List[BaseProvider] = []
        self._register_providers()

    def _register_providers(self):
        self._providers = [
            OpenAIProvider(),
            GeminiProvider(),
            OpenRouterProvider(),
            AiIOProvider(),
            MistralProvider(),
            CommonProvider(),
            G4FProvider()
        ]
        self._providers.sort(key=lambda p: p.priority)
        logger.info(f"Registered {len(self._providers)} providers")

    def generate(self, req: LLMRequest) -> Optional[str]:
        for provider in self._providers:
            if provider.is_applicable(req):
                logger.info(f"Using provider: {provider.name}")

                preprocess_messages_for_provider(req, provider)

                return provider.generate(req)
        logger.error("No provider can handle this request")
        raise RuntimeError("No provider can handle this request")