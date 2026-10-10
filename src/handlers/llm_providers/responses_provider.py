from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .base import BaseProvider, LLMRequest, LLMResponse, check_request_cancelled, record_response_body_started
from .errors import build_provider_error, coerce_provider_error
from .protocols.registry import adapter_for
from .protocols.responses.stream import iter_responses_events
from .streaming import iter_sse_data


class ResponsesProvider(BaseProvider):
    name = 'responses'
    priority = 16
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = True
    supports_stream_usage = True

    def is_applicable(self, req: LLMRequest) -> bool:
        return req.dialect_id == 'openai_responses' and req.provider_name in {'common', 'openai', self.name}

    def generate(self, req: LLMRequest) -> LLMResponse:
        url = self._resolve_request_url(req)
        adapter = adapter_for('openai_responses')
        headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream' if req.wire_stream else 'application/json'}
        headers.update({str(k): str(v) for k, v in (req.headers or {}).items()
                        if k and v is not None and str(k).lower() not in {'authorization', 'content-type', 'accept'}})
        if req.api_key:
            headers['Authorization'] = f'Bearer {req.api_key}'
        response = None
        phase = 'request'
        try:
            check_request_cancelled(req)
            payload = adapter.encode(req, wire_stream=req.wire_stream)
            phase = 'http'
            response = self.http_transport.post_json(req, url, headers=headers, payload=payload,
                                                     stream=req.wire_stream, follow_redirects=False)
            check_request_cancelled(req)
            if response.status_code != 200:
                body = response.read().decode('utf-8', errors='replace')
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = body
                error = error_payload.get('error') if isinstance(error_payload, dict) else None
                raise build_provider_error(self.name, status_code=response.status_code, payload=error_payload,
                                           response_headers=response.headers, phase='http', url=url,
                                           code=str(error.get('code') or '') if isinstance(error, dict) else None)
            phase = 'stream' if req.wire_stream else 'response'
            if req.wire_stream:
                return adapter.consume_stream(req, iter_responses_events(iter_sse_data(response.iter_lines())))
            record_response_body_started(req)
            result = adapter.decode(req, response.json())
            check_request_cancelled(req)
            return result
        except Exception as exc:
            from .base import RequestCancelledError
            if isinstance(exc, RequestCancelledError):
                raise
            if isinstance(exc, ValueError):
                raise build_provider_error(self.name, provider_message=str(exc),
                                           code='responses.invalid_payload', phase=phase, url=url) from exc
            error = coerce_provider_error(self.name, exc, url=url)
            if error is exc:
                raise
            raise error from exc
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _resolve_request_url(req: LLMRequest) -> str:
        url = str(req.api_url or 'https://api.openai.com/v1/responses').strip()
        parsed = urlsplit(url)
        path = parsed.path.rstrip('/')
        if not path:
            path = '/v1/responses'
        elif path == '/v1':
            path += '/responses'
        else:
            return url
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


__all__ = ['ResponsesProvider']
