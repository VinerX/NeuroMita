import json

import pytest

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.chatgpt_plan_protocol import ResponsesInferenceAdapter
from schemas.game_master_response import GameMasterResponse
from schemas.structured_response import StructuredResponse


def assert_strict_schema(node):
    if isinstance(node, dict):
        assert 'default' not in node
        if node.get('type') == 'object':
            assert node['additionalProperties'] is False
            assert set(node['required']) == set(node['properties'])
        for value in node.values():
            assert_strict_schema(value)
    elif isinstance(node, list):
        for value in node:
            assert_strict_schema(value)


def test_structured_request_sends_strict_responses_schema_and_preserves_verbosity():
    parameters = {'text': {'verbosity': 'low', 'format': {'type': 'text'}}}
    req = LLMRequest(model='gpt-6-luna', messages=[], structured_model=StructuredResponse,
        capabilities={'structured_output': True, 'native_structured_output': True,
            'schema_reasoning': False, 'schema_intents': False,
            'structured_exclude_fields': ['working_state'],
            'structured_segment_exclude_fields': ['clothes']}, native_parameters=parameters)
    payload = ResponsesInferenceAdapter().build(req)
    fmt = payload['text']['format']
    assert fmt['type'] == 'json_schema'
    assert fmt['strict'] is True
    assert fmt['name'] == 'structured_response'
    assert payload['text']['verbosity'] == 'low'
    assert parameters['text']['format']['type'] == 'text'
    assert 'response_format' not in payload
    assert payload['store'] is False and payload['stream'] is True
    props = fmt['schema']['properties']
    assert not {'reasoning', 'custom_fields', 'working_state'} & props.keys()
    segment = props['segments']['items']['properties']
    assert not {'intents', 'clothes'} & segment.keys()
    assert_strict_schema(fmt['schema'])


def test_custom_game_master_model_reaches_responses_format():
    req = LLMRequest(model='gpt-6-luna', messages=[], structured_model=GameMasterResponse,
        capabilities={'structured_output': True})
    fmt = ResponsesInferenceAdapter().build(req)['text']['format']
    assert fmt['name'] == 'game_master_response'
    assert 'actions' in fmt['schema']['properties']
    assert 'segments' not in fmt['schema']['properties']
    assert_strict_schema(fmt['schema'])


def test_custom_parameters_and_free_form_action_data_survive_strict_schema():
    req = LLMRequest(model='gpt-6-luna', messages=[], capabilities={
        'structured_output': True, 'schema_intents': True,
        'custom_params': [{'name': 'energy', 'type': 'float'}]})
    schema = ResponsesInferenceAdapter().build(req)['text']['format']['schema']
    custom = schema['properties']['custom_fields']['anyOf'][0]
    assert custom['properties']['energy']['type'] == 'number'
    intent = schema['properties']['segments']['items']['properties']['intents']['items']
    assert intent['properties']['payload']['type'] == 'string'
    assert_strict_schema(schema)
    decoded = StructuredResponse.model_validate_json(json.dumps({
        'segments': [{'text': 'Hello', 'intents': [{'type': 'light.test', 'payload': '{"value":1}'}]}],
        'tool_call': {'name': 'test', 'args': '{"query":"hello"}'}, 'custom_fields': {'energy': 1}}))
    assert decoded.segments[0].intents[0].payload == {'value': 1}
    assert decoded.tool_call.args == {'query': 'hello'}


@pytest.mark.parametrize('caps', [{}, {'structured_output': False},
    {'structured_output': True, 'native_structured_output': False}])
def test_unstructured_requests_do_not_acquire_response_schema(caps):
    req = LLMRequest(model='m', messages=[], structured_model=StructuredResponse, capabilities=caps)
    assert 'text' not in ResponsesInferenceAdapter().build(req)


def test_json_object_mode_is_forwarded_without_schema():
    req = LLMRequest(model='m', messages=[], capabilities={
        'structured_output': True, 'structured_output_mode': 'json_object'})
    assert ResponsesInferenceAdapter().build(req)['text']['format'] == {'type': 'json_object'}


def test_undeclared_custom_parameters_are_rejected_instead_of_silently_erased():
    req = LLMRequest(model='m', messages=[], capabilities={
        'structured_output': True, 'has_custom_params': True})
    with pytest.raises(ValueError, match='declared properties for custom_fields'):
        ResponsesInferenceAdapter().build(req)


def test_subscription_schema_enables_native_structured_output():
    from model_settings.service import ModelSettingsService
    from presets.api_protocols import API_PROTOCOLS_DATA
    protocol = next(p for p in API_PROTOCOLS_DATA if p['id'] == 'chatgpt_plan_default')
    assert protocol['capabilities']['native_structured_output'] is True
    assert ModelSettingsService().repository.get('chatgpt-plan').data['supports']['structured_output'] is True
