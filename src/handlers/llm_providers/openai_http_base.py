# src/handlers/llm_providers/openai_http_base.py
from __future__ import annotations
from core.error_utils import format_exception

import json
import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from main_logger import logger
from handlers.llm_providers.base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    StreamCallback,
    check_request_cancelled,
)
from handlers.llm_providers.errors import build_provider_error, build_stream_error, coerce_provider_error
from handlers.llm_providers.streaming import iter_sse_data, track_response_body
from handlers.llm_providers.protocols.registry import adapter_for
from handlers.llm_providers.protocols.chat_completions.request import fallback_payload

class OpenAIHTTPProviderBase(BaseProvider):
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False

    tools_dialect_id: str = "openai"

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

    def _supports_structured_output(self, req: LLMRequest) -> bool:
        caps = req.capabilities or {}
        return bool(caps.get("structured_output", False) and caps.get("native_structured_output", True))

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

    def _request(self, request_url: str, req: LLMRequest, payload: Dict[str, Any]) -> httpx.Response:
        headers = self._headers(req)
        return self.http_transport.post_json(
            req,
            request_url,
            headers=headers,
            payload=payload,
            stream=bool(payload["stream"]),
        )

    def generate(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error(f"[{self.name}] Too deep tool recursion.")
            return LLMResponse(
                text=None,
                provider_name=req.provider_name or self.name,
                provider_display_name=req.provider_display_name or req.provider_name or self.name,
                error_message="Too deep tool recursion.",
            )

        if not req.api_url:
            logger.error(f"[{self.name}] api_url is empty.")
            raise build_provider_error(self.name, provider_message="api_url is empty.", url=req.api_url)

        request_url = self._resolve_request_url(req)
        adapter = adapter_for("openai_chat_completions", provider_name=self.name,
                              supports_stream_usage=self.should_request_stream_usage(req))
        payload = adapter.encode(req, wire_stream=req.wire_stream)

        try:
            resp = self._request(request_url, req, payload)
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=request_url)
            logger.debug(
                "[%s] Transport failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
            raise provider_error from e

        if (
            resp.status_code == 400
            and self._supports_structured_output(req)
            and (req.capabilities or {}).get("structured_output_fallback", True)
        ):
            if req.wire_stream:
                resp.read()
            initial_mode = (req.capabilities or {}).get("structured_output_mode", "json_schema")
            fallback_count = 1 if initial_mode == "json_object" else 0
            while resp.status_code == 400 and fallback_count < 2:
                if req.wire_stream:
                    resp.read()
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = {}
                err_msg = str(err_body)
                next_payload = fallback_payload(payload, err_msg)
                if next_payload is None:
                    break
                logger.warning(
                    f"[{self.name}] response format rejected; retrying with a narrower format. "
                    f"Error: {err_msg[:200]}"
                )
                payload = next_payload
                resp.close()
                resp = self._request(request_url, req, payload)
                fallback_count += 1

        if resp.status_code != 200:
            if req.wire_stream:
                resp.read()
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
            logger.debug(
                "[%s] HTTP failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
            logger.debug(f"[{self.name}] raw error payload: {self._stringify_error(err, limit=800)}")
            resp.close()
            raise provider_error

        if req.wire_stream:
            return self._handle_stream(resp, request_url, req, req.stream_cb)

        try:
            data = resp.json()
        except Exception as e:
            provider_error = build_provider_error(
                self.name,
                provider_message=f"JSON parse error: {format_exception(e)}",
                payload=getattr(resp, "text", None),
                url=request_url,
            )
            logger.debug(
                "[%s] Parse failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
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
            logger.debug(
                "[%s] Payload failure delegated to request runner: %s",
                self.name,
                provider_error.to_console_summary(),
            )
            logger.debug(f"[{self.name}] raw error payload: {self._stringify_error(data, limit=800)}")
            raise provider_error

        return adapter.decode(req, data)

    def _handle_stream(
        self,
        resp: httpx.Response,
        api_url: str,
        req: LLMRequest,
        stream_callback: Optional[StreamCallback] = None,
    ) -> LLMResponse:
        def chunks():
            for chunk in iter_sse_data(track_response_body(req, resp.iter_lines())):
                check_request_cancelled(req)
                if chunk.strip() == "[DONE]":
                    return
                try:
                    yield json.loads(chunk)
                except json.JSONDecodeError as e:
                    raise build_stream_error(
                        self.name, payload=chunk[:500],
                        provider_message=f"Invalid JSON in provider stream: {format_exception(e)}",
                        code="stream.invalid_json", url=api_url,
                    ) from e
        try:
            return adapter_for("openai_chat_completions", provider_name=self.name).consume_stream(req, chunks())
        except Exception as e:
            raise coerce_provider_error(self.name, e, url=api_url) from e
        finally:
            try:
                resp.close()
            except Exception:
                logger.debug(f"[{self.name}] Failed to close HTTP stream", exc_info=True)
