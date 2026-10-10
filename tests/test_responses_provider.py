import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.errors import LLMProviderError
from handlers.llm_providers.responses_provider import ResponsesProvider


@pytest.mark.parametrize('stream', [False, True])
def test_api_key_transport_and_wire_modes(stream):
    calls = []
    payload = {'status': 'completed', 'model': 'm', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ok'}]}]}
    def post(req, url, **kwargs):
        calls.append((url, kwargs))
        if stream:
            return httpx.Response(200, content='data: ' + json.dumps({'type': 'response.completed', 'response': payload}) + '\n\n')
        return httpx.Response(200, json=payload)
    provider = ResponsesProvider(http_transport=SimpleNamespace(post_json=post))
    req = LLMRequest(model='m', messages=[], api_key='secret', api_url='https://custom.test/v1/responses',
                     provider_name='common', dialect_id='openai_responses', stream=stream)
    assert provider.is_applicable(req)
    assert provider.generate(req).text == 'ok'
    url, kwargs = calls[0]
    assert url == req.api_url and kwargs['headers']['Authorization'] == 'Bearer secret'
    assert kwargs['stream'] is stream and kwargs['payload']['stream'] is stream


def test_routing_is_explicit():
    provider = ResponsesProvider(http_transport=SimpleNamespace())
    for name in ('common', 'openai', 'responses'):
        assert provider.is_applicable(LLMRequest(model='m', messages=[], provider_name=name, dialect_id='openai_responses'))
    assert not provider.is_applicable(LLMRequest(model='m', messages=[], provider_name='chatgpt_plan', dialect_id='openai_responses'))
    assert not provider.is_applicable(LLMRequest(model='m', messages=[], provider_name='common', dialect_id='openai_chat_completions'))


def test_http_error_and_close():
    response = httpx.Response(429, json={'error': {'code': 'rate_limit', 'message': 'wait'}})
    provider = ResponsesProvider(http_transport=SimpleNamespace(post_json=lambda *a, **kw: response))
    with pytest.raises(LLMProviderError) as caught:
        provider.generate(LLMRequest(model='m', messages=[]))
    assert caught.value.code == 'rate_limit' and caught.value.retryable
    assert response.is_closed


@pytest.mark.parametrize('url, expected', [
    ('https://custom.test/v1', 'https://custom.test/v1/responses'),
    ('https://custom.test/v1/', 'https://custom.test/v1/responses'),
    ('https://custom.test', 'https://custom.test/v1/responses'),
    ('https://custom.test/custom?route=1', 'https://custom.test/custom?route=1'),
])
def test_base_url_normalization(url, expected):
    calls = []
    def post(req, destination, **kwargs):
        calls.append(destination)
        return httpx.Response(200, json={'status': 'completed', 'output': []})
    ResponsesProvider(http_transport=SimpleNamespace(post_json=post)).generate(
        LLMRequest(model='m', messages=[], api_url=url))
    assert calls == [expected]


def test_forced_generic_wire_stream_does_not_emit_ui_deltas():
    events, calls = [], []
    body = 'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
    body += 'data: {"type":"response.completed","response":{}}\n\n'
    def post(req, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, content=body)
    req = LLMRequest(model='m', messages=[], stream_event_cb=events.append, capabilities={'force_wire_stream': True})
    assert ResponsesProvider(http_transport=SimpleNamespace(post_json=post)).generate(req).text == 'ok'
    assert calls[0]['stream'] and calls[0]['payload']['stream']
    assert calls[0]['headers']['Accept'] == 'text/event-stream' and events == []


def test_invalid_decode_is_normalized_nonretryable_error():
    output = {'type': 'function_call', 'name': 'lookup', 'call_id': 'c1', 'arguments': '[]'}
    response = httpx.Response(200, json={'output': [output]})
    req = LLMRequest(model='m', messages=[], tools_on=True, tools_payload=[{'name': 'lookup'}])
    with pytest.raises(LLMProviderError) as caught:
        ResponsesProvider(http_transport=SimpleNamespace(post_json=lambda *a, **kw: response)).generate(req)
    assert not caught.value.retryable and caught.value.phase == 'response'
    assert response.is_closed


@pytest.mark.parametrize('partial', [False, True])
def test_siwc_subscription_policy_and_partial_progress(monkeypatch, partial):
    from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth',
                        lambda: SimpleNamespace(get_access_token=lambda: 'oauth'))
    body = 'data: {"type":"response.output_text.delta","delta":"partial"}\n\n' if partial else ''
    body += 'data: {"type":"error","code":"subscription_sharing_usage_unavailable","message":"wait"}\n\n'
    req = LLMRequest(model='m', messages=[])
    with pytest.raises(LLMProviderError) as caught:
        ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=lambda *a, **kw: httpx.Response(200, content=body))).generate(req)
    assert caught.value.retryable is (not partial)
    assert req.wire_stream and req.stream is False
