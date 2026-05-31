# src/handlers/llm_providers/openai_compatible.py
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from main_logger import logger
from .base import BaseProvider, LLMRequest, LLMResponse, normalize_usage_payload
from schemas.structured_response import StructuredResponse


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

    def generate(self, req: LLMRequest) -> LLMResponse:
        return self._generate(req)

    def _generate(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error(f"Слишком много рекурсивных tool-вызовов ({self.name}).")
            return LLMResponse(text=None, provider_name=self.name)

        model_to_use = self._get_model_to_use(req)
        client = self._get_client(req)
        if not client:
            return LLMResponse(text=None, model=model_to_use, provider_name=self.name)

        try:
            cleaned_messages = [{k: v for k, v in m.items() if k != "time"} for m in (req.messages or [])]

            params: Dict[str, Any] = {"model": model_to_use, "messages": cleaned_messages}
            params.update(self._map_unified_params(req.extra or {}, model_to_use))

            caps = req.capabilities or {}
            if caps.get("structured_output"):
                rf_mode = caps.get("structured_output_mode", "json_schema")
                if rf_mode == "json_object":
                    params["response_format"] = {"type": "json_object"}
                else:
                    model_cls = req.structured_model or StructuredResponse
                    has_custom = bool(caps.get("has_custom_params")) or bool(caps.get("custom_params"))
                    excl = set() if has_custom else {"custom_fields"}
                    if not caps.get("schema_reasoning", True):
                        excl.add("reasoning")
                    params["response_format"] = model_cls.openai_response_format(exclude_fields=excl or None)
                logger.debug(f"[{self.name}] Structured output enabled: response_format={rf_mode}")

            completion = client.chat.completions.create(**params, stream=req.stream)

            if req.stream:
                return self._handle_stream(completion, req.stream_cb)

            if completion and getattr(completion, "choices", None):
                message = completion.choices[0].message
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
                usage = self._extract_usage(getattr(completion, "usage", None))
                finish_reason = None
                try:
                    finish_reason = completion.choices[0].finish_reason
                except Exception:
                    pass
                return LLMResponse(
                    text=content.strip() if content else None,
                    usage=usage,
                    model=getattr(completion, "model", None) or model_to_use,
                    provider_name=self.name,
                    finish_reason=finish_reason,
                )

            logger.warning(f"[{self.name}] No completion choices.")
            return LLMResponse(text=None, model=model_to_use, provider_name=self.name)

        except Exception as e:
            logger.error(f"[{self.name}] Error during API call: {e}", exc_info=True)
            return LLMResponse(text=None, model=model_to_use, provider_name=self.name)

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

    def _handle_stream(self, completion, stream_callback=None) -> LLMResponse:
        parts: List[str] = []
        final_usage = None
        finish_reason = None
        try:
            for chunk in completion:
                try:
                    final_usage = final_usage or self._extract_usage(getattr(chunk, "usage", None))
                except Exception:
                    pass

                try:
                    if chunk.choices and getattr(chunk.choices[0], "finish_reason", None):
                        finish_reason = chunk.choices[0].finish_reason
                except Exception:
                    pass

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

        return LLMResponse(
            text="".join(parts),
            usage=final_usage,
            provider_name=self.name,
            finish_reason=finish_reason,
        )

    def _extract_usage(self, usage_obj: Any):
        if usage_obj is None:
            return None
        try:
            if hasattr(usage_obj, "model_dump"):
                payload = usage_obj.model_dump()
            elif isinstance(usage_obj, dict):
                payload = usage_obj
            else:
                payload = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                    "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                    "total_tokens": getattr(usage_obj, "total_tokens", None),
                    "prompt_tokens_details": getattr(usage_obj, "prompt_tokens_details", None),
                    "completion_tokens_details": getattr(usage_obj, "completion_tokens_details", None),
                    "cost": getattr(usage_obj, "cost", None),
                }
            return normalize_usage_payload(payload)
        except Exception:
            return None
