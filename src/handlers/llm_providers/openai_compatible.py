# src/handlers/llm_providers/openai_compatible.py
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from main_logger import logger
from .base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    check_request_cancelled,
    normalize_usage_payload,
    register_cancellable_resource,
)
from .errors import build_provider_error, coerce_provider_error
from .message_transforms import trailing_system_to_user_prefix
from schemas.structured_response import StructuredResponse
from utils.openrouter_routing import (
    annotate_openrouter_prompt_cache,
    normalize_openrouter_routing,
)


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

    @staticmethod
    def _stringify_error(value: Any, limit: int = 400) -> str:
        try:
            if isinstance(value, str):
                text = value
            else:
                text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)

        text = (text or "").strip()
        return text[:limit]

    def generate(self, req: LLMRequest) -> LLMResponse:
        return self._generate(req)

    def _generate(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error(f"Слишком много рекурсивных tool-вызовов ({self.name}).")
            return LLMResponse(
                text=None,
                provider_name=self.name,
                error_message="Too deep tool recursion.",
            )

        model_to_use = self._get_model_to_use(req)
        client = self._get_client(req)
        if not client:
            raise build_provider_error(
                self.name,
                provider_message="API client initialization returned no client.",
                url=req.api_url,
            )

        try:
            check_request_cancelled(req)
            cleaned_messages = [{k: v for k, v in m.items() if k != "time"} for m in (req.messages or [])]
            if req.protocol_id == "openrouter_default":
                if bool((req.extra or {}).get("openrouter_tail_system_to_user", True)):
                    cleaned_messages = trailing_system_to_user_prefix(cleaned_messages, tag="[SYSTEM INFO]")
                cleaned_messages = annotate_openrouter_prompt_cache(cleaned_messages, model_to_use)

            params: Dict[str, Any] = {"model": model_to_use, "messages": cleaned_messages}
            params.update(self._map_unified_params(req.extra or {}, model_to_use))
            if req.protocol_id == "openrouter_default":
                extra_body = dict(params.get("extra_body") or {})
                routing = normalize_openrouter_routing((req.extra or {}).get("openrouter_routing"))
                if routing:
                    extra_body["provider"] = routing
                session_id = str((req.extra or {}).get("openrouter_session_id") or "").strip()
                if session_id:
                    extra_body["session_id"] = session_id
                if extra_body:
                    params["extra_body"] = extra_body

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
                    segment_excl = set(caps.get("structured_segment_exclude_fields") or ())
                    params["response_format"] = model_cls.openai_response_format(
                        exclude_fields=excl or None,
                        exclude_segment_fields=segment_excl or None,
                    )
                logger.debug(f"[{self.name}] Structured output enabled: response_format={rf_mode}")

            check_request_cancelled(req)
            completion = client.chat.completions.create(**params, stream=req.stream)
            completion = register_cancellable_resource(req, completion)

            if req.stream:
                return self._handle_stream(completion, req, req.stream_cb)

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
                    error_message=None if content else (
                        "Provider returned completion without message content."
                        + (f" finish_reason={finish_reason}." if finish_reason else "")
                    ),
                )

            logger.warning(f"[{self.name}] No completion choices.")
            return LLMResponse(
                text=None,
                model=model_to_use,
                provider_name=self.name,
                error_message="Provider returned no completion choices.",
            )

        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=req.api_url)
            logger.error(f"[{self.name}] {provider_error.to_console_summary()}", exc_info=True)
            raise provider_error from e
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug(f"[{self.name}] Failed to close provider client", exc_info=True)

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

    def _handle_stream(self, completion, req: LLMRequest, stream_callback=None) -> LLMResponse:
        parts: List[str] = []
        final_usage = None
        finish_reason = None
        chunk_error_count = 0
        last_chunk_error = ""
        try:
            for chunk in completion:
                check_request_cancelled(req)
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
                except Exception as e:
                    chunk_error_count += 1
                    last_chunk_error = f"{type(e).__name__}: {e}"
                    if chunk_error_count <= 3:
                        preview = self._stringify_error(getattr(chunk, "model_dump", lambda: chunk)(), limit=240)
                        logger.warning(f"[{self.name}] Failed to parse stream chunk: {last_chunk_error}. Chunk: {preview}")
                    continue

                if text:
                    if stream_callback:
                        stream_callback(text)
                    parts.append(text)
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e)
            logger.error(f"[{self.name}] stream error: {provider_error.to_console_summary()}", exc_info=True)
            raise provider_error from e
        finally:
            close = getattr(completion, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug(f"[{self.name}] Failed to close provider stream", exc_info=True)

        error_message = None
        if not parts:
            if chunk_error_count > 0:
                error_message = (
                    "Provider stream ended without content. "
                    f"Chunk parse errors: {chunk_error_count}, last error: {last_chunk_error}"
                )
            elif finish_reason and finish_reason != "stop":
                error_message = f"Provider stream ended without content (finish_reason={finish_reason})."

        return LLMResponse(
            text="".join(parts) or None,
            usage=final_usage,
            provider_name=self.name,
            finish_reason=finish_reason,
            error_message=error_message,
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
