import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.chatgpt_plan_auth import ChatGPTPlanAuth
from handlers.llm_providers.chatgpt_plan_protocol import build_responses_payload
from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider


def test_protocol_preserves_instruction_order_and_images():
    result = build_responses_payload('model', [
        {'role': 'system', 'content': 'first'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'look'},
                                   {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc'}}]},
        {'role': 'developer', 'content': 'later'},
    ])
    assert [item['role'] for item in result['input']] == ['developer', 'user', 'developer']
    assert result['input'][1]['content'][1]['image_url'] == 'data:image/png;base64,abc'


def test_protocol_preserves_tool_calls_and_results():
    result = build_responses_payload('model', [
        {'role': 'assistant', 'tool_calls': [{'id': 'call_1', 'function': {'name': 'lookup', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'found'},
    ])
    assert result['input'] == [
        {'type': 'function_call', 'call_id': 'call_1', 'name': 'lookup', 'arguments': '{}'},
        {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'found'},
    ]


def test_protocol_rejects_unsupported_media_instead_of_dropping_it():
    with pytest.raises(ValueError, match='Unsupported'):
        build_responses_payload('model', [{'role': 'user', 'content': [{'type': 'input_audio', 'data': 'abc'}]}])


class FakeAuth:
    def get_access_token(self):
        return 'test-token'


@pytest.mark.parametrize('nested', [False, True])
def test_stream_error_preserves_quota_reason_and_disables_retry(monkeypatch, nested):
    from handlers.llm_providers.errors import LLMProviderError
    error = {'code': 'subscription_sharing_usage_limit_exceeded', 'message': 'Subscription usage limit reached'}
    event = {'type': 'error', 'error': error} if nested else {'type': 'error', **error}
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    transport = SimpleNamespace(post_json=lambda *args, **kwargs: httpx.Response(
        200, headers={'x-request-id': 'test-request'}, content='data: ' + json.dumps(event) + '\n\n'))
    with pytest.raises(LLMProviderError) as caught:
        ChatGPTPlanProvider(http_transport=transport).generate(LLMRequest(model='m', messages=[]))
    assert caught.value.code == error['code']
    assert error['message'] in caught.value.provider_message
    assert 'test-request' in caught.value.provider_message
    assert caught.value.raw_payload == event
    assert not caught.value.retryable


@pytest.mark.parametrize('url', [
    'https://evil.example/v1/responses', 'http://api.openai.com/v1/responses',
    'https://api.openai.com/v1/responses?forward=1',
    'https://api.openai.com@evil.example/v1/responses',
    'https://api.openai.com/v1/chat/completions',
])
def test_provider_rejects_untrusted_destination_before_auth(monkeypatch, url):
    def forbidden():
        pytest.fail('credentials must not be loaded for an untrusted destination')
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', forbidden)
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace())
    with pytest.raises(Exception, match='endpoint|destination'):
        provider.generate(LLMRequest(model='model', messages=[], api_url=url))


def test_provider_uses_protected_headers_and_disables_redirects(monkeypatch):
    calls = []
    def post(req, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, content='data: {"type":"response.completed","response":{"model":"model"}}\n\n')
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    result = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=post)).generate(
        LLMRequest(model='model', messages=[], headers={'authorization': 'evil', 'Host': 'evil.example'}))
    assert result.finish_reason == 'completed'
    assert calls[0]['follow_redirects'] is False
    headers = {key.lower(): value for key, value in calls[0]['headers'].items()}
    assert headers['authorization'] == 'Bearer test-token'
    assert 'host' not in headers


def test_plaintext_credential_envelope_is_rejected():
    encoded = base64.b64encode(json.dumps({'refresh_token': 'secret'}).encode()).decode()
    with pytest.raises(RuntimeError, match='protected|Unsupported'):
        ChatGPTPlanAuth._unprotect_json('file:' + encoded)


def test_descriptor_follows_protocol_provider_instead_of_template_number():
    from services.provider_settings import describe_protocol
    descriptor = describe_protocol('chatgpt_plan_default')
    assert descriptor.authentication == 'oauth_chatgpt'
    assert descriptor.settings.api_key is False
    assert descriptor.connection_action == 'sign_in'
    generic = describe_protocol('openai_compatible_default')
    assert generic.settings.api_key is True
    assert generic.connection_action == 'test_connection'


def test_backend_dispatches_auth_by_selected_protocol(monkeypatch):
    from controllers.api_presets_controller import ApiPresetsController
    from core.events import Event, Events
    launched = []
    controller = SimpleNamespace(templates={}, presets={}, _sync_account_action=lambda *args: None)
    monkeypatch.setattr('controllers.api_presets_controller.task_supervisor',
                        lambda: SimpleNamespace(start_thread=lambda *args, **kwargs: launched.append(kwargs)))
    ApiPresetsController._on_test_connection(controller, Event(Events.ApiPresets.TEST_CONNECTION,
        {'id': 42, 'base': None, 'protocol_id': 'chatgpt_plan_default', 'url': ''}))
    assert launched[0]['args'] == (42, 'chatgpt_plan_default', 'sign_in', '')


def test_saved_registrations_survive_sign_out_and_reload(tmp_path):
    path = tmp_path / 'auth.json'
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'revocation_endpoint': 'https://auth.openai.com/revoke'})))
    auth = ChatGPTPlanAuth(client=client, path=path)
    auth._data['account'] = {'client_id': 'a', 'email': 'same@example.org', 'refresh_token': 'one'}
    auth._save()
    auth._data['account'] = {'client_id': 'b', 'email': 'same@example.org', 'refresh_token': 'two'}
    auth._save()
    assert len(auth.list_accounts()) == 2
    result = auth.sign_out()
    assert result['revoked'] is True
    assert not result['signed_in']
    reloaded = ChatGPTPlanAuth(client=client, path=path)
    assert len(reloaded.list_accounts()) == 2
    assert 'refresh_token' not in reloaded._data['accounts']['b']
    assert reloaded._data['accounts']['a']['refresh_token'] == 'one'
    assert 'same@example.org' not in path.read_text()
    client.close()


def test_provider_streams_through_shared_event_channel(monkeypatch):
    events = []
    body = 'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
    body += 'data: {"type":"response.completed","response":{"model":"model","usage":{"input_tokens":2,"output_tokens":1,"total_tokens":3}}}\n\n'
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=lambda *args, **kwargs: httpx.Response(200, content=body)))
    response = provider.generate(LLMRequest(model='model', messages=[], stream=True, stream_event_cb=events.append))
    assert response.text == 'hi'
    assert any(event.text == 'hi' for event in events)
    assert response.usage.total_tokens == 3


def test_native_tool_response_uses_existing_application_contract(monkeypatch):
    output = {'type': 'function_call', 'call_id': 'c1', 'name': 'neuromita.lookup', 'arguments': '{"query":"abc"}'}
    body = 'data: ' + json.dumps({'type': 'response.completed', 'response': {'output': [output]}}) + '\n\n'
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    response = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=lambda *args, **kwargs: httpx.Response(200, content=body))).generate(
        LLMRequest(model='model', messages=[], tools_on=True, tools_payload=[{'name': 'lookup', 'parameters': {'type': 'object'}}]))
    assert response.text == ''
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == 'lookup'
    assert response.tool_calls[0].arguments == {'query': 'abc'}
    assert response.tool_calls[0].id == 'c1'


def test_transport_does_not_follow_redirect_with_bearer_credentials():
    from handlers.llm_providers.http_transport import LLMHttpClient
    destinations = []
    def handle(request):
        destinations.append(str(request.url))
        return httpx.Response(307, headers={'location': 'https://evil.example/'})
    transport = LLMHttpClient(enable_http2=False, client_factory=lambda *args: httpx.Client(
        follow_redirects=True, transport=httpx.MockTransport(handle)))
    req = LLMRequest(model='m', messages=[])
    response = transport.post_json(req, 'https://api.openai.com/v1/responses',
        headers={'Authorization': 'Bearer test'}, payload={}, stream=True, follow_redirects=False)
    assert response.status_code == 307
    assert destinations == ['https://api.openai.com/v1/responses']
    response.close()
    transport.close()


@pytest.mark.parametrize('refresh_failure', [False, True])
def test_real_preset_runner_provider_pipeline(monkeypatch, refresh_failure):
    from managers.api_preset_resolver import ApiPresetResolver
    from managers.llm_request_runner import LLMRequestRunner
    from handlers.llm_providers.http_transport import LLMHttpClient
    from managers.provider_manager import ProviderManager
    from schemas.structured_response import StructuredResponse
    settings = SimpleNamespace(get=lambda key, default=None: default)
    bus = SimpleNamespace(emit=lambda *args, **kwargs: None)
    resolver = ApiPresetResolver(settings, bus)
    monkeypatch.setattr(resolver, '_load_preset_full', lambda pid: {
        'name': 'Subscription', 'protocol_id': 'chatgpt_plan_default', 'base': 12,
        'default_model': 'model', 'url': 'https://api.openai.com/v1/responses'})
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        delta = json.dumps({'type': 'response.output_text.delta', 'delta': '{"segments":[{"text":"Hello"}]}'})
        terminal = json.dumps({'type': 'response.completed', 'response': {'model': 'model',
            'usage': {'input_tokens': 5, 'output_tokens': 3, 'total_tokens': 8}}})
        return httpx.Response(200, content=f'data: {delta}\n\ndata: {terminal}\n\n')
    credential_calls = []
    class Auth(FakeAuth):
        def get_credentials(self):
            credential_calls.append(1)
            if refresh_failure and len(credential_calls) == 1:
                raise httpx.ConnectError('temporary refresh failure')
            return 'test-token', 'test-account'
    auth = Auth()
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: auth)
    transport = LLMHttpClient(enable_http2=False, client_factory=lambda *args: httpx.Client(transport=httpx.MockTransport(handle)))
    manager = ProviderManager()
    manager.http_transport.close()
    manager.http_transport = transport
    manager._providers = [ChatGPTPlanProvider(http_transport=transport)]
    runner = LLMRequestRunner(settings, resolver, bus)
    runner.provider_manager.close()
    runner.provider_manager = manager
    events = []
    messages = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'hello'}]
    def build(preset, model):
        return LLMRequest(model=model, messages=messages, provider_name=preset.provider_name,
            api_url=preset.api_url, capabilities=preset.capabilities, native_parameters=preset.native_parameters,
            stream=True, stream_event_cb=events.append)
    try:
        result = runner.run(messages=messages, preset_id=42, stream_callback=None, build_request=build,
            max_attempts=2, retry_delay=0, request_timeout=10)
        assert len(credential_calls) == (2 if refresh_failure else 1)
        assert StructuredResponse.model_validate_json(result.text).segments[0].text == 'Hello'
        assert result.usage.total_tokens == 8
        assert requests[0]['store'] is False and requests[0]['stream'] is True
        assert requests[0]['input'][0]['role'] == 'developer'
        response_format = requests[0]['text']['format']
        assert response_format['type'] == 'json_schema'
        assert response_format['strict'] is True
        assert response_format['schema']['additionalProperties'] is False
        assert 'segments' in response_format['schema']['required']
        assert any(event.text for event in events)
    finally:
        runner.close()


def test_auth_exposes_quota_and_session_states(tmp_path):
    auth = ChatGPTPlanAuth(client=httpx.Client(), path=tmp_path / 'auth.json')
    assert auth.status().get('usage_state') == 'sign_in_required'
    auth.record_inference_error('subscription_sharing_usage_limit_exceeded')
    assert auth.status()['usage_state'] == 'quota_exhausted'
    auth.record_inference_error('chatpass_v2_scope_not_authorized')
    assert auth.status()['usage_state'] == 'session_invalid'
    auth.record_inference_error('subscription_sharing_usage_unavailable')
    assert auth.status()['usage_state'] == 'temporarily_unavailable'
    auth.record_inference_error('')
    assert auth.status()['usage_state'] == 'ready'
    auth._client.close()


def test_refresh_uses_latest_rotated_token_from_disk(tmp_path, monkeypatch):
    import time
    requests = []
    def handle(request):
        requests.append(request.content.decode())
        return httpx.Response(200, json={'access_token': 'fresh', 'refresh_token': 'rotated', 'expires_in': 3600})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    # Test synchronization independently of the OS credential API.
    monkeypatch.setattr(ChatGPTPlanAuth, '_protect_json', staticmethod(lambda obj: json.dumps(obj)))
    monkeypatch.setattr(ChatGPTPlanAuth, '_unprotect_json', staticmethod(json.loads))
    path = tmp_path / 'auth.json'
    first = ChatGPTPlanAuth(client=client, path=path)
    first._data['account'] = {'client_id': 'a', 'refresh_token': 'old', 'expires_at': 0,
                              'scopes': ['chatgpt.tokens.use.direct']}
    first._save()
    second = ChatGPTPlanAuth(client=client, path=path)
    first._data['account']['refresh_token'] = 'new'
    first._save()
    assert second.get_access_token() == 'fresh'
    assert 'refresh_token=new' in requests[0]
    assert second._data['account']['expires_at'] > int(time.time())
    client.close()


def test_unreadable_credentials_are_not_overwritten(tmp_path):
    path = tmp_path / 'auth.json'
    path.write_text('{broken json')
    with pytest.raises(RuntimeError, match='credentials'):
        ChatGPTPlanAuth(client=httpx.Client(), path=path)
    assert path.read_text() == '{broken json'


def test_account_error_state_stays_bound_to_request_account(tmp_path):
    client = httpx.Client()
    auth = ChatGPTPlanAuth(client=client, path=tmp_path / 'auth.json')
    auth._data['account'] = {'client_id': 'b', 'refresh_token': 'token', 'scopes': ['chatgpt.tokens.use.direct']}
    auth.record_inference_error('subscription_sharing_usage_limit_exceeded', account_id='a')
    assert auth.status()['usage_state'] == 'ready'
    assert auth._usage_states['a'] == 'quota_exhausted'
    client.close()


def test_subscription_settings_expose_only_supported_wire_parameters(tmp_path):
    from model_settings.repository import SchemaRepository
    from model_settings.service import ModelSettingsService
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    document = service.create('chatgpt-plan')
    document['enabled'] = ['reasoning_effort', 'verbosity']
    document['values'].update(reasoning_effort='low', verbosity='low')
    compiled = service.compile(document, 'openai_responses')
    assert compiled == {'reasoning': {'effort': 'low'}, 'text': {'verbosity': 'low'}}
    payload = build_responses_payload('model', [], parameters=compiled)
    assert payload['reasoning'] == {'effort': 'low'}
    assert payload['text'] == {'verbosity': 'low'}
    old = service.create('openai-compatible')
    migrated = service.for_preset({'protocol_id': 'chatgpt_plan_default', 'model_settings': old}, 'openai_responses')
    assert migrated['schema_id'] == 'chatgpt-plan'
    assert not migrated['enabled']
    assert old['schema_id'] == 'openai-compatible'


@pytest.mark.parametrize('location', ['catalog', 'preset'])
def test_legacy_responses_definition_preserves_custom_parameters(tmp_path, location):
    from copy import deepcopy
    from model_settings.repository import SchemaRepository
    from model_settings.service import ModelSettingsService
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    document = service.create('chatgpt-plan')
    legacy = deepcopy(service.repository.get('chatgpt-plan').data)
    legacy['dialect'] = 'openai_chat_completions'
    legacy['revision'] = 10
    legacy['fields'].append({'id': 'seed', 'path': ['seed'], 'type': 'integer', 'default': 7})
    document['values']['seed'] = 42
    document['enabled'] = ['seed']
    document['support_overrides'] = {'structured_output': False}
    if location == 'catalog':
        (tmp_path / 'schemas' / 'chatgpt-plan.json').write_text(json.dumps(legacy), encoding='utf-8')
    else:
        document['schema_override'] = legacy
    original = deepcopy(document)
    migrated = service.for_preset({'protocol_id': 'chatgpt_plan_default', 'model_settings': document}, 'openai_responses')
    assert service.compile(migrated, 'openai_responses') == {'seed': 42}
    assert migrated['support_overrides'] == {'structured_output': False}
    assert document == original
    assert service.resolve(migrated, 'openai_responses')[0].data['dialect'] == 'openai_responses'


def test_quota_failure_after_delta_marks_progress_and_never_returns_partial_text(monkeypatch):
    from handlers.llm_providers.base import RequestCancellation
    from handlers.llm_providers.errors import LLMProviderError
    body = 'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
    body += 'data: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}}\n\n'
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    cancellation = RequestCancellation()
    request = LLMRequest(model='model', messages=[], stream=True, extra={'_request_cancellation': cancellation})
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=lambda *args, **kwargs: httpx.Response(200, content=body)))
    with pytest.raises(LLMProviderError) as caught:
        provider.generate(request)
    assert caught.value.code == 'subscription_sharing_usage_limit_exceeded'
    assert caught.value.retryable is False
    assert cancellation.response_body_started


def test_unadvertised_native_tool_is_rejected_before_application_execution(monkeypatch):
    output = {'type': 'function_call', 'call_id': 'c1', 'name': 'shell', 'arguments': '{}'}
    body = 'data: ' + json.dumps({'type': 'response.completed', 'response': {'output': [output]}}) + '\n\n'
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: FakeAuth())
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=lambda *args, **kwargs: httpx.Response(200, content=body)))
    with pytest.raises(ValueError, match='unadvertised'):
        provider.generate(LLMRequest(model='model', messages=[], tools_on=True, tools_payload=[{'name': 'lookup'}]))
