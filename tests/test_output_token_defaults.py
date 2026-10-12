from copy import deepcopy
from types import SimpleNamespace

import pytest

from handlers.llm_providers.param_mapper import build_unified_generation_params
from managers.model_config_loader import ModelConfigLoader, ModelRuntimeConfig
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService


TOKEN_SCHEMAS = [
    'google-budget-lite', 'google-budget-pro', 'google-budget', 'google-level',
    'groq', 'local-openai', 'mistral', 'openai-compatible', 'openai-responses',
    'openrouter', 'together',
]
TOKEN_PATHS = {
    'gemini_generate_content': ('generationConfig', 'maxOutputTokens'),
    'openai_chat_completions': ('max_tokens',),
    'openai_responses': ('max_output_tokens',),
}


@pytest.fixture
def service(tmp_path):
    return ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))


def output_limit(service, document, dialect):
    payload = service.compile(document, dialect)
    path = ('max_completion_tokens',) if document['schema_id'] == 'groq' else TOKEN_PATHS[dialect]
    for key in path:
        payload = payload[key]
    return payload


@pytest.mark.parametrize('identifier', TOKEN_SCHEMAS)
@pytest.mark.parametrize('missing_value', [False, True])
def test_new_or_incomplete_preset_sends_5000_tokens(service, identifier, missing_value):
    document = service.create(identifier)
    if missing_value:
        document['values'].pop('max_tokens')
    document['enabled'] = ['max_tokens']
    dialect = service.repository.get(identifier).data['dialect']
    assert output_limit(service, document, dialect) == 5000


@pytest.mark.parametrize('identifier', TOKEN_SCHEMAS)
@pytest.mark.parametrize('saved_limit', [2500, 8192])
def test_saved_preset_token_limit_survives_resolution(service, identifier, saved_limit):
    document = service.create(identifier)
    document['values']['max_tokens'] = saved_limit
    document['enabled'] = ['max_tokens']
    saved = deepcopy(document)
    dialect = service.repository.get(identifier).data['dialect']
    resolved = service.for_preset({'model_settings': document}, dialect)
    assert output_limit(service, resolved, dialect) == saved_limit
    assert document == saved


@pytest.mark.parametrize('identifier', TOKEN_SCHEMAS)
@pytest.mark.parametrize('settings, expected', [({}, 5000), ({'MODEL_MAX_RESPONSE_TOKENS': 2500}, 2500)])
def test_legacy_preset_migration_defaults_without_replacing_saved_limit(service, identifier, settings, expected):
    dialect = service.repository.get(identifier).data['dialect']
    preset = {'settings_schema_id': identifier, 'model_profile_overrides': {'parameters': ['max_tokens']}}
    document = service.for_preset(preset, dialect, settings)
    assert output_limit(service, document, dialect) == expected


def runtime_payload(config, settings=None):
    return build_unified_generation_params(
        settings=settings if settings is not None else {},
        temperature=config.temperature,
        max_response_tokens=config.max_response_tokens,
        presence_penalty=config.presence_penalty,
        frequency_penalty=config.frequency_penalty,
        log_probability=config.log_probability,
        top_k=config.top_k,
        top_p=config.top_p,
        thinking_budget=config.thinking_budget,
        force_params=config.preset_forced_params,
    )


def test_direct_runtime_config_sends_5000_tokens():
    assert runtime_payload(ModelRuntimeConfig())['max_tokens'] == 5000


@pytest.mark.parametrize('settings', [
    {}, {'MODEL_MAX_RESPONSE_TOKENS': None}, {'MODEL_MAX_RESPONSE_TOKENS': ''},
    {'MODEL_MAX_RESPONSE_TOKENS': 'invalid'}, {'MODEL_MAX_RESPONSE_TOKENS': 0},
])
def test_runtime_loader_fallback_sends_5000_tokens(settings):
    assert runtime_payload(ModelConfigLoader(settings).load())['max_tokens'] == 5000


@pytest.mark.parametrize('saved_limit', [2500, '2500', 8192])
def test_runtime_loader_preserves_saved_user_limit(saved_limit):
    config = ModelConfigLoader({'MODEL_MAX_RESPONSE_TOKENS': saved_limit}).load()
    assert runtime_payload(config)['max_tokens'] == int(saved_limit)


@pytest.mark.parametrize('enabled, value, expected', [(True, 2500, 2500), (True, 8192, 8192), (False, 2500, 5000)])
def test_runtime_preset_override_keeps_its_limit_or_uses_default(enabled, value, expected):
    loader = ModelConfigLoader({})
    base = loader.load()
    preset = SimpleNamespace(generation_overrides={'max_tokens': {'enabled': enabled, 'value': value}})
    effective = loader.effective_for_preset(base, preset, 'test-model')
    assert runtime_payload(effective)['max_tokens'] == expected
    assert runtime_payload(base)['max_tokens'] == 5000


def test_disabled_token_limit_remains_omitted(service):
    document = service.create('openai-compatible')
    document['enabled'] = []
    assert 'max_tokens' not in service.compile(document, 'openai_chat_completions')
    settings = {'USE_MODEL_MAX_RESPONSE_TOKENS': False}
    assert 'max_tokens' not in runtime_payload(ModelConfigLoader(settings).load(), settings)
