# src/handlers/llm_providers/openai_http_base.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from main_logger import logger
from handlers.llm_providers.base import BaseProvider, LLMRequest, LLMResponse, normalize_usage_payload
from schemas.structured_response import StructuredResponse
from utils.openrouter_routing import (
    annotate_openrouter_prompt_cache,
    normalize_openrouter_routing,
)


class OpenAIHTTPProviderBase(BaseProvider):
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False

    tools_dialect_id: str = "openai"

    def _supports_tools_for_req(self, req: LLMRequest) -> bool:
        caps = req.capabilities or {}
        if "tools_native" in caps:
            return bool(caps.get("tools_native"))
        return bool(self.supports_tools_native)

    def _headers(self, req: LLMRequest) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}

        extra = req.headers or {}
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k and v is not None:
                    headers[str(k)] = str(v)

        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"
        return headers

    def _preprocess_messages(self, req: LLMRequest) -> List[Dict[str, Any]]:
        allowed_keys = {
            "role",
            "content",
            "name",
            "tool_calls",
            "tool_call_id",
            "function_call",
        }

        cleaned: List[Dict[str, Any]] = []
        for m in (req.messages or []):
            if not isinstance(m, dict):
                continue
            cleaned.append({k: v for k, v in m.items() if k in allowed_keys})

        return cleaned

    def _normalize_messages(self, req: LLMRequest, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return messages

    def _map_unified_params(self, unified: Dict[str, Any], model_to_use: str) -> Dict[str, Any]:
        u = unified or {}
        m = (model_to_use or "").lower()
        out: Dict[str, Any] = {}

        for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
            if k in u:
                out[k] = u[k]

        if "top_k" in u and "deepseek" in m:
            out["top_k"] = u["top_k"]

        if "logprobs" in u:
            lp = u["logprobs"]
            out["logprobs"] = lp if isinstance(lp, bool) else bool(lp)

        # Reasoning/thinking is serialized separately in _apply_reasoning, driven by
        # the protocol's declared capabilities (not by the model name).
        return out

    @staticmethod
    def _apply_reasoning(payload: Dict[str, Any], req: LLMRequest) -> None:
        """Serialize the reasoning/thinking toggle into the request payload.

        The transport is declared by the protocol via capabilities["reasoning_control"]
        rather than guessed from the model name:
          - "openrouter": OpenRouter's unified `reasoning` map (safe to send to any
            OpenRouter model — unsupported models normalize it away).
          - "deepseek": the native DeepSeek `thinking` object, which defaults to
            "enabled" and must be explicitly disabled to skip reasoning.
          - otherwise (legacy/unknown): only ever ENABLE via an Anthropic-style
            `thinking` object; never emit a disabled flag, since some providers
            reject it (e.g. Mistral 422).

        enable_thinking is tri-state: absent -> leave the provider default untouched;
        True -> enable; False -> disable.
        """
        extra = req.extra or {}
        if "enable_thinking" not in extra:
            return

        enabled = bool(extra.get("enable_thinking"))
        try:
            budget = int(extra.get("thinking_budget") or extra.get("gemini_thinking_budget") or 0)
        except Exception:
            budget = 0

        transport = str((req.capabilities or {}).get("reasoning_control") or "")

        if transport == "openrouter":
            reasoning: Dict[str, Any] = {"enabled": enabled}
            if enabled and budget > 0:
                reasoning["max_tokens"] = budget
            payload["reasoning"] = reasoning
        elif transport == "deepseek":
            thinking: Dict[str, Any] = {"type": "enabled" if enabled else "disabled"}
            if enabled and budget > 0:
                thinking["budget_tokens"] = budget
            payload["thinking"] = thinking
        elif enabled:
            thinking = {"type": "enabled"}
            if budget > 0:
                thinking["budget_tokens"] = budget
            payload["thinking"] = thinking

    def _supports_structured_output(self, req: LLMRequest) -> bool:
        caps = req.capabilities or {}
        return bool(caps.get("structured_output", False))

    def _build_payload(self, req: LLMRequest, model_to_use: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if req.protocol_id == "openrouter_default":
            messages = annotate_openrouter_prompt_cache(messages, model_to_use)
        payload: Dict[str, Any] = {
            "model": model_to_use,
            "messages": messages,
        }
        payload.update(self._map_unified_params(req.extra or {}, model_to_use))
        self._apply_reasoning(payload, req)

        if req.protocol_id == "openrouter_default":
            routing = normalize_openrouter_routing((req.extra or {}).get("openrouter_routing"))
            if routing:
                payload["provider"] = routing
            session_id = str((req.extra or {}).get("openrouter_session_id") or "").strip()
            if session_id:
                payload["session_id"] = session_id

        if self._supports_structured_output(req):
            rf_mode = (req.capabilities or {}).get("structured_output_mode", "json_schema")
            if rf_mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
            else:
                model_cls = req.structured_model or StructuredResponse
                caps = req.capabilities or {}
                has_custom = bool(caps.get("has_custom_params")) or bool(caps.get("custom_params"))
                excl = set() if has_custom else {"custom_fields"}
                if not caps.get("schema_reasoning", True):
                    excl.add("reasoning")
                payload["response_format"] = model_cls.openai_response_format(exclude_fields=excl or None)
            logger.debug(f"[{self.name}] Structured output enabled: response_format={rf_mode}")

        return payload

    def _request(self, req: LLMRequest, payload: Dict[str, Any]) -> requests.Response:
        headers = self._headers(req)
        if req.stream:
            payload["stream"] = True
        return requests.post(req.api_url, headers=headers, json=payload, stream=req.stream)

    def generate(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error(f"[{self.name}] Too deep tool recursion.")
            return LLMResponse(text=None, provider_name=self.name)

        if not req.api_url:
            logger.error(f"[{self.name}] api_url is empty.")
            return LLMResponse(text=None, provider_name=self.name)

        model_to_use = req.model
        msgs = self._preprocess_messages(req)
        msgs = self._normalize_messages(req, msgs)

        payload = self._build_payload(req, model_to_use, msgs)

        resp = self._request(req, payload)

        if resp.status_code == 400 and self._supports_structured_output(req):
            rf_mode = (req.capabilities or {}).get("structured_output_mode", "json_schema")
            if rf_mode != "json_object" and "response_format" in payload:
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = {}
                err_msg = str(err_body)
                if "response_format" in err_msg or "json_schema" in err_msg or "json_object" in err_msg:
                    logger.warning(
                        f"[{self.name}] json_schema rejected by provider, retrying with json_object. "
                        f"Error: {err_msg[:200]}"
                    )
                    payload["response_format"] = {"type": "json_object"}
                    resp = self._request(req, payload)

        if resp.status_code != 200:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            logger.error(f"[{self.name}] HTTP {resp.status_code}: {err}")
            return LLMResponse(text=None, model=model_to_use, provider_name=self.name)

        if req.stream:
            return self._handle_stream(resp, req.api_url, req.stream_cb)

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[{self.name}] JSON parse error: {e}", exc_info=True)
            return LLMResponse(text=None, model=model_to_use, provider_name=self.name)

        message = (data.get("choices", [{}])[0].get("message") or {}) if isinstance(data, dict) else {}

        content = message.get("content") or message.get("reasoning_content") or ""
        return LLMResponse(
            text=content.strip() if content else None,
            usage=self._extract_usage(data, req.api_url),
            model=(data.get("model") if isinstance(data, dict) else None) or model_to_use,
            provider_name=self.name,
            finish_reason=((data.get("choices") or [{}])[0].get("finish_reason") if isinstance(data, dict) else None),
            raw=data if isinstance(data, dict) else {},
        )

    def _handle_stream(
        self,
        resp: requests.Response,
        api_url: str,
        stream_callback: Optional[callable] = None,
    ) -> LLMResponse:
        parts: List[str] = []
        usage = None
        finish_reason = None
        response_model = None
        try:
            for line_bytes in resp.iter_lines(decode_unicode=False):
                if not line_bytes:
                    continue
                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    line = line_bytes.decode("utf-8", errors="replace")

                if not line.startswith("data: "):
                    continue

                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break

                try:
                    obj = json.loads(chunk)
                    if response_model is None:
                        response_model = obj.get("model")
                    usage = usage or self._extract_usage(obj, api_url)
                    delta = obj.get("choices", [{}])[0].get("delta", {}) or {}
                    fr = obj.get("choices", [{}])[0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                    text = delta.get("content", "") or delta.get("reasoning_content", "") or ""
                    if text:
                        if stream_callback:
                            stream_callback(text)
                        parts.append(text)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[{self.name}] stream error: {e}", exc_info=True)

        return LLMResponse(
            text="".join(parts),
            usage=usage,
            model=response_model,
            provider_name=self.name,
            finish_reason=finish_reason,
        )

    def _extract_usage(self, data: Any, api_url: str):
        if not isinstance(data, dict):
            return None

        is_openrouter = "openrouter.ai" in str(api_url or "").lower()
        usage = normalize_usage_payload(
            data.get("usage"),
            cost_currency="credits" if is_openrouter else None,
            cost_source="provider_usage" if isinstance(data.get("usage"), dict) and data.get("usage", {}).get("cost") is not None else None,
        )
        if usage is not None:
            return usage

        if "usage" not in data:
            return None

        # Some providers expose usage but without cost; keep token stats if present.
        return normalize_usage_payload(data.get("usage"))
