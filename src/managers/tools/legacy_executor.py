# src/managers/tools/legacy_executor.py
from __future__ import annotations

import json
import random
import re
import string
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from main_logger import logger


class LegacyToolExecutor:
    """
    Вынесенная логика legacy tools:
    - парсит вызовы инструментов из текста (раньше: regex; теперь: JSONDecoder scan)
    - исполняет их через ToolManager
    - добавляет сообщения tool_call/tool_resp в messages
    - инициирует повторную генерацию через переданную функцию generate_fn
    """

    def __init__(self, settings, tool_manager, preset_resolver):
        self.settings = settings
        self.tool_manager = tool_manager
        self.preset_resolver = preset_resolver

    def _extract_legacy_tool_calls(self, text: str) -> List[Tuple[str, dict]]:
        """
        Устойчивое извлечение legacy tool-вызовов из произвольного текста.

        Ищет JSON-объекты вида:
          { "tool": "...", "args": { ... } }

        В отличие от regex, корректно переживает вложенные {} внутри args,
        потому что использует JSONDecoder.raw_decode и сканирует текст по '{'.
        """
        if not isinstance(text, str) or not text:
            return []

        decoder = json.JSONDecoder()
        calls: List[Tuple[str, dict]] = []

        i = 0
        n = len(text)

        while i < n:
            if text[i] != "{":
                i += 1
                continue

            try:
                obj, end_rel = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                # Не начало корректного JSON
                i += 1
                continue
            except Exception:
                i += 1
                continue

            end_abs = i + end_rel

            if isinstance(obj, dict) and "tool" in obj and "args" in obj:
                tool_name = obj.get("tool")
                args = obj.get("args")

                if isinstance(tool_name, str) and tool_name.strip():
                    # Нормализуем args к dict
                    if args is None:
                        args = {}
                    elif isinstance(args, str):
                        # Иногда модель кладет args как JSON-строку
                        try:
                            parsed = json.loads(args)
                            args = parsed if isinstance(parsed, dict) else {}
                        except Exception:
                            args = {"_raw_args": args}
                    elif not isinstance(args, dict):
                        args = {}

                    calls.append((tool_name, args))

            # Перепрыгиваем распарсенный JSON-объект целиком
            i = max(end_abs, i + 1)

        return calls

    def process(
        self,
        response_text: str,
        messages: List[Dict],
        generate_fn: Callable[[List[Dict], Optional[callable], Optional[int]], Tuple[Optional[str], bool]],
        stream_callback: Optional[callable] = None,
        preset_id: Optional[int] = None,
        depth: int = 0,
    ) -> str:
        if depth > 3:
            logger.error("Слишком много рекурсивных legacy tool-вызовов.")
            return response_text

        if not isinstance(response_text, str) or not response_text.strip():
            return response_text

        # Вместо regex: устойчивое извлечение JSON-вызовов (не ломается на вложенных args).
        calls = self._extract_legacy_tool_calls(response_text)
        if not calls:
            return response_text

        try:
            preset = self.preset_resolver.resolve(preset_id)
            dialect = "gemini" if (preset.make_request and preset.gemini_case) else "openai"
        except Exception:
            dialect = "openai"

        # ВАЖНО: убираем весь исходный текст модели, чтобы при повторной генерации
        # в истории были только Tool Call / Tool Response, без пред-объяснений.
        cleaned_text = ""

        for tool_name, args in calls:
            try:
                logger.info(f"Legacy tool call: {tool_name}({args})")
                tool_result = self.tool_manager.run(tool_name, args)
                logger.info(f"Legacy tool result: {tool_result})")

                call_id = f"call_{uuid.uuid4().hex[:8]}"

                # Временная заглушка
                chars = string.ascii_letters + string.digits
                call_id = "".join(random.choices(chars, k=9))

                messages.append(self.tool_manager.mk_tool_call_msg(dialect, tool_name, args, tool_call_id=call_id))
                messages.append(
                    self.tool_manager.mk_tool_resp_msg(dialect, tool_name, tool_result, tool_call_id=call_id)
                )

            except Exception as e:
                logger.error(f"Ошибка legacy tool: {e}", exc_info=True)
                messages.append({"role": "system", "content": f"Tool call failed: {e}"})

        new_response, _ok = generate_fn(messages, stream_callback, preset_id)
        return new_response or cleaned_text