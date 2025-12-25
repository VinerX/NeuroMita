# src/handlers/llm_providers/mistral_provider.py
from __future__ import annotations

from typing import Any, Dict, List

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class MistralProvider(OpenAIHTTPProviderBase):
    name = "mistral"
    priority = 27  # раньше common

    def is_applicable(self, req: LLMRequest) -> bool:
        if req.g4f_flag:
            return False
        if not req.make_request:
            return False
        if req.gemini_case:
            return False
        url = (req.api_url or "").lower()
        # mistral официальный endpoint
        return "api.mistral.ai" in url

    def _normalize_messages(self, req: LLMRequest, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Менее агрессивно, чем AI.IO:
        - объединяем все system в один system (чтобы не было кучи system сообщений)
        - порядок: [system] + остальное
        """
        system_parts: List[str] = []
        rest: List[Dict[str, Any]] = []

        for m in messages:
            if m.get("role") == "system":
                c = m.get("content", "")
                if isinstance(c, str) and c.strip():
                    system_parts.append(c.strip())
                else:
                    try:
                        system_parts.append(str(c))
                    except Exception:
                        pass
            else:
                rest.append(m)

        if not system_parts:
            return messages

        system_msg = {"role": "system", "content": "\n\n".join(system_parts)}
        return [system_msg] + rest