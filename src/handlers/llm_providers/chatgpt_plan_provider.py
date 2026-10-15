from __future__ import annotations

import json
import httpx

from utils import _

from .base import (
    BaseProvider, LLMRequest, LLMResponse, RequestCancellation, get_request_cancellation, check_request_cancelled,
)
from .chatgpt_plan_auth import get_chatgpt_plan_auth
from .protocols.responses import ResponsesPolicy
from .protocols.registry import adapter_for
from .protocols.responses.stream import iter_responses_events
from .streaming import iter_sse_data
from .errors import LLMProviderError


class ChatGPTPlanProvider(BaseProvider):
    """Direct Responses API transport authorized by Sign in with ChatGPT."""

    name = "chatgpt_plan"
    priority = 15
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = True
    supports_stream_usage = True

    def is_applicable(self, req: LLMRequest) -> bool:
        return str(req.provider_name or "") == self.name

    def generate(self, req: LLMRequest) -> LLMResponse:
        url = str(req.api_url or 'https://api.openai.com/v1/responses')
        if url != 'https://api.openai.com/v1/responses':
            raise LLMProviderError(provider=self.name, friendly_message='Untrusted ChatGPT plan endpoint',
                                   code='chatgpt_plan.invalid_destination', retryable=False, phase='request')
        check_request_cancelled(req)
        req.capabilities['force_wire_stream'] = True
        if get_request_cancellation(req) is None:
            req.extra['_request_cancellation'] = RequestCancellation()
        adapter = adapter_for('openai_responses', responses_policy=ResponsesPolicy.siwc())
        payload = adapter.encode(req, wire_stream=True)
        auth = get_chatgpt_plan_auth()
        account_id = None
        try:
            credentials = getattr(auth, 'get_credentials', None)
            if callable(credentials):
                access_token, account_id = credentials()
            else:
                access_token = auth.get_access_token()
        except Exception as exc:
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            temporary = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)) or (
                status_code is not None and (status_code in {408, 429} or status_code >= 500))
            raise LLMProviderError(
                provider=self.name,
                friendly_message=_(
                    'Не удалось обновить сессию ChatGPT из-за временной сетевой ошибки. Повторите запрос позже.',
                    'Could not refresh the ChatGPT session due to a temporary network error. Try again later.',
                ) if temporary else _(
                    "Войдите через ChatGPT в настройках API перед использованием этого провайдера.",
                    "Sign in with ChatGPT in API settings before using this provider.",
                ),
                provider_message=str(exc),
                retryable=temporary,
                status_code=status_code,
                code='chatgpt_plan.auth_temporarily_unavailable' if temporary else 'chatgpt_plan.sign_in_required',
                phase="auth",
            ) from exc

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        headers.update({k: v for k, v in (req.headers or {}).items()
                        if k.lower() not in {'authorization', 'host', 'content-type', 'accept', 'cookie', 'proxy-authorization'}})

        response = self.http_transport.post_json(req, url, headers=headers, payload=payload, stream=True, follow_redirects=False)
        try:
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")
                code = self._error_code_from_body(body) or f"chatgpt_plan.http_{response.status_code}"
                retryable = response.status_code in {408, 500, 502, 503, 504}
                if response.status_code == 429:
                    retryable = code != "subscription_sharing_usage_limit_exceeded"
                if code in {
                    "subscription_sharing_user_not_eligible",
                    "subscription_sharing_unsupported_capability",
                    "subscription_sharing_route_not_supported",
                    "subscription_sharing_invalid_user",
                    "chatpass_v2_scope_not_authorized",
                    "chatpass_v2_invalid_authorization_context",
                }:
                    retryable = False
                if code in {
                    "subscription_sharing_usage_unavailable",
                    "subscription_sharing_user_unavailable",
                }:
                    retryable = True
                request_id = str(response.headers.get("x-request-id") or "").strip()
                provider_message = body[:2000]
                if request_id:
                    provider_message = f"request_id={request_id}; {provider_message}"
                raise LLMProviderError(
                    provider=self.name,
                    friendly_message=self._http_error_message(response.status_code, code),
                    status_code=int(response.status_code),
                    provider_message=provider_message,
                    raw_payload=body,
                    retryable=retryable,
                    code=code,
                    phase="http",
                    url=url,
                )

            result = adapter.consume_stream(req, iter_responses_events(iter_sse_data(response.iter_lines())))
            result.provider_name = self.name
            result.provider_display_name = req.provider_display_name or 'ChatGPT Plan (Codex)'
            record_state = getattr(auth, 'record_inference_error', None)
            if callable(record_state):
                record_state('', account_id=account_id)
            return result
        except LLMProviderError as exc:
            exc.provider = self.name
            exc.url = url
            if exc.phase == 'stream':
                code = exc.code or 'chatgpt_plan.stream_error'
                exc.friendly_message = self._http_error_message(0, code)
                exc.retryable = self._stream_retryable(code) if not code.startswith('responses.') else False
                cancellation = get_request_cancellation(req)
                if cancellation is not None and cancellation.response_body_started:
                    exc.retryable = False
                request_id = str(response.headers.get('x-request-id') or '').strip()
                if request_id:
                    exc.provider_message = f'request_id={request_id}; {exc.provider_message or code}'
            record_state = getattr(auth, 'record_inference_error', None)
            if callable(record_state):
                record_state(exc.code or '', account_id=account_id)
            raise
        finally:
            response.close()

    @staticmethod
    def _stream_retryable(code: str) -> bool:
        return code not in {
            'subscription_sharing_usage_limit_exceeded', 'subscription_sharing_unsupported_capability',
            'subscription_sharing_route_not_supported', 'subscription_sharing_user_not_eligible',
            'subscription_sharing_invalid_user', 'chatpass_v2_scope_not_authorized',
            'chatpass_v2_invalid_authorization_context',
        }

    @staticmethod
    def _error_code_from_body(body: str) -> str:
        try:
            payload = json.loads(str(body or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("code") or "")
        return ""

    @staticmethod
    def _http_error_message(status: int, code: str = "") -> str:
        if code == "subscription_sharing_usage_limit_exceeded" or status == 429:
            return _(
                "Достигнут лимит ChatGPT/Codex. Проверьте Usage в ChatGPT или используйте резервный провайдер.",
                "The ChatGPT/Codex usage limit was reached. Check Usage in ChatGPT or use a fallback provider.",
            )
        if code in {"subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable"}:
            return _(
                "Проверка доступной квоты ChatGPT/Codex временно недоступна.",
                "ChatGPT/Codex usage availability is temporarily unavailable.",
            )
        if code in {'subscription_sharing_unsupported_capability', 'subscription_sharing_route_not_supported'}:
            return _(
                'Запрос использует неподдерживаемую возможность ChatGPT-режима.',
                'This request uses a capability unsupported by the ChatGPT mode.',
            )
        if status in {401, 403}:
            return _(
                "Сессия ChatGPT недействительна или доступ к использованию плана не разрешён. Выполните вход заново.",
                "The ChatGPT session is invalid or plan usage is not authorized. Sign in again.",
            )
        return _("Ошибка Responses API ChatGPT.", "ChatGPT Responses API error.")


__all__ = ["ChatGPTPlanProvider"]
