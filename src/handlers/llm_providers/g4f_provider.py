# src/handlers/llm_providers/g4f_provider.py
from __future__ import annotations

from main_logger import logger

from .base import LLMRequest
from .openai_compatible import OpenAICompatibleProvider


class G4FProvider(OpenAICompatibleProvider):
    name = "g4f"
    priority = 40

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.g4f_flag)

    def _get_model_to_use(self, req: LLMRequest) -> str:
        return (req.g4f_model or "gpt-3.5-turbo").strip()

    def _get_client(self, req: LLMRequest):
        # 1) пробуем импорт
        try:
            from g4f.client import Client as g4fClient
            return g4fClient()
        except ImportError:
            logger.info("g4f not found. Attempting install (if pip_installer provided)...")

        # 2) установка (перенесена из chat_handler)
        pip_installer = getattr(req, "pip_installer", None)
        settings = getattr(req, "settings", None)

        if not pip_installer or not settings:
            logger.error("g4f not available and cannot be installed: pip_installer/settings not provided.")
            return None

        target_version = settings.get("G4F_VERSION", "0.4.7.7")
        package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"

        try:
            ok = pip_installer.install_package(
                package_spec,
                description=f"Installing g4f version {target_version}..."
            )
            if not ok:
                logger.error("g4f installation failed.")
                return None
        except Exception as e:
            logger.error(f"g4f installation raised exception: {e}", exc_info=True)
            return None

        try:
            import importlib
            importlib.invalidate_caches()
        except Exception:
            pass

        try:
            from g4f.client import Client as g4fClient
            return g4fClient()
        except Exception as e:
            logger.error(f"g4f still not importable after install: {e}", exc_info=True)
            return None