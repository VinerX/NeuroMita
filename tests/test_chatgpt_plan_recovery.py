import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from handlers.llm_providers.chatgpt_plan_auth import ChatGPTPlanAuth
from services.provider_settings import run_account_action


@pytest.mark.parametrize('entry_point', ['sign_in', 'select_account'])
@pytest.mark.parametrize('concurrent_action', ['credentials', 'status', 'sign_out', 'select_account'])
def test_pending_oauth_does_not_hold_storage_lock_and_rechecks_publication(auth_factory, monkeypatch, concurrent_action, entry_point):
    from urllib.parse import parse_qs, urlencode, urlparse
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'revocation_endpoint': 'https://auth.openai.com/revoke'})
        if request.url.path == '/revoke':
            return httpx.Response(200)
        return httpx.Response(200, json={
            'access_token': 'fresh', 'refresh_token': 'rotated', 'id_token': 'identity',
            'scope': 'chatgpt.tokens.use.direct', 'expires_in': 3600,
        })
    auth = auth_factory(handle)
    auth._data['accounts']['other'] = {
        'client_id': 'other', 'subject': 'other-user', 'refresh_token': 'other-refresh',
        'access_token': 'other-access', 'expires_at': int(time.time()) + 3600,
        'scopes': ['chatgpt.tokens.use.direct'],
    }
    auth._save()
    if entry_point == 'select_account':
        auth._data['accounts']['registered'].pop('refresh_token')
        auth._data['account'] = dict(auth._data['accounts']['other'])
        auth._save()
    other = auth_factory(handle)
    ready, release = threading.Event(), threading.Event()
    def browser(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        ready.set()
        assert release.wait(5)
        callback = query['redirect_uri'][0] + '?' + urlencode({
            'state': query['state'][0], 'code': 'code', 'client_id': 'registered',
        })
        with httpx.Client(trust_env=False) as client:
            client.get(callback).raise_for_status()
        return True
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_auth.webbrowser.open', browser)
    monkeypatch.setattr(auth, '_validate_jwt', lambda *args, **kwargs: {
        'sub': 'user', 'iss': 'https://auth.openai.com', 'email': 'user@example.org',
    })
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = (executor.submit(auth.sign_in, 5) if entry_point == 'sign_in'
                   else executor.submit(auth.select_account, 'registered'))
        try:
            assert ready.wait(3)
            operation = {'credentials': other.get_credentials, 'status': auth.status, 'sign_out': other.sign_out,
                         'select_account': lambda: other.select_account('other')}[concurrent_action]
            executor.submit(operation).result(timeout=2)
        finally:
            release.set()
        if concurrent_action in {'credentials', 'status'}:
            assert pending.result(timeout=3)['plan_usage_enabled']
        else:
            with pytest.raises(RuntimeError, match='changed'):
                pending.result(timeout=3)
            reloaded = auth_factory(handle)
            if concurrent_action == 'sign_out':
                assert not reloaded.status()['signed_in']
            else:
                assert reloaded.status()['client_id'] == 'other'


def test_oauth_callback_default_allows_time_to_fix_connectivity():
    import inspect
    assert inspect.signature(ChatGPTPlanAuth.sign_in).parameters['timeout'].default >= 1800


@pytest.mark.parametrize('failure', [
    httpx.ConnectError('offline'), httpx.ReadTimeout('timeout'),
    httpx.HTTPStatusError('unavailable', request=httpx.Request('POST', 'https://auth.openai.com/'),
                         response=httpx.Response(503)),
    httpx.HTTPStatusError('too many requests', request=httpx.Request('POST', 'https://auth.openai.com/'),
                         response=httpx.Response(429)),
])
def test_provider_temporary_credential_failure_is_retryable(monkeypatch, failure):
    from handlers.llm_providers.base import LLMRequest
    from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider
    from handlers.llm_providers.errors import LLMProviderError
    def credentials():
        raise failure
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth',
                        lambda: SimpleNamespace(get_credentials=credentials))
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace(
        post_json=lambda *args, **kwargs: pytest.fail('No inference without credentials')))
    with pytest.raises(LLMProviderError) as caught:
        provider.generate(LLMRequest(model='m', messages=[]))
    assert caught.value.retryable
    assert caught.value.code == 'chatgpt_plan.auth_temporarily_unavailable'
    assert caught.value.phase == 'auth'
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize('failure', [PermissionError('consent required'), RuntimeError('Sign in required')])
def test_provider_terminal_credential_failure_still_requires_sign_in(monkeypatch, failure):
    from handlers.llm_providers.base import LLMRequest
    from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider
    from handlers.llm_providers.errors import LLMProviderError
    def credentials():
        raise failure
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth',
                        lambda: SimpleNamespace(get_credentials=credentials))
    with pytest.raises(LLMProviderError) as caught:
        ChatGPTPlanProvider(http_transport=SimpleNamespace()).generate(LLMRequest(model='m', messages=[]))
    assert not caught.value.retryable
    assert caught.value.code == 'chatgpt_plan.sign_in_required'


@pytest.fixture
def auth_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(ChatGPTPlanAuth, '_protect_json', staticmethod(json.dumps))
    monkeypatch.setattr(ChatGPTPlanAuth, '_unprotect_json', staticmethod(json.loads))
    clients = []

    def create(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        auth = ChatGPTPlanAuth(client=client, path=tmp_path / 'auth.json')
        if not auth._data.get('account'):
            auth._data['account'] = {
                'client_id': 'registered', 'subject': 'user', 'email': 'user@example.org',
                'refresh_token': 'refresh', 'access_token': 'expired', 'id_token': 'identity',
                'expires_at': 0, 'scopes': ['chatgpt.tokens.use.direct'],
            }
            auth._save()
        return auth

    yield create
    for client in clients:
        client.close()


@pytest.mark.parametrize('code', [
    'invalid_grant', 'invalid_refresh_token', 'token_expired',
    'refresh_token_expired', 'refresh_token_invalidated', 'refresh_token_reused',
])
@pytest.mark.parametrize('nested', [False, True])
def test_terminal_refresh_clears_tokens_but_keeps_registration(auth_factory, code, nested):
    payload = {'error': {'code': code}} if nested else {'error': code}
    auth = auth_factory(lambda request: httpx.Response(400, json=payload))
    with pytest.raises(RuntimeError, match='Sign in'):
        auth.get_access_token()
    reloaded = auth_factory(lambda request: pytest.fail('No request expected'))
    account = reloaded._data['account']
    assert account['client_id'] == 'registered'
    assert account['subject'] == 'user'
    assert reloaded.host_id == auth.host_id
    assert all(key not in account for key in ('access_token', 'refresh_token', 'id_token'))
    assert reloaded.status()['usage_state'] == 'sign_in_required'


@pytest.mark.parametrize('status, code', [(503, 'invalid_grant'), (400, 'invalid_client')])
def test_temporary_or_client_failure_keeps_tokens(auth_factory, status, code):
    auth = auth_factory(lambda request: httpx.Response(status, json={'error': code}))
    with pytest.raises(httpx.HTTPStatusError):
        auth.get_access_token()
    assert auth_factory(lambda request: None)._data['account']['refresh_token'] == 'refresh'


def test_network_refresh_failure_keeps_tokens(auth_factory):
    def fail(request):
        raise httpx.ConnectError('offline', request=request)
    auth = auth_factory(fail)
    with pytest.raises(httpx.ConnectError):
        auth.get_access_token()
    assert auth_factory(lambda request: None)._data['account']['refresh_token'] == 'refresh'


def test_valid_identity_without_direct_scope_is_saved_but_cannot_infer(auth_factory, monkeypatch):
    auth = auth_factory(lambda request: pytest.fail('Inference/refresh must not be called'))
    monkeypatch.setattr(auth, '_validate_jwt', lambda *args, **kwargs: {
        'email': 'user@example.org', 'iss': 'https://auth.openai.com', 'sub': 'user',
    })
    auth._data['account'] = auth._validated_record({
        'id_token': 'valid-identity', 'access_token': 'access', 'refresh_token': 'refresh',
        'scope': 'openid email offline_access', 'expires_in': 3600,
    }, 'registered', 'nonce')
    auth._save()
    assert auth.status()['signed_in']
    assert not auth.status()['plan_usage_enabled']
    assert auth.status()['usage_state'] == 'plan_usage_disabled'
    with pytest.raises(PermissionError, match='enable'):
        auth.get_access_token()
    assert auth_factory(lambda request: None).status()['signed_in']
    assert auth.select_account('registered')['usage_state'] == 'plan_usage_disabled'


@pytest.mark.parametrize('action', ['sign_in', 'add_account', 'select_account'])
def test_catalog_failure_does_not_turn_successful_login_into_failure(monkeypatch, action):
    status = {'signed_in': True, 'plan_usage_enabled': True, 'email': 'a@example.org'}
    def fail():
        raise httpx.ConnectError('offline')
    auth = SimpleNamespace(sign_in=lambda **kwargs: status, select_account=lambda aid: status,
                           status=lambda: status, list_models=fail)
    monkeypatch.setattr('services.provider_settings.authentication_service', lambda pid: auth)
    result = run_account_action('chatgpt_plan_default', action, 'registered')
    assert result['success']
    assert result['account']['signed_in']
    assert not result['models']
    assert result['catalog_error']


def test_explicit_catalog_refresh_failure_is_reported(monkeypatch):
    def fail():
        raise httpx.ConnectError('offline')
    auth = SimpleNamespace(status=lambda: {'signed_in': True, 'plan_usage_enabled': True}, list_models=fail)
    monkeypatch.setattr('services.provider_settings.authentication_service', lambda pid: auth)
    assert not run_account_action('chatgpt_plan_default', 'list_models')['success']


def test_disabled_usage_does_not_fetch_catalog(monkeypatch):
    status = {'signed_in': True, 'plan_usage_enabled': False}
    auth = SimpleNamespace(sign_in=lambda: status, status=lambda: status,
                           list_models=lambda: pytest.fail('Plan usage disabled'))
    monkeypatch.setattr('services.provider_settings.authentication_service', lambda pid: auth)
    result = run_account_action('chatgpt_plan_default', 'sign_in')
    assert result['success'] and not result['models']


def test_plan_usage_notice_is_only_shown_once_across_restarts(auth_factory):
    auth = auth_factory(lambda request: None)
    assert auth.consume_plan_usage_notice()
    assert not auth.consume_plan_usage_notice()
    reloaded = auth_factory(lambda request: None)
    assert not reloaded.consume_plan_usage_notice()


def test_selecting_expired_account_keeps_other_account_active_and_clears_failed_tokens(auth_factory):
    auth = auth_factory(lambda request: httpx.Response(400, json={'error': 'invalid_grant'}))
    auth._data['account'] = {'client_id': 'other', 'refresh_token': 'other-refresh',
                              'scopes': ['chatgpt.tokens.use.direct']}
    auth._save()
    with pytest.raises(RuntimeError):
        auth.select_account('registered')
    reloaded = auth_factory(lambda request: None)
    assert reloaded._data['account']['client_id'] == 'other'
    assert 'refresh_token' not in reloaded._data['accounts']['registered']
    assert reloaded._data['accounts']['other']['refresh_token'] == 'other-refresh'


def test_oauth_catalog_generation_restart_refresh_and_sign_out(auth_factory, monkeypatch):
    from urllib.parse import parse_qs, urlencode, urlparse
    from handlers.llm_providers.base import LLMRequest
    from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider
    grants = []
    def handle(request):
        if request.url.path.endswith('/oauth/token'):
            data = parse_qs(request.content.decode())
            grants.append(data)
            return httpx.Response(200, json={
                'access_token': 'access', 'refresh_token': 'rotated', 'id_token': 'identity',
                'scope': 'openid email offline_access chatgpt.tokens.use.direct', 'expires_in': 3600,
            })
        if request.url.path == '/v1/models':
            assert request.headers['authorization'] == 'Bearer access'
            return httpx.Response(200, json={'models': [
                {'slug': 'account-luna', 'display_name': 'Luna', 'visibility': 'list'},
                {'slug': 'hidden', 'visibility': 'hidden'},
            ]})
        if request.method == 'GET':
            return httpx.Response(200, json={'revocation_endpoint': 'https://auth.openai.com/revoke'})
        assert request.url.path == '/revoke'
        return httpx.Response(200)
    auth = auth_factory(handle)
    def browser(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        assert query['client_id'] == ['registered']
        assert 'chatgpt.tokens.use.direct' in query['scope'][0]
        callback = query['redirect_uri'][0] + '?' + urlencode({
            'state': query['state'][0], 'code': 'test-code', 'client_id': 'registered',
        })
        with httpx.Client(trust_env=False) as loopback:
            loopback.get(callback).raise_for_status()
        return True
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_auth.webbrowser.open', browser)
    monkeypatch.setattr(auth, '_validate_jwt', lambda *args, **kwargs: {
        'sub': 'user', 'email': 'user@example.org', 'iss': 'https://auth.openai.com',
    })
    assert auth.sign_in(timeout=5)['plan_usage_enabled']
    assert auth.list_models() == [{'id': 'account-luna', 'name': 'Luna'}]
    requests = []
    def post(req, url, **kwargs):
        requests.append(kwargs['payload'])
        terminal = {'type': 'response.completed', 'response': {
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'hello'}]}],
        }}
        delta = {'type': 'response.output_text.delta', 'delta': 'hello'}
        return httpx.Response(200, content='data: ' + json.dumps(delta) + '\n\ndata: ' + json.dumps(terminal) + '\n\n')
    monkeypatch.setattr('handlers.llm_providers.chatgpt_plan_provider.get_chatgpt_plan_auth', lambda: auth)
    provider = ChatGPTPlanProvider(http_transport=SimpleNamespace(post_json=post))
    req = LLMRequest(model='account-luna', messages=[{'role': 'user', 'content': 'hello'}])
    assert provider.generate(req).text == 'hello'
    assert provider.generate(req).text == 'hello'
    assert all('prompt_cache_options' not in payload for payload in requests)
    auth._data['account']['expires_at'] = 0
    auth._save()
    reloaded = auth_factory(handle)
    assert reloaded.get_access_token() == 'access'
    assert grants[-1]['grant_type'] == ['refresh_token']
    assert grants[-1]['refresh_token'] == ['rotated']
    assert reloaded.sign_out()['revoked']
    after = auth_factory(handle)
    assert after._data['account']['client_id'] == 'registered'
    assert after.status()['usage_state'] == 'sign_in_required'
