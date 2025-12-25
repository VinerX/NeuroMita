# src/managers/tools/legacy_executor.py
from __future__ import annotations

import json
import re
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from main_logger import logger


class LegacyToolExecutor:
    """
    Вынесенная логика legacy tools:
    - парсит вызовы инструментов из текста (regex)
    - исполняет их через ToolManager
    - добавляет сообщения tool_call/tool_resp в messages
    - инициирует повторную генерацию через переданную функцию generate_fn
    """

    def __init__(self, settings, tool_manager, preset_resolver):
        self.settings = settings
        self.tool_manager = tool_manager
        self.preset_resolver = preset_resolver

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

        parse_regex = self.settings.get(
            "LEGACY_TOOLS_PARSE_REGEX",
            r'\{.*?"tool":\s*"(.*?)",\s*"args":\s*(\{.*?\})\}'
        )

        matches = re.findall(parse_regex, response_text, flags=re.S)
        if not matches:
            return response_text

        try:
            preset = self.preset_resolver.resolve(preset_id)
            dialect = "gemini" if (preset.make_request and preset.gemini_case) else "openai"
        except Exception:
            dialect = "openai"

        cleaned_text = response_text

        for tool_name, args_str in matches:
            try:
                args = json.loads(args_str)
            except Exception as e:
                logger.error(f"Legacy tool parse args failed: {e}")
                messages.append({"role": "system", "content": f"Tool call failed (bad args json): {e}"})
                continue

            try:
                logger.info(f"Legacy tool call: {tool_name}({args})")
                tool_result = self.tool_manager.run(tool_name, args)

                call_id = f"call_{uuid.uuid4().hex[:8]}"

                messages.append(self.tool_manager.mk_tool_call_msg(dialect, tool_name, args, tool_call_id=call_id))
                messages.append(self.tool_manager.mk_tool_resp_msg(dialect, tool_name, tool_result, tool_call_id=call_id))

                cleaned_text = re.sub(parse_regex, "", cleaned_text, flags=re.S).strip()

            except Exception as e:
                logger.error(f"Ошибка legacy tool: {e}", exc_info=True)
                messages.append({"role": "system", "content": f"Tool call failed: {e}"})

        new_response, _ok = generate_fn(messages, stream_callback, preset_id)
        return new_response or cleaned_text