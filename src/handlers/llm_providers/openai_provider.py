# src/handlers/llm_providers/openai_provider.py
from __future__ import annotations

import threading

from openai import OpenAI
from main_logger import logger

from .base import (
    LLMRequest,
)
from .errors import build_provider_error
from .http_transport import estimate_json_size, resolve_httpx_timeout
from .openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    priority = 10
    supports_stream_usage = True

    def __init__(self, *, http_transport=None) -> None:
        super().__init__(http_transport=http_transport)
        self._clients: dict[tuple[str, str], OpenAI] = {}
        self._clients_lock = threading.RLock()

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def _get_client(self, req: LLMRequest):
        if not req.api_key:
            logger.error("OpenAI API key is not available.")
            raise build_provider_error(
                self.name,
                status_code=401,
                provider_message="OpenAI API key is not available.",
                url=req.api_url,
            )
        try:
            base_url = str(req.api_url or "https://api.openai.com/v1")
            payload_size = estimate_json_size({
                "messages": req.messages,
                "tools": req.tools_payload,
            })
            timeout = resolve_httpx_timeout(req, payload_size_bytes=payload_size)
            key = (base_url, str(req.api_key))
            with self._clients_lock:
                client = self._clients.get(key)
                if client is None:
                    client = OpenAI(
                        api_key=req.api_key,
                        base_url=base_url,
                        http_client=self.http_transport.client_for_url(base_url),
                        timeout=timeout,
                        max_retries=0,
                    )
                    self._clients[key] = client
            return client.with_options(
                timeout=timeout,
                max_retries=0,
            )
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
            raise build_provider_error(
                self.name,
                provider_message=f"Failed to initialize OpenAI client: {e}",
                url=req.api_url,
            ) from e

    def _release_client(self, client) -> None:
        return None

    def close(self) -> None:
        with self._clients_lock:
            self._clients.clear()
        super().close()
