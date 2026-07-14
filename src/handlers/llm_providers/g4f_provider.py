# src/handlers/llm_providers/g4f_provider.py
from __future__ import annotations

from main_logger import logger

from .base import LLMRequest, register_cancellable_resource
from .openai_compatible import OpenAICompatibleProvider


class G4FProvider(OpenAICompatibleProvider):
    name = "g4f"
    priority = 40

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def _get_model_to_use(self, req: LLMRequest) -> str:
        return (req.model or "gpt-3.5-turbo").strip()

    def _get_client(self, req: LLMRequest):
        try:
            from g4f.client import Client as g4fClient
            return register_cancellable_resource(req, g4fClient())
        except ImportError:
            logger.error(
                "g4f provider is selected, but the optional g4f package is not installed. "
                "Automatic installation is disabled.",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(f"g4f import failed unexpectedly: {e}", exc_info=True)
            return None