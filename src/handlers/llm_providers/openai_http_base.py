# src/handlers/llm_providers/openai_http_base.py
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from main_logger import logger
from handlers.llm_providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    check_request_cancelled,
    normalize_usage_payload,
    register_cancellable_resource,
    resolve_requests_timeout,
)
from handlers.llm_providers.errors import build_provider_error, coerce_provider_error
from handlers.llm_providers.message_transforms import trailing_system_to_user_prefix
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
          - otherwise (legacy/unknown): emit nothing. Generic OpenAI-compatible
            providers (e.g. Mistral) reject unknown `thinking` members with 4xx,
            so thinking is strictly opt-in via a declared reasoning_control.

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

    def _supports_structured_output(self, req: LLMRequest) -> bool:
        caps = req.capabilities or {}
        return bool(caps.get("structured_output", False))

    def _resolve_request_url(self, req: LLMRequest) -> str:
        url = str(req.api_url or "").strip()
        if not url:
            return ""

        if str(req.dialect_id or "").strip() != "openai_chat_completions":
            return url

        parsed = urlsplit(url)
        path = (parsed.path or "").rstrip("/")
        lowered = path.lower()

        # Already a completions endpoint — leave it untouched.
        if lowered.endswith("/chat/completions") or lowered.endswith("/completions"):
            return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

        # Only auto-complete obvious "base" URLs: empty/root path or a versioned
        # prefix like ".../v1". Custom gateway paths (e.g. ".../llm/generate") are
        # left as the user entered them to avoid producing ".../generate/chat/completions".
        if path == "" or re.search(r"/v\d+$", lowered):
            normalized_path = f"{path}/chat/completions" if path else "/chat/completions"
            return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))

        return url

    def _build_payload(self, req: LLMRequest, model_to_use: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        if req.protocol_id == "openrouter_default":
            if bool((req.extra or {}).get("openrouter_tail_system_to_user", True)):
                messages = trailing_system_to_user_prefix(messages, tag="[SYSTEM INFO]")
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
                segment_excl = set(caps.get("structured_segment_exclude_fields") or ())
                payload["response_format"] = model_cls.openai_response_format(
                    exclude_fields=excl or None,
                    exclude_segment_fields=segment_excl or None,
                )
            logger.debug(f"[{self.name}] Structured output enabled: response_format={rf_mode}")

        return payload

    def _request(self, request_url: str, req: LLMRequest, payload: Dict[str, Any]) -> requests.Response:
        check_request_cancelled(req)
        headers = self._headers(req)
        if req.stream:
            payload["stream"] = True
        timeout = resolve_requests_timeout(req)
        response = requests.post(
            request_url,
            headers=headers,
            json=payload,
            stream=req.stream,
            timeout=timeout,
        )
        register_cancellable_resource(req, response)
        check_request_cancelled(req)
        return response

    def generate(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error(f"[{self.name}] Too deep tool recursion.")
            return LLMResponse(
                text=None,
                provider_name=self.name,
                error_message="Too deep tool recursion.",
            )

        if not req.api_url:
            logger.error(f"[{self.name}] api_url is empty.")
            raise build_provider_error(self.name, provider_message="api_url is empty.", url=req.api_url)

        model_to_use = req.model
        msgs = self._preprocess_messages(req)
        msgs = self._normalize_messages(req, msgs)
        request_url = self._resolve_request_url(req)

        payload = self._build_payload(req, model_to_use, msgs)

        try:
            resp = self._request(request_url, req, payload)
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=request_url)
            logger.error(f"[{self.name}] {provider_error.to_console_summary()}", exc_info=True)
            raise provider_error from e

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
                    resp.close()
                    resp = self._request(request_url, req, payload)

        if resp.status_code != 200:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            provider_error = build_provider_error(
                self.name,
                status_code=resp.status_code,
                payload=err,
                response_headers=resp.headers,
                url=request_url,
            )
            logger.error(f"[{self.name}] {provider_error.to_console_summary()}")
            logger.debug(f"[{self.name}] raw error payload: {self._stringify_error(err, limit=800)}")
            resp.close()
            raise provider_error

        if req.stream:
            return self._handle_stream(resp, request_url, req, req.stream_cb)

        try:
            data = resp.json()
        except Exception as e:
            provider_error = build_provider_error(
                self.name,
                provider_message=f"JSON parse error: {e}",
                payload=getattr(resp, "text", None),
                url=request_url,
            )
            logger.error(f"[{self.name}] {provider_error.to_console_summary()}", exc_info=True)
            resp.close()
            raise provider_error from e
        resp.close()

        if isinstance(data, dict) and data.get("error"):
            status_code = None
            err_payload = data.get("error")
            if isinstance(err_payload, dict):
                raw_code = err_payload.get("code")
                try:
                    status_code = int(raw_code)
                except Exception:
                    status_code = None
            provider_error = build_provider_error(
                self.name,
                status_code=status_code,
                payload=data,
                response_headers=resp.headers,
                url=request_url,
            )
            logger.error(f"[{self.name}] {provider_error.to_console_summary()}")
            logger.debug(f"[{self.name}] raw error payload: {self._stringify_error(data, limit=800)}")
            raise provider_error

        message = (data.get("choices", [{}])[0].get("message") or {}) if isinstance(data, dict) else {}
        finish_reason = ((data.get("choices") or [{}])[0].get("finish_reason") if isinstance(data, dict) else None)

        content = message.get("content") or message.get("reasoning_content") or ""
        if not content:
            response_preview = self._stringify_error(data, limit=600)
            finish_suffix = f" finish_reason={finish_reason}." if finish_reason else ""
            error_message = f"Provider returned 200 OK but empty message content.{finish_suffix}"
            logger.error(f"[{self.name}] {error_message} Raw response: {response_preview}")
            return LLMResponse(
                text=None,
                usage=self._extract_usage(data, request_url),
                model=(data.get("model") if isinstance(data, dict) else None) or model_to_use,
                provider_name=self.name,
                finish_reason=finish_reason,
                error_message=error_message,
                raw=data if isinstance(data, dict) else {},
            )

        return LLMResponse(
            text=content.strip() if content else None,
            usage=self._extract_usage(data, request_url),
            model=(data.get("model") if isinstance(data, dict) else None) or model_to_use,
            provider_name=self.name,
            finish_reason=finish_reason,
            raw=data if isinstance(data, dict) else {},
        )

    def _handle_stream(
        self,
        resp: requests.Response,
        api_url: str,
        req: LLMRequest,
        stream_callback: Optional[callable] = None,
    ) -> LLMResponse:
        parts: List[str] = []
        usage = None
        finish_reason = None
        response_model = None
        chunk_error_count = 0
        last_chunk_error = ""
        try:
            for line_bytes in resp.iter_lines(decode_unicode=False):
                check_request_cancelled(req)
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
                except Exception as e:
                    chunk_error_count += 1
                    last_chunk_error = f"{type(e).__name__}: {e}"
                    if chunk_error_count <= 3:
                        preview = chunk[:240].replace("\n", "\\n")
                        logger.warning(f"[{self.name}] Failed to parse stream chunk: {last_chunk_error}. Chunk: {preview}")
                    continue
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=api_url)
            logger.error(f"[{self.name}] stream error: {provider_error.to_console_summary()}", exc_info=True)
            raise provider_error from e
        finally:
            try:
                resp.close()
            except Exception:
                logger.debug(f"[{self.name}] Failed to close HTTP stream", exc_info=True)

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
            usage=usage,
            model=response_model,
            provider_name=self.name,
            finish_reason=finish_reason,
            error_message=error_message,
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
