# src/handlers/llm_providers/openai_compatible.py
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from main_logger import logger
from .base import BaseProvider, LLMRequest


class OpenAICompatibleProvider(BaseProvider, ABC):
    """
    Общая логика:
    - чистка messages от 'time'
    - маппинг canonical params -> допустимые kwargs для openai-compatible
    - tools (native) => stream off
    - streaming handler
    - tool_calls recursion
    """

    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False

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
            self._change_last_message_to_user_for_gemini(model_to_use, req.messages)

            cleaned_messages = [{k: v for k, v in m.items() if k != "time"} for m in (req.messages or [])]

            params: Dict[str, Any] = {
                "model": model_to_use,
                "messages": cleaned_messages,
            }
            params.update(self._map_unified_params(req.extra or {}, model_to_use))

            if req.tools_on and req.tools_mode == "native" and req.tools_payload:
                params["tools"] = req.tools_payload
                # OpenAI-compatible инструменты часто ломают streaming
                params["stream"] = False

            logger.info(
                f"[{self.name}] completion: model={model_to_use}, "
                f"temp={params.get('temperature')}, max_tokens={params.get('max_tokens')}, stream={req.stream}"
            )

            completion = client.chat.completions.create(**params, stream=req.stream)

            if req.stream:
                return self._handle_stream(completion, req.stream_cb)

            if completion and getattr(completion, "choices", None):
                message = completion.choices[0].message

                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    tm = req.tool_manager or (req.extra or {}).get("tool_manager")
                    if tm:
                        for tool_call in tool_calls:
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments)
                            from tools.manager import mk_tool_call_msg, mk_tool_resp_msg
                            tool_result = tm.run(name, args)
                            req.messages.append(mk_tool_call_msg(name, args))
                            req.messages.append(mk_tool_resp_msg(name, tool_result))
                        req.depth += 1
                        return self._generate(req)

                content = message.content
                return content.strip() if content else None

            logger.warning(f"[{self.name}] No completion choices.")
            self._try_print_error(completion)
            return None

        except Exception as e:
            logger.error(f"[{self.name}] Error during API call: {e}", exc_info=True)
            if hasattr(e, "response") and e.response:
                logger.error(f"[{self.name}] API Error details: Status={e.response.status_code}, Body={e.response.text}")
            return None

    def _map_unified_params(self, unified: Dict[str, Any], model_to_use: str) -> Dict[str, Any]:
        """
        Canonical -> openai-compatible kwargs.
        Ничего лишнего: иначе многие прокси/SDK падают на unknown fields.
        """
        u = unified or {}
        m = (model_to_use or "").lower()
        out: Dict[str, Any] = {}

        for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
            if k in u:
                out[k] = u[k]

        # top_k — часто невалиден в OpenAI, но некоторые deepseek-openai прокси принимают
        if "top_k" in u and "deepseek" in m:
            out["top_k"] = u["top_k"]

        # logprobs: OpenAI SDK обычно ожидает bool
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
                        text = chunk.choices[0].delta.content or ""
                    # иногда встречаются альтернативные структуры
                    elif hasattr(chunk, "candidates") and chunk.candidates and chunk.candidates[0].content and \
                            chunk.candidates[0].content.parts:
                        text = chunk.candidates[0].content.parts[0].text or ""
                except Exception:
                    continue

                if text:
                    if stream_callback:
                        stream_callback(text)
                    parts.append(text)
        except Exception as e:
            logger.error(f"[{self.name}] stream error: {e}", exc_info=True)

        return "".join(parts)

    def _change_last_message_to_user_for_gemini(self, api_model: str, messages: List[Dict]) -> None:
        if messages and ("gemini" in (api_model or "").lower() or "gemma" in (api_model or "").lower()) and \
                messages[-1].get("role") in {"system", "model", "assistant"}:
            logger.info(f"[{self.name}] Adjusting last message for {api_model}: -> user with [SYSTEM INFO]")
            messages[-1]["role"] = "user"
            messages[-1]["content"] = f"[SYSTEM INFO] {messages[-1].get('content', '')}"

    def _try_print_error(self, completion_or_error):
        if not completion_or_error:
            return
        if hasattr(completion_or_error, "error") and completion_or_error.error:
            err = completion_or_error.error
            logger.warning(
                f"[{self.name}] API Error: code={getattr(err, 'code', 'N/A')}, "
                f"message={getattr(err, 'message', 'N/A')}, type={getattr(err, 'type', 'N/A')}"
            )
        elif isinstance(completion_or_error, dict) and "error" in completion_or_error:
            logger.warning(f"[{self.name}] API Error (dict): {completion_or_error['error']}")