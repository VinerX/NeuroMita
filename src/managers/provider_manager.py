# src/managers/provider_manager.py
from typing import List, Optional

from main_logger import logger
from handlers.llm_providers.base import BaseProvider, LLMRequest
from handlers.llm_providers.openai_provider import OpenAIProvider
from handlers.llm_providers.gemini_provider import GeminiProvider
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.g4f_provider import G4FProvider

from handlers.llm_providers.message_preprocessor import preprocess_messages_for_provider
from handlers.llm_providers.message_transforms import apply_transforms


class ProviderManager:
    def __init__(self):
        self._providers: List[BaseProvider] = []
        self._register_providers()

    def _register_providers(self):
        self._providers = [
            OpenAIProvider(),
            GeminiProvider(),
            CommonProvider(),
            G4FProvider(),
        ]
        self._providers.sort(key=lambda p: p.priority)
        logger.info(f"Registered {len(self._providers)} providers: {[p.name for p in self._providers]}")

    def _find_by_name(self, name: str) -> Optional[BaseProvider]:
        if not name:
            return None
        for p in self._providers:
            if getattr(p, "name", None) == name:
                return p
        return None

    def _enforce_capabilities(self, req: LLMRequest) -> None:
        caps = req.capabilities or {}

        if "streaming" in caps and not bool(caps.get("streaming")):
            req.stream = False

        if req.tools_on and req.tools_mode == "native":
            if "tools_native" in caps and not bool(caps.get("tools_native")):
                req.tools_on = False

            if req.stream and ("streaming_with_tools" in caps) and not bool(caps.get("streaming_with_tools")):
                req.stream = False

    def generate(self, req: LLMRequest) -> Optional[str]:
        if not req.provider_name:
            logger.error("Protocol-driven routing requires provider_name in request")
            raise RuntimeError("No provider can handle this request")

        provider = self._find_by_name(req.provider_name)
        if not provider:
            logger.error(f"No provider registered with name '{req.provider_name}'")
            raise RuntimeError("No provider can handle this request")

        self._enforce_capabilities(req)

        trace = {
            "protocol_id": req.protocol_id,
            "dialect_id": req.dialect_id,
            "provider_name": req.provider_name,
            "transforms": req.transforms or [],
            "transform_trace": [],
        }

        if req.transforms:
            req.messages, ttrace = apply_transforms(req.messages, req.transforms)
            trace["transform_trace"] = ttrace

        req.extra["_protocol_trace"] = trace

        logger.info(f"Using provider: {provider.name} | protocol={req.protocol_id} | dialect={req.dialect_id}")
        logger.debug(f"Protocol trace: {trace}")

        preprocess_messages_for_provider(req, provider)
        return provider.generate(req)