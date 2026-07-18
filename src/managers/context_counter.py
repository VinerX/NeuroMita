# src/managers/context_counter.py
from __future__ import annotations

import json
from typing import Any, Dict, List

from main_logger import logger


class ContextCounter:
    """Оценка числа токенов в сообщениях без побочных эффектов (не строит промпт).

    Если доступен tiktoken — используем его (точнее). Если нет (а в рантайме игры
    его часто нет: отдельная зависимость + первый запуск tiktoken тянет данные
    кодировки из сети) — не сдаёмся, а считаем по эвристике (символы/слова).
    Это всё равно оценка «для сравнения масштаба», поэтому важнее, чтобы цифры
    были всегда, чем чтобы они точно совпадали с биллингом провайдера.
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
            logger.info("tiktoken не найден — оценка токенов по эвристике (символы/слова).")
        except Exception as e:
            # encoding_for_model может пытаться скачать данные кодировки и упасть
            # без сети — тогда тоже переходим на эвристику, а не отключаем счётчик.
            logger.info(f"tiktoken init failed ({e}) — оценка токенов по эвристике.")

    @property
    def available(self) -> bool:
        # Оценку можем дать всегда: либо tiktoken, либо эвристика.
        return True

    @property
    def is_exact(self) -> bool:
        """True только когда считаем настоящим токенайзером (tiktoken)."""
        return bool(self._has_tokenizer and self._tokenizer)

    @property
    def method(self) -> str:
        return f"tiktoken:{self.encoding_model}" if self.is_exact else "heuristic"

    @staticmethod
    def _heuristic_tokens(text: str) -> int:
        """Оценка токенов без токенайзера.

        Латиница ~ 4 символа/токен, но кириллица и JSON дробятся мельче. Берём
        максимум из «символы/4» и «слова×1.3» и добавляем надбавку за не-ASCII
        (русский текст), чтобы не занижать оценку вдвое. Это грубо, но
        применяется единообразно ко всем блокам, поэтому пропорции сохраняются.
        """
        if not text:
            return 0
        chars = len(text)
        words = len(text.split())
        non_ascii = sum(1 for c in text if ord(c) > 127)
        est = max(chars / 4.0, words * 1.3) + non_ascii * 0.5
        return max(1, int(round(est)))

    def _encode_len(self, text: str) -> int:
        text = str(text or "")
        if not text:
            return 0
        if self.is_exact:
            try:
                return len(self._tokenizer.encode(text))
            except Exception:
                pass
        return self._heuristic_tokens(text)

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
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
                    total += self._encode_len(json.dumps(msg["tool_calls"], ensure_ascii=False))
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
        if isinstance(content, str):
            return self._encode_len(content)

        if isinstance(content, list):
            cnt = 0
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and item.get("text"):
                    cnt += self._encode_len(str(item["text"]))
                elif item.get("type") in ("image_url", "image"):
                    # Изображения не токенизируются текстовым токенайзером, и у
                    # каждого провайдера считаются по-своему (tiles/detail).
                    # Раньше приписывали фиктивные +1000 — это врало о масштабе.
                    # Теперь в текстовую оценку не включаем; их наличие считается
                    # отдельно (см. _compute_token_usage) и показывается пометкой.
                    continue
                else:
                    try:
                        cnt += self._encode_len(json.dumps(item, ensure_ascii=False))
                    except Exception:
                        pass
            return cnt

        if isinstance(content, dict):
            try:
                return self._encode_len(json.dumps(content, ensure_ascii=False))
            except Exception:
                return 0

        return self._encode_len(str(content))
