from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from controllers.api_presets_controller import ApiPresetsController, ApiTemplate, UserPreset
from controllers.protocols_controller import ProtocolsController
from managers.api_preset_resolver import ApiPresetResolver
from managers.protocol_registry import ProtocolRegistry
from model_settings.repository import SchemaRepository
from model_settings.schema import SchemaError
from model_settings.service import ModelSettingsService
from presets.api_protocols import API_PROTOCOLS_DATA
from presets.api_templates import API_TEMPLATES_DATA
from services.contracts import ApiPresetService, ProtocolBuilderService
from services.provider_settings import describe_protocol


@pytest.fixture
def service(tmp_path):
    return ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))


def responses_template():
    matches = [item for item in API_TEMPLATES_DATA if item['protocol_id'] == 'openai_responses_default']
    assert len(matches) == 1, 'API-key Responses template must be available in the existing API UI'
    return deepcopy(matches[0])


def test_protocol_keeps_api_key_responses_separate_from_siwc():
    registry = ProtocolRegistry(API_PROTOCOLS_DATA)
    generic = registry.get('openai_responses_default')
    assert generic is not None, 'Missing API-key Responses protocol'
    assert generic.provider == 'common'
    assert generic.dialect == 'openai_responses'
    assert generic.auth['mode'] == 'bearer'
    assert generic.settings_schema_id == 'openai-responses'
    assert generic.capabilities['force_wire_stream'] is False
    assert not generic.capabilities.get('tools_namespace')
    assert generic.capabilities['streaming_with_tools'] is True
    siwc = registry.get('chatgpt_plan_default')
    assert siwc.provider == 'chatgpt_plan'
    assert siwc.auth['mode'] == 'oauth_chatgpt'
    assert siwc.settings_schema_id == 'chatgpt-plan'
    assert siwc.capabilities['force_wire_stream'] is True
    assert siwc.capabilities['tools_namespace'] == 'neuromita'


def test_ui_exposes_editable_endpoint_and_api_key_without_account_login():
    template = responses_template()
    assert template['id'] == 13
    assert template['url'] == 'https://api.openai.com/v1/responses'
    assert template['url_editable'] is True
    assert template['test_url_editable'] is True
    descriptor = describe_protocol(template['protocol_id'])
    assert descriptor.settings.api_key
    assert descriptor.settings.api_url
    assert descriptor.settings.reserve_keys
    assert descriptor.connection_action == 'test_connection'
    assert not descriptor.account_actions
    assert descriptor.authentication == 'bearer'


def test_generic_profile_is_default_but_existing_siwc_migration_stays_explicit(service):
    assert service.default_id('openai_responses') == 'openai-responses'
    legacy = {'protocol_id': 'chatgpt_plan_default', 'model_settings': service.create('openai-compatible')}
    document = service.for_preset(legacy, 'openai_responses')
    assert document['schema_id'] == 'chatgpt-plan'
    assert service.for_preset({'protocol_id': 'chatgpt_plan_default'}, 'openai_responses')['schema_id'] == 'chatgpt-plan'
    assert legacy['model_settings']['schema_id'] == 'openai-compatible'


def test_native_parameters_compile_to_responses_paths_without_siwc_restrictions(service):
    assert 'openai-responses' in service.repository.catalog(), 'Missing independent Responses settings profile'
    document = service.create('openai-responses')
    assert service.compile(document, 'openai_responses') == {}
    document['enabled'] = ['temperature', 'top_p', 'max_tokens', 'reasoning_effort', 'reasoning_summary', 'verbosity']
    document['values'].update(temperature=0.7, top_p=0.8, max_tokens=8192,
                              reasoning_effort='xhigh', reasoning_summary='auto', verbosity='low')
    assert service.compile(document, 'openai_responses') == {
        'temperature': 0.7, 'top_p': 0.8, 'max_output_tokens': 8192,
        'reasoning': {'effort': 'xhigh', 'summary': 'auto'}, 'text': {'verbosity': 'low'},
    }
    siwc_fields = {item['id'] for item in service.repository.get('chatgpt-plan').fields}
    assert not siwc_fields.intersection({'temperature', 'top_p', 'max_tokens'})


@pytest.mark.parametrize('field,value', [('temperature', -1), ('temperature', 3), ('top_p', 1.1), ('max_tokens', 0)])
def test_generic_profile_rejects_invalid_native_parameters(service, field, value):
    assert 'openai-responses' in service.repository.catalog(), 'Missing independent Responses settings profile'
    document = service.create('openai-responses')
    document['enabled'] = [field]
    document['values'][field] = value
    with pytest.raises(SchemaError):
        service.compile(document, 'openai_responses')


def test_existing_sampling_settings_migrate_to_native_responses_limit(service):
    preset = {'protocol_id': 'openai_responses_default', 'generation_overrides': {
        'max_tokens': {'enabled': True, 'value': 4096},
    }}
    document = service.for_preset(preset, 'openai_responses', {'USE_MODEL_TEMPERATURE': False})
    assert document['schema_id'] == 'openai-responses'
    assert service.compile(document, 'openai_responses') == {'max_output_tokens': 4096}


def test_standard_template_resolves_custom_endpoint_key_and_native_parameters(service):
    template = responses_template()
    controller = ApiPresetsController.__new__(ApiPresetsController)
    controller.model_settings_service = service
    controller.templates = {template['id']: ApiTemplate(**template)}
    document = service.create(template['settings_schema_id'])
    document['enabled'] = ['max_tokens', 'reasoning_effort', 'verbosity']
    document['values'].update(max_tokens=4096, reasoning_effort='high', verbosity='low')
    endpoint = 'https://responses.example.test/custom/responses'
    controller.presets = {1001: UserPreset(id=1001, name='Responses', base=template['id'],
        url=endpoint, key='test-api-key', default_model='test-model', model_settings=document)}
    registry = ProtocolRegistry(API_PROTOCOLS_DATA)
    builder = ProtocolsController.__new__(ProtocolsController)
    resolver = ApiPresetResolver({}, None, model_settings_service=service)

    def use_service(contract):
        return {ApiPresetService: controller, ProtocolBuilderService: builder}[contract]

    with patch('managers.protocol_registry.get_protocol_registry', return_value=registry), \
            patch('managers.api_preset_resolver.get_protocol_registry', return_value=registry), \
            patch('controllers.protocols_controller.get_protocol_registry', return_value=registry), \
            patch('managers.api_preset_resolver.use', side_effect=use_service):
        effective = controller.get_full(1001)
        assert effective['url'] == endpoint
        resolved = resolver.resolve(1001)
    assert resolved.protocol_id == 'openai_responses_default'
    assert resolved.provider_name == 'common'
    assert resolved.dialect_id == 'openai_responses'
    assert resolved.api_url == endpoint
    assert resolved.api_model == 'test-model'
    assert resolved.headers['Authorization'] == 'Bearer test-api-key'
    assert resolved.native_parameters == {
        'max_output_tokens': 4096, 'reasoning': {'effort': 'high'}, 'text': {'verbosity': 'low'},
    }
    assert resolved.capabilities['force_wire_stream'] is False
    assert resolved.capabilities['native_structured_output'] is True
    assert resolved.capabilities['sparse_response'] is False


def test_existing_template_ids_and_protocols_are_preserved():
    old_ids = {1: 'mistral_default', 2: 'openrouter_default', 3: 'google_gemini_default',
               4: 'aiio_default', 5: 'openai_compatible_default', 6: 'openai_compatible_default',
               7: 'openai_compatible_default', 8: 'openai_compatible_default', 9: 'lmstudio_default',
               10: 'openai_compatible_default', 11: 'openai_compatible_default', 12: 'chatgpt_plan_default'}
    actual = {item['id']: item['protocol_id'] for item in API_TEMPLATES_DATA}
    assert {identifier: actual[identifier] for identifier in old_ids} == old_ids
    assert len(actual) == len(API_TEMPLATES_DATA)
