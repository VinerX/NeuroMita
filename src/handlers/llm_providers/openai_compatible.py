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
    StreamCallback,
    StreamChannel,
    check_request_cancelled,
    normalize_usage_payload,
    record_response_body_started,
    register_cancellable_resource,
)
from .errors import build_provider_error, build_stream_error, coerce_provider_error
from .message_transforms import trailing_system_to_user_prefix
from schemas.structured_response import StructuredResponse
from utils.openrouter_routing import (
    annotate_openrouter_prompt_cache,
    normalize_openrouter_routing,
)
from .streaming import StreamAccumulator


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

    def _release_client(self, client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()

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
            if req.stream and self.should_request_stream_usage(req):
                params["stream_options"] = {"include_usage": True}
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
                    if not caps.get("schema_intents", False):
                        segment_excl.add("intents")
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
                reasoning = self._extract_sdk_reasoning(message)
                if not reasoning:
                    try:
                        raw_dict = completion.model_dump()
                        msg_dict = (raw_dict.get("choices") or [{}])[0].get("message") or {}
                        reasoning = str(msg_dict.get("reasoning_content") or "")
                    except Exception:
                        reasoning = ""
                content, reasoning = self._resolve_content_and_reasoning(
                    str(message.content or ""), reasoning
                )
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
                    reasoning=reasoning.strip() or None,
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
            logger.debug(
                "[%s] Provider failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
            raise provider_error from e
        finally:
            try:
                self._release_client(client)
            except Exception:
                logger.debug(f"[{self.name}] Failed to release provider client", exc_info=True)

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
        accumulator = StreamAccumulator(req, provider=self.name, model=req.model)
        finish_reason = None
        response_model = None
        tool_calls: dict[int, dict[str, Any]] = {}
        try:
            for chunk in completion:
                record_response_body_started(req)
                check_request_cancelled(req)
                chunk_payload = self._stream_chunk_payload(chunk)
                if chunk_payload.get("error"):
                    raise build_stream_error(
                        self.name,
                        payload=chunk_payload,
                        url=req.api_url,
                    )
                response_model = response_model or getattr(chunk, "model", None)
                try:
                    chunk_usage = self._extract_usage(getattr(chunk, "usage", None))
                    if chunk_usage is not None:
                        accumulator.set_usage(chunk_usage)
                except Exception:
                    pass

                try:
                    choices = getattr(chunk, "choices", None) or []
                    if choices and getattr(choices[0], "finish_reason", None):
                        finish_reason = choices[0].finish_reason
                    if choices and getattr(choices[0], "delta", None):
                        delta = choices[0].delta
                        accumulator.add_text(delta.content or "")
                        reasoning = getattr(delta, "reasoning_content", None) or ""
                        if not reasoning:
                            reasoning = (getattr(delta, "model_extra", None) or {}).get("reasoning_content", "")
                        accumulator.add_reasoning(reasoning)
                        for tool_delta in getattr(delta, "tool_calls", None) or []:
                            index = int(getattr(tool_delta, "index", 0) or 0)
                            state = tool_calls.setdefault(index, {"id": "", "name": "", "started": False})
                            state["id"] = str(getattr(tool_delta, "id", None) or state["id"])
                            function = getattr(tool_delta, "function", None)
                            state["name"] = str(getattr(function, "name", None) or state["name"])
                            if not state["started"] and (state["id"] or state["name"]):
                                accumulator.tool_call_started(tool_call_id=state["id"], tool_name=state["name"])
                                state["started"] = True
                            arguments = str(getattr(function, "arguments", None) or "")
                            if arguments:
                                accumulator.tool_call_delta(
                                    tool_call_id=state["id"],
                                    tool_name=state["name"],
                                    arguments_delta=arguments,
                                )
                except Exception as e:
                    raise build_stream_error(
                        self.name,
                        payload=chunk_payload,
                        provider_message=f"Invalid provider stream chunk: {type(e).__name__}: {e}",
                        code="stream.invalid_payload",
                        url=req.api_url,
                    ) from e

        except Exception as e:
            provider_error = coerce_provider_error(self.name, e)
            logger.debug(
                "[%s] Stream failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
            raise provider_error from e
        finally:
            close = getattr(completion, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug(f"[{self.name}] Failed to close provider stream", exc_info=True)

        for state in tool_calls.values():
            if state["started"]:
                accumulator.tool_call_completed(tool_call_id=state["id"], tool_name=state["name"])
        response = accumulator.complete(finish_reason=finish_reason, model=response_model)
        if not response.text:
            if finish_reason and finish_reason != "stop":
                response.error_message = f"Provider stream ended without content (finish_reason={finish_reason})."
        return response

    @staticmethod
    def _stream_chunk_payload(chunk: Any) -> dict[str, Any]:
        if isinstance(chunk, dict):
            return dict(chunk)
        model_dump = getattr(chunk, "model_dump", None)
        if callable(model_dump):
            try:
                payload = model_dump()
                if isinstance(payload, dict):
                    model_extra = getattr(chunk, "model_extra", None)
                    if isinstance(model_extra, dict):
                        payload = {**model_extra, **payload}
                    return payload
            except Exception:
                pass
        model_extra = getattr(chunk, "model_extra", None)
        return dict(model_extra) if isinstance(model_extra, dict) else {}

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
