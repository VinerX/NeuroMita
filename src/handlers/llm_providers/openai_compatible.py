# src/handlers/llm_providers/openai_compatible.py
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from main_logger import logger
from .base import BaseProvider, LLMRequest


class OpenAICompatibleProvider(BaseProvider, ABC):
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False

    tools_dialect_id: str = "openai"

    @abstractmethod
    def _get_client(self, req: LLMRequest) -> Any:
        pass

    def _get_model_to_use(self, req: LLMRequest) -> str:
        return req.model

    def generate(self, req: LLMRequest) -> Optional[str]:
        return self._generate(req)

    def _generate(self, req: LLMRequest) -> Optional[str]:
        if req.depth > 3:
            logger.error(f"Слишком много рекурсивных tool-вызовов ({self.name}).")
            return None

        model_to_use = self._get_model_to_use(req)
        client = self._get_client(req)
        if not client:
            return None

        try:
            cleaned_messages = [{k: v for k, v in m.items() if k != "time"} for m in (req.messages or [])]

            params: Dict[str, Any] = {"model": model_to_use, "messages": cleaned_messages}
            params.update(self._map_unified_params(req.extra or {}, model_to_use))

            # NEW: tools payload строит провайдер
            if req.tools_on and req.tools_mode == "native" and req.tool_manager:
                dialect = req.tools_dialect or self.tools_dialect_id
                tools_payload = req.tools_payload or req.tool_manager.get_tools_payload(dialect)
                if tools_payload:
                    params["tools"] = tools_payload
                    params["stream"] = False

            completion = client.chat.completions.create(**params, stream=req.stream)

            if req.stream:
                return self._handle_stream(completion, req.stream_cb)

            if completion and getattr(completion, "choices", None):
                message = completion.choices[0].message
                tool_calls = getattr(message, "tool_calls", None)

                if tool_calls:
                    tm = req.tool_manager
                    dialect = req.tools_dialect or self.tools_dialect_id

                    for tool_call in tool_calls:
                        call_id = getattr(tool_call, "id", None)
                        name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)

                        tool_result = tm.run(name, args)

                        req.messages.append(tm.mk_tool_call_msg(dialect, name, args, tool_call_id=call_id))
                        req.messages.append(tm.mk_tool_resp_msg(dialect, name, tool_result, tool_call_id=call_id))

                    req.depth += 1
                    return self._generate(req)

                content = message.content
                if not content:
                    content = getattr(message, "reasoning_content", None)
                if not content:
                    content = (getattr(message, "model_extra", None) or {}).get("reasoning_content")
                if not content:
                    try:
                        raw_dict = completion.model_dump()
                        msg_dict = (raw_dict.get("choices") or [{}])[0].get("message") or {}
                        content = msg_dict.get("reasoning_content")
                    except Exception:
                        pass
                return content.strip() if content else None

            logger.warning(f"[{self.name}] No completion choices.")
            return None

        except Exception as e:
            logger.error(f"[{self.name}] Error during API call: {e}", exc_info=True)
            return None

    def _map_unified_params(self, unified: Dict[str, Any], model_to_use: str) -> Dict[str, Any]:
        u = unified or {}
        m = (model_to_use or "").lower()
        out: Dict[str, Any] = {}

        for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
            if k in u:
                out[k] = u[k]

        if "top_k" in u and "deepseek" in m:
            out["top_k"] = u["top_k"]

        if "enable_thinking" in u:
            out["enable_thinking"] = bool(u["enable_thinking"])

        if "logprobs" in u:
            lp = u["logprobs"]
            out["logprobs"] = lp if isinstance(lp, bool) else bool(lp)

        return out

    def _handle_stream(self, completion, stream_callback=None) -> str:
        parts: List[str] = []
        try:
            for chunk in completion:
                text = ""
                try:
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta
                        text = delta.content or ""
                        # Qwen3 thinking-режим: контент идёт в reasoning_content
                        if not text:
                            text = getattr(delta, "reasoning_content", None) or ""
                        if not text:
                            text = (getattr(delta, "model_extra", None) or {}).get("reasoning_content", "")
                except Exception:
                    continue

                if text:
                    if stream_callback:
                        stream_callback(text)
                    parts.append(text)
        except Exception as e:
            logger.error(f"[{self.name}] stream error: {e}", exc_info=True)

        return "".join(parts)