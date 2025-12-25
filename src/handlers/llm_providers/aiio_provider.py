# src/handlers/llm_providers/aiio_provider.py
from __future__ import annotations

from typing import Any, Dict, List

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class AiIOProvider(OpenAIHTTPProviderBase):
    name = "aiio"
    priority = 26  # раньше common, чтобы перехватывать

    # AI.IO: tools выключаем на уровне провайдера (как в PR)
    supports_tools_native = False

    def is_applicable(self, req: LLMRequest) -> bool:
        if req.g4f_flag:
            return False
        if not req.make_request:
            return False
        if req.gemini_case:
            return False
        url = (req.api_url or "").lower()
        return "intelligence.io.solutions" in url

    def _supports_tools_for_req(self, req: LLMRequest) -> bool:
        return False

    def _normalize_messages(self, req: LLMRequest, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        AI.IO иногда плохо принимает system role. Безопасная стратегия:
        - собрать все system сообщения в текстовый префикс
        - удалить system из messages
        - добавить префикс в первое user сообщение (или создать user)
        """
        system_texts: List[str] = []
        out: List[Dict[str, Any]] = []

        for m in messages:
            role = m.get("role")
            if role == "system":
                c = m.get("content", "")
                if isinstance(c, str) and c.strip():
                    system_texts.append(c.strip())
                else:
                    # если не строка — всё равно сериализуем
                    try:
                        system_texts.append(str(c))
                    except Exception:
                        pass
                continue
            out.append(m)

        if not system_texts:
            return out

        prefix = "\n\n".join(f"[SYSTEM CONTEXT] {t}" for t in system_texts).strip()

        # найти первое user сообщение
        for m in out:
            if m.get("role") != "user":
                continue

            content = m.get("content")
            # OpenAI multimodal list
            if isinstance(content, list):
                # вставить/дописать в первый text chunk
                inserted = False
                for chunk in content:
                    if isinstance(chunk, dict) and chunk.get("type") == "text":
                        chunk["text"] = f"{prefix}\n\n{chunk.get('text','')}"
                        inserted = True
                        break
                if not inserted:
                    content.insert(0, {"type": "text", "text": prefix})
                return out

            # plain string content
            if isinstance(content, str):
                m["content"] = f"{prefix}\n\n{content}"
                return out

            # fallback
            m["content"] = f"{prefix}\n\n{str(content)}"
            return out

        # нет user сообщения — создаём
        out.append({"role": "user", "content": prefix})
        return out