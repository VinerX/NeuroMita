# src/managers/context_counter.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from main_logger import logger


class ContextCounter:
    """
    Считает токены в сообщениях без побочных эффектов (не строит промпт).
    Опционально использует tiktoken. Если tiktoken нет — возвращает 0.
    """

    def __init__(self, encoding_model: str = "gpt-4o-mini"):
        self.encoding_model = encoding_model
        self._tokenizer = None
        self._has_tokenizer = False

        try:
            import tiktoken
            self._tokenizer = tiktoken.encoding_for_model(encoding_model)
            self._has_tokenizer = True
        except ImportError:
            logger.warning("tiktoken не найден — подсчёт токенов отключён.")
        except Exception as e:
            logger.warning(f"tiktoken init failed: {e}")

    @property
    def available(self) -> bool:
        return bool(self._has_tokenizer and self._tokenizer)

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        if not self.available:
            return 0
        if not messages:
            return 0

        total = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue

            if "content" in msg:
                total += self._count_content(msg["content"])

            if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
                try:
                    total += len(self._tokenizer.encode(json.dumps(msg["tool_calls"], ensure_ascii=False)))
                except Exception:
                    pass

        return int(total)

    def with_user_text(self, base_messages: List[Dict[str, Any]], user_text: str) -> List[Dict[str, Any]]:
        """
        Возвращает новый список messages = base + user_message(text-only).
        Ничего не мутирует в base_messages.
        """
        user_text = user_text or ""
        out = list(base_messages) if base_messages else []

        if not user_text.strip():
            return out

        out.append({
            "role": "user",
            "content": [{"type": "text", "text": user_text}]
        })
        return out

    def _count_content(self, content: Any) -> int:
        if not self.available:
            return 0

        if isinstance(content, str):
            return len(self._tokenizer.encode(content))

        if isinstance(content, list):
            cnt = 0
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and item.get("text"):
                    cnt += len(self._tokenizer.encode(str(item["text"])))
                elif item.get("type") == "image_url" and item.get("image_url", {}).get("url"):
                    cnt += 1000
                else:
                    try:
                        cnt += len(self._tokenizer.encode(json.dumps(item, ensure_ascii=False)))
                    except Exception:
                        pass
            return cnt

        if isinstance(content, dict):
            try:
                return len(self._tokenizer.encode(json.dumps(content, ensure_ascii=False)))
            except Exception:
                return 0

        try:
            return len(self._tokenizer.encode(str(content)))
        except Exception:
            return 0