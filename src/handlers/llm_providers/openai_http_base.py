# src/handlers/llm_providers/openai_http_base.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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

        return out

    def _build_payload(self, req: LLMRequest, model_to_use: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_to_use,
            "messages": messages,
        }
        payload.update(self._map_unified_params(req.extra or {}, model_to_use))

        if req.tools_on and req.tools_mode == "native" and req.tool_manager and self._supports_tools_for_req(req):
            dialect = req.tools_dialect or self.tools_dialect_id
            tools_payload = req.tools_payload or req.tool_manager.get_tools_payload(dialect)
            if tools_payload:
                payload["tools"] = tools_payload
                payload["stream"] = False

        return payload

    def _request(self, req: LLMRequest, payload: Dict[str, Any]) -> requests.Response:
        headers = self._headers(req)
        # Принудительно добавляем stream в payload, если он включен в запросе
        if req.stream:
            payload["stream"] = True
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

        if req.stream:
            return self._handle_stream(resp, req.stream_cb)

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[{self.name}] JSON parse error: {e}", exc_info=True)
            return None

        message = (data.get("choices", [{}])[0].get("message") or {}) if isinstance(data, dict) else {}
        tool_calls = message.get("tool_calls") or []

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
            # Используем decode_unicode=False, чтобы вручную декодировать чанки.
            # Это предотвращает разрыв многобайтовых UTF-8 символов на границах чанков.
            for line_bytes in resp.iter_lines(decode_unicode=False):
                if not line_bytes:
                    continue
                
                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    # Если не удалось декодировать строку целиком, пробуем игнорировать ошибки
                    # или обрабатывать как сырые данные.
                    line = line_bytes.decode("utf-8", errors="replace")

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