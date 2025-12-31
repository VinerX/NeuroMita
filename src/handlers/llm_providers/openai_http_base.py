# src/handlers/llm_providers/openai_http_base.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import requests

from main_logger import logger
from handlers.llm_providers.base import BaseProvider, LLMRequest


class OpenAIHTTPProviderBase(BaseProvider):
    """
    OpenAI-compatible HTTP provider base:
    - payload: {"model": ..., "messages": ...} + canonical params
    - tools (native) via ToolManager dialect (if supported)
    - tool_calls recursion
    - SSE streaming ("data: ...")
    """

    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False

    # tools dialect for ToolManager (usually "openai")
    tools_dialect_id: str = "openai"

    # providers can override this
    def _supports_tools_for_req(self, req: LLMRequest) -> bool:
        return bool(self.supports_tools_native)

    def _headers(self, req: LLMRequest) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"
        return headers

    def _preprocess_messages(self, req: LLMRequest) -> List[Dict[str, Any]]:
        """
        Sanitize messages for OpenAI-compatible HTTP endpoints.
        Keep only fields that are typically accepted by chat/completions APIs.
        This prevents 4xx errors on strict providers (e.g., Mistral) when
        history/UI metadata is present in stored messages.
        """
        allowed_keys = {
            "role",
            "content",
            "name",
            # tools recursion support
            "tool_calls",
            "tool_call_id",
            # legacy function calling
            "function_call",
        }

        cleaned: List[Dict[str, Any]] = []
        for m in (req.messages or []):
            if not isinstance(m, dict):
                continue
            cleaned.append({k: v for k, v in m.items() if k in allowed_keys})

        return cleaned

    def _normalize_messages(self, req: LLMRequest, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # default: no changes
        return messages

    def _map_unified_params(self, unified: Dict[str, Any], model_to_use: str) -> Dict[str, Any]:
        """
        Canonical -> openai-compatible kwargs.
        Keep it conservative: don't send unknown fields.
        """
        u = unified or {}
        m = (model_to_use or "").lower()
        out: Dict[str, Any] = {}

        for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
            if k in u:
                out[k] = u[k]

        # top_k: only for deepseek-openai proxies
        if "top_k" in u and "deepseek" in m:
            out["top_k"] = u["top_k"]

        # logprobs: most openai-compatible endpoints expect bool
        if "logprobs" in u:
            lp = u["logprobs"]
            out["logprobs"] = lp if isinstance(lp, bool) else bool(lp)

        # thinking_budget is not sent
        return out

    def _build_payload(self, req: LLMRequest, model_to_use: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_to_use,
            "messages": messages,
        }
        payload.update(self._map_unified_params(req.extra or {}, model_to_use))

        # tools: provider decides; tools payload comes from ToolManager dialect
        if req.tools_on and req.tools_mode == "native" and req.tool_manager and self._supports_tools_for_req(req):
            dialect = req.tools_dialect or self.tools_dialect_id
            tools_payload = req.tools_payload or req.tool_manager.get_tools_payload(dialect)
            if tools_payload:
                payload["tools"] = tools_payload
                # streaming with tools often breaks
                payload["stream"] = False

        return payload

    def _request(self, req: LLMRequest, payload: Dict[str, Any]) -> requests.Response:
        headers = self._headers(req)
        return requests.post(req.api_url, headers=headers, json=payload, stream=req.stream)

    def generate(self, req: LLMRequest) -> Optional[str]:
        if req.depth > 3:
            logger.error(f"[{self.name}] Too deep tool recursion.")
            return None

        if not req.api_url:
            logger.error(f"[{self.name}] api_url is empty.")
            return None

        model_to_use = req.model
        msgs = self._preprocess_messages(req)
        msgs = self._normalize_messages(req, msgs)

        payload = self._build_payload(req, model_to_use, msgs)

        resp = self._request(req, payload)

        if resp.status_code != 200:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            logger.error(f"[{self.name}] HTTP {resp.status_code}: {err}")
            return None

        # streaming
        if req.stream:
            return self._handle_stream(resp, req.stream_cb)

        # non-stream parsing
        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[{self.name}] JSON parse error: {e}", exc_info=True)
            return None

        message = (data.get("choices", [{}])[0].get("message") or {}) if isinstance(data, dict) else {}
        tool_calls = message.get("tool_calls") or []

        # tool recursion
        if tool_calls and req.tool_manager and self._supports_tools_for_req(req):
            tm = req.tool_manager
            dialect = req.tools_dialect or self.tools_dialect_id

            for call in tool_calls:
                call_id = call.get("id")
                name = call["function"]["name"]
                args = json.loads(call["function"]["arguments"])

                tool_result = tm.run(name, args)

                req.messages.append(tm.mk_tool_call_msg(dialect, name, args, tool_call_id=call_id))
                req.messages.append(tm.mk_tool_resp_msg(dialect, name, tool_result, tool_call_id=call_id))

            req.depth += 1
            return self.generate(req)

        return (message.get("content") or "").strip()

    def _handle_stream(self, resp: requests.Response, stream_callback: Optional[callable] = None) -> str:
        parts: List[str] = []
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue

                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break

                try:
                    obj = json.loads(chunk)
                    delta = obj.get("choices", [{}])[0].get("delta", {}) or {}
                    text = delta.get("content", "") or ""
                    if text:
                        if stream_callback:
                            stream_callback(text)
                        parts.append(text)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[{self.name}] stream error: {e}", exc_info=True)

        return "".join(parts)