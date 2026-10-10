import json
from unittest.mock import patch
from types import SimpleNamespace

import httpx
import pytest

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.http_transport import LLMHttpClient
from managers.provider_manager import ProviderManager
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService


@pytest.mark.parametrize('dialect', ['openai_chat_completions', 'openai_responses'])
@pytest.mark.parametrize('stream', [False, True])
def test_openai_provider_alias_runs_without_sdk(dialect, stream):
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if dialect == 'openai_responses':
            response = {'status': 'completed', 'output': [{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'OK'}]}]}
            events = [{'type': 'response.completed', 'response': response}]
        else:
            response = {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}
            events = [{'choices': [{'delta': {'content': 'OK'}, 'finish_reason': 'stop'}]}]
        if stream:
            return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))
        return httpx.Response(200, json=response)

    with patch.dict('sys.modules', {'openai': None, 'g4f': None}):
        manager = ProviderManager()
        manager.http_transport.close()
        transport = LLMHttpClient(client_factory=lambda *_: httpx.Client(transport=httpx.MockTransport(handle)))
        manager.http_transport = transport
        for provider in manager._providers:
            provider.http_transport = transport
        try:
            req = LLMRequest(model='m', messages=[{'role': 'user', 'content': 'Hello'}],
                             provider_name='openai', dialect_id=dialect, stream=stream,
                             api_key='fixture', api_url='https://test.invalid/v1')
            assert manager.generate(req).text == 'OK'
            assert requests[0][0] == ('/v1/responses' if dialect == 'openai_responses' else '/v1/chat/completions')
            assert requests[0][1]['stream'] is stream
            assert 'extra_body' not in requests[0][1]
        finally:
            manager.close()


def test_retired_g4f_cannot_generate_and_saved_schema_is_preserved(tmp_path):
    path = tmp_path / 'g4f.json'
    path.write_text(json.dumps({'schema_version': 1, 'id': 'g4f', 'dialect': 'g4f'}))
    original = path.read_bytes()
    assert 'g4f' not in SchemaRepository(tmp_path).catalog()
    assert path.read_bytes() == original
    manager = ProviderManager()
    try:
        with pytest.raises(RuntimeError, match='unavailable'):
            manager.generate(LLMRequest(model='m', messages=[], provider_name='g4f', dialect_id='g4f'))
    finally:
        manager.close()


def test_retired_preset_survives_startup_without_becoming_a_chat_preset(tmp_path):
    from controllers.api_presets_controller import ApiPresetsController
    from managers.api_preset_resolver import ApiPresetResolver
    settings = tmp_path / 'Settings'
    settings.mkdir()
    saved = {'id': 1001, 'name': 'Retired', 'protocol_id': 'g4f_default',
             'generation_overrides': {'temperature': {'enabled': True, 'value': 0.5}}}
    path = settings / 'api_presets.json'
    path.write_text(json.dumps({'presets': {'1001': saved}, 'order': [1001]}))
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    with patch('core.app_paths.base_dir', return_value=tmp_path), \
            patch.object(ApiPresetsController, '_migrate_old_api_keys'):
        controller = ApiPresetsController(model_settings_service=service)
        try:
            preset = controller.get_full(1001)
            assert preset['protocol_id'] == 'g4f_default'
            assert preset['generation_overrides'] == saved['generation_overrides']
            assert preset.get('model_settings') is None
            resolver = ApiPresetResolver({}, SimpleNamespace(), model_settings_service=service)
            with patch.object(resolver, '_load_preset_full', return_value=preset):
                with pytest.raises(ValueError, match='unavailable'):
                    resolver.resolve(1001)
            reloaded = json.loads(path.read_text())['presets']['1001']
            assert reloaded['protocol_id'] == 'g4f_default'
            assert reloaded['generation_overrides'] == saved['generation_overrides']
        finally:
            controller.close()
