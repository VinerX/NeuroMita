import json
from types import SimpleNamespace

import pytest

from handlers.llm_providers.base import LLMRequest, LLMResponse, ToolCall as NativeToolCall
from services.structured_response_capabilities import resolve_structured_response_capabilities
from services.contracts import RuntimeCapabilities


def profile(**overrides):
    values = dict(settings={}, runtime=RuntimeCapabilities(), character=SimpleNamespace(),
                  structured_output=True, tools_enabled=True, enabled_tools=('calculator',),
                  tools_mode='native', tool_depth=0, tool_max_depth=2,
                  images_available=False, has_custom_params=False, schema_reasoning=False)
    values.update(overrides)
    return resolve_structured_response_capabilities(**values)


def native_response(text=None, name='calculator', call_id='call_real'):
    response = LLMResponse(text=text)
    response.tool_calls = [NativeToolCall(name=name, arguments={'value': 41}, id=call_id)]
    return response


def request():
    return LLMRequest(model='m', messages=[], tools_on=True, tools_payload=[
        {'name': 'calculator', 'parameters': {'type': 'object'}}],
        capabilities={'structured_response_profile': profile()})


def test_bridge_preserves_structured_json_and_native_id():
    from services.native_tool_calls import bridge_native_tool_response
    response = native_response(json.dumps({'segments': [{'text': 'Checking', 'target': 'Player'}],
                                           'memory_add': [{'text': 'retain'}]}))
    bridge_native_tool_response(response, request())
    data = json.loads(response.text)
    assert data['segments'][0]['text'] == 'Checking'
    assert data['memory_add'] == [{'text': 'retain'}]
    assert data['tool_call'] == {'name': 'calculator', 'args': {'value': 41}}
    assert response.raw['native_tool_call']['id'] == 'call_real'


@pytest.mark.parametrize('text', [None, 'Checking'])
def test_bridge_accepts_tool_only_and_plain_text(text):
    from services.native_tool_calls import bridge_native_tool_response
    response = native_response(text)
    bridge_native_tool_response(response, request())
    assert json.loads(response.text)['segments'] == ([{'text': text}] if text else [])


@pytest.mark.parametrize('case', ['dual', 'sparse_dual', 'multiple', 'unadvertised', 'missing_id', 'invalid_args', 'disabled'])
def test_bridge_rejects_invalid_native_calls(case):
    from services.native_tool_calls import bridge_native_tool_response
    response, req = native_response(), request()
    if case == 'dual':
        response.text = '{"segments":[],"tool_call":{"name":"calculator","args":{}}}'
    elif case == 'sparse_dual':
        response.text = '{"segments":[],"changes":[{"type":"tool_call","name":"calculator","args":"{}"}]}'
    elif case == 'multiple':
        response.tool_calls *= 2
    elif case == 'unadvertised':
        response.tool_calls = [NativeToolCall(name='web_reader', arguments={}, id='c')]
    elif case == 'missing_id':
        response.tool_calls = [NativeToolCall(name='calculator', arguments={}, id='')]
    elif case == 'invalid_args':
        response.tool_calls = [NativeToolCall(name='calculator', arguments=[], id='c')]
    else:
        req.tools_on = False
    with pytest.raises(ValueError):
        bridge_native_tool_response(response, req)


@pytest.mark.parametrize('dialect,capable,mode', [
    ('openai_chat_completions', True, 'native'), ('openai_responses', True, 'native'),
    ('gemini_generate_content', True, 'schema'), ('openai_chat_completions', False, 'schema')])
def test_chat_model_builds_actual_request_from_profile(monkeypatch, dialect, capable, mode):
    import handlers.chat_handler as module
    from managers.api_preset_resolver import PresetSettings
    preset = PresetSettings(protocol_id='test', dialect_id=dialect, provider_name='common',
        headers={}, transforms=[], capabilities={'structured_output': True, 'tools_native': capable},
        api_key='key', api_url='https://example.test', api_model='m', preset_name='test', reserve_keys=[])
    monkeypatch.setattr(module, 'ApiPresetResolver', lambda **_: SimpleNamespace(resolve=lambda *_: preset))
    monkeypatch.setattr(module, '_save_last_request_context', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, '_save_last_response_context', lambda *_args, **_kwargs: None)
    settings = SimpleNamespace(get=lambda key, default=None: default)
    model = module.ChatModel(settings)
    captured = []
    def run(**kwargs):
        captured.append(kwargs['build_request'](preset, 'm'))
        return LLMResponse(text='{"segments":[{"text":"done"}]}')
    model.request_runner.run = run
    model.generate([], capabilities_override={'structured_response_profile': profile()})
    req = captured[0]
    assert req.tools_mode == mode
    assert req.tools_on is (mode == 'native')
    assert [tool['name'] for tool in req.tools_payload or []] == (['calculator'] if mode == 'native' else [])
    assert req.extra['tool_mode']['effective'] == mode
    schema = req.structured_model.openai_response_format(
        exclude_fields=req.capabilities['structured_response_profile'].excluded_fields)['json_schema']['schema']
    assert ('tool_call' in schema['properties']) is (mode == 'schema')
    model.close()


@pytest.mark.parametrize('cancel_stage', ['none', 'before', 'after'])
def test_native_followup_executes_once_and_preserves_call_and_result(cancel_stage):
    from controllers.model_controller import ModelController
    from core.request_policy import RequestPolicy
    from schemas.structured_response import StructuredResponse, ToolCall
    from core.cancellation import CancellationToken, OperationCancelledError
    cancellation = CancellationToken()
    if cancel_stage == 'before':
        cancellation.cancel()
    executions, followups = [], []
    def run(name, args, **kwargs):
        executions.append((name, args))
        if cancel_stage == 'after':
            cancellation.cancel()
        return '42'
    def generate(messages, **kwargs):
        followups.append((messages, kwargs))
        return LLMResponse(text='{"segments":[{"text":"done"}]}')
    harness = SimpleNamespace(settings=SimpleNamespace(get=lambda key, default=None: default),
        event_bus=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
        model=SimpleNamespace(tool_manager=SimpleNamespace(set_char_context=lambda _: None, run=run), generate=generate),
        _build_usage_snapshot=lambda *_args, **_kwargs: None,
        _split_response_thinking=lambda response: (response.text, ''),
        _process_structured_output=lambda **kwargs: kwargs)
    kwargs = dict(
        structured=StructuredResponse(segments=[], tool_call=ToolCall(name='calculator', args={'value': 41})),
        visible_raw='{"segments":[]}', think_text='', usage=None, response_model='m', response_provider='common',
        pricing_info=None, char=object(), char_id='Crazy', char_name='Crazy', origin_message_id=None,
        capabilities={'structured_response_profile': profile()}, policy=RequestPolicy(write_to_history=False),
        sender='Player', participants=[], user_input='calculate', image_data=[], image_source='', req_id='r',
        task_uid='t', event_type='chat', combined_messages=[{'role': 'user', 'content': 'calculate'}],
        preset_id=None, enabled_tools=['calculator'], tool_depth=0,
        request_cancellation=cancellation,
        native_tool_call={'name': 'calculator', 'arguments': {'value': 41}, 'id': 'call_real',
                          'assistant_text': None, 'responses_output': []})
    if cancel_stage != 'none':
        with pytest.raises(OperationCancelledError):
            ModelController._handle_tool_call(harness, **kwargs)
        assert len(executions) == (0 if cancel_stage == 'before' else 1)
        assert followups == []
        return
    result = ModelController._handle_tool_call(harness, **kwargs)
    assert executions == [('calculator', {'value': 41})]
    messages = followups[0][0]
    assert messages[-2]['tool_calls'][0]['id'] == 'call_real'
    assert messages[-1] == {'role': 'tool', 'tool_call_id': 'call_real', 'content': '42'}
    assert result['tool_depth'] == 1
    assert followups[0][1]['request_options_override']['cancellation'] is cancellation


def test_raw_responses_history_keeps_encrypted_reasoning_and_call():
    from services.native_tool_calls import bridge_native_tool_response, native_tool_followup_messages
    response = native_response()
    output = [{'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'cipher', 'summary': []},
              {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_real',
               'name': 'calculator', 'arguments': '{"value":41}'}]
    response.raw = {'output': output}
    response.protocol_history = {'openai_responses': {'output': output}}
    bridge_native_tool_response(response, request())
    followup = native_tool_followup_messages(response.raw['native_tool_call'], '42')
    assert response.protocol_history['openai_responses']['output'] == output
    assert followup[0]['protocol_history']['openai_responses']['output'] == output
    assert followup[1]['tool_call_id'] == 'call_real'
    followup[0]['protocol_history']['openai_responses']['output'][0]['encrypted_content'] = 'changed'
    assert response.protocol_history['openai_responses']['output'][0]['encrypted_content'] == 'cipher'


def test_native_bridge_preserves_sparse_changes():
    from services.native_tool_calls import bridge_native_tool_response
    from utils.structured_response_parser import parse_structured_response_with_meta
    from schemas.structured_response import ResponseSegment
    req = request()
    req.capabilities['structured_response_profile'] = profile(sparse_enabled=True)
    segment = ResponseSegment(text='Checking').model_dump()
    for name in req.capabilities['structured_response_profile'].excluded_segment_fields:
        segment.pop(name, None)
    response = native_response(json.dumps({'segments': [segment], 'changes': [
        {'type': 'attitude_change', 'value': 2}
    ]}))
    bridge_native_tool_response(response, req)
    data = json.loads(response.text)
    assert data['segments'][0]['text'] == 'Checking'
    assert data['attitude_change'] == 2
    parsed = parse_structured_response_with_meta(response.text).response
    assert parsed.tool_call.args == {'value': 41}


def test_tool_policy_does_not_advertise_without_authoritative_profile():
    from services.native_tool_calls import configure_native_tools
    req = request()
    req.capabilities = {'tools_native': True}
    configure_native_tools(req, {}, None)
    assert not req.tools_on
    assert req.tools_payload is None


def test_exhausted_profile_does_not_advertise_native_tools():
    from services.native_tool_calls import configure_native_tools
    req = request()
    req.dialect_id = 'openai_responses'
    req.capabilities['tools_native'] = True
    req.capabilities['structured_response_profile'] = profile(tool_depth=2)
    manager = SimpleNamespace(_filtered_schema=lambda _: pytest.fail('exhausted tools must not load schemas'))
    configure_native_tools(req, {}, manager)
    assert not req.tools_on
    assert req.depth == 2


def test_chat_model_bridges_tool_only_response(monkeypatch):
    import handlers.chat_handler as module
    from managers.api_preset_resolver import PresetSettings
    preset = PresetSettings(protocol_id='test', dialect_id='openai_responses', provider_name='responses',
        headers={}, transforms=[], capabilities={'structured_output': True, 'tools_native': True},
        api_key='key', api_url='https://example.test', api_model='m', preset_name='test', reserve_keys=[])
    monkeypatch.setattr(module, 'ApiPresetResolver', lambda **_: SimpleNamespace(resolve=lambda *_: preset))
    monkeypatch.setattr(module, '_save_last_request_context', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, '_save_last_response_context', lambda *_args, **_kwargs: None)
    model = module.ChatModel(SimpleNamespace(get=lambda key, default=None: default))
    def run(**kwargs):
        req = kwargs['build_request'](preset, 'm')
        assert req.tools_on
        return native_response()
    model.request_runner.run = run
    response = model.generate([], capabilities_override={'structured_response_profile': profile()})
    assert response is not None
    assert json.loads(response.text)['tool_call']['name'] == 'calculator'
    assert response.raw['native_tool_call']['id'] == 'call_real'
    model.close()


def test_schema_fallback_restores_profile_for_retry_and_does_not_mutate_input():
    from dataclasses import replace
    from services.native_tool_calls import configure_native_tools
    req = request()
    req.dialect_id = 'gemini_generate_content'
    original = replace(profile(), excluded_fields=tuple(sorted(set(profile().excluded_fields) | {'tool_call'})))
    req.capabilities['structured_response_profile'] = original
    messages = [{'role': 'user', 'content': 'calculate'}]
    req.messages = messages
    manager = SimpleNamespace(_filtered_schema=lambda _: [{'name': 'calculator', 'parameters': {}}])
    configure_native_tools(req, {}, manager)
    assert req.tools_mode == 'schema'
    assert 'tool_call' not in req.capabilities['structured_response_profile'].excluded_fields
    assert 'tool_call' in original.excluded_fields
    assert len(req.messages) == 2
    assert len(messages) == 1


def test_bridge_rejects_replayed_native_call_id():
    from services.native_tool_calls import bridge_native_tool_response
    req = request()
    req.messages = [{'role': 'tool', 'tool_call_id': 'call_real', 'content': '42'}]
    with pytest.raises(ValueError, match='already executed'):
        bridge_native_tool_response(native_response(), req)


@pytest.mark.parametrize('sparse', [False, True])
def test_native_mode_rejects_schema_only_call(sparse):
    from services.native_tool_calls import bridge_native_tool_response
    data = {'segments': [], 'changes': [{'type': 'tool_call', 'name': 'calculator', 'args': '{}'}]} if sparse else {
        'segments': [], 'tool_call': {'name': 'calculator', 'args': {}}}
    with pytest.raises(ValueError, match='Schema'):
        bridge_native_tool_response(LLMResponse(text=json.dumps(data)), request())


@pytest.mark.parametrize('stream', [False, True])
def test_followup_preserves_original_chat_tool_extensions(stream):
    from services.native_tool_calls import bridge_native_tool_response, native_tool_followup_messages
    from handlers.llm_providers.protocols.registry import adapter_for
    original = {'id': 'call_real', 'type': 'function', 'index': 0,
                'function': {'name': 'calculator', 'arguments': '{"value":41}'},
                'extra_content': {'google': {'thought_signature': 'opaque-signature'}}}
    req = request()
    req.stream = stream
    adapter = adapter_for('openai_chat_completions')
    if stream:
        response = adapter.consume_stream(req, [{'choices': [{'delta': {'tool_calls': [original]},
                                                             'finish_reason': 'tool_calls'}]}])
    else:
        response = adapter.decode(req, {'choices': [{'message': {'tool_calls': [original]},
                                                    'finish_reason': 'tool_calls'}]})
    bridge_native_tool_response(response, req)
    req.messages = native_tool_followup_messages(response.raw['native_tool_call'], '42')
    replay = adapter.encode(req, wire_stream=False)['messages'][0]['tool_calls'][0]
    assert replay == {key: value for key, value in original.items() if key != 'index'}
    replay['extra_content']['google']['thought_signature'] = 'changed'
    assert original['extra_content']['google']['thought_signature'] == 'opaque-signature'


@pytest.mark.parametrize('invalid', [None, 'disabled', 'empty_allowlist', 'depth', 'profile_depth',
                                    'schema_mode', 'missing_profile', 'schema_only', 'mismatched_args'])
def test_controller_routes_bridged_native_call_after_profile_sanitization(invalid):
    from controllers.model_controller import ModelController
    from core.request_policy import RequestPolicy
    from dataclasses import replace
    routed = []
    native_profile = replace(profile(), excluded_fields=tuple(sorted(set(profile().excluded_fields) | {'tool_call'})))
    harness = SimpleNamespace(settings=SimpleNamespace(get=lambda key, default=None: default),
        _handle_tool_call=lambda **kwargs: routed.append(kwargs) or 'handled')
    char = SimpleNamespace(process_structured_response=lambda *_args, **_kwargs: None)
    call = {'name': 'calculator', 'arguments': {'value': 41}, 'id': 'call_real',
            'assistant_text': None, 'responses_output': []}
    caps = {'structured_response_profile': native_profile, 'tool_mode': {'effective': 'native'}}
    tools_on, enabled_tools, depth = True, ['calculator'], 0
    if invalid == 'disabled':
        caps['structured_response_profile'] = replace(native_profile, tools_enabled=False)
    elif invalid == 'empty_allowlist':
        enabled_tools = []
    elif invalid == 'depth':
        depth = 2
    elif invalid == 'profile_depth':
        caps['structured_response_profile'] = replace(native_profile, tool_depth=2)
    elif invalid == 'schema_mode':
        caps['tool_mode'] = {'effective': 'schema'}
    elif invalid == 'missing_profile':
        caps.pop('structured_response_profile')
    elif invalid == 'schema_only':
        call = None
    elif invalid == 'mismatched_args':
        call['arguments'] = {'value': 9}
    result = ModelController._process_structured_output(harness,
        visible_raw='{"segments":[],"tool_call":{"name":"calculator","args":{"value":41}}}',
        think_text='', usage=None, response_model='m', response_provider='common', pricing_info=None,
        char=char, char_id='Crazy', char_name='Crazy', origin_message_id=None,
        capabilities=caps, policy=RequestPolicy(write_to_history=False),
        sender='Player', participants=[], user_input='calculate', image_data=[], image_source='', req_id='r',
        task_uid='t', event_type='chat', combined_messages=[], preset_id=None,
        tools_on=tools_on, enabled_tools=enabled_tools, tool_depth=depth, native_tool_call=call)
    if invalid:
        assert result.error_details['code'] == 'native_tool_call_invalid'
        assert routed == []
        return
    assert result == 'handled'
    assert len(routed) == 1
    assert routed[0]['structured'].tool_call.args == {'value': 41}
    assert routed[0]['native_tool_call']['id'] == 'call_real'


@pytest.mark.parametrize('dialect', ['chat', 'responses'])
@pytest.mark.parametrize('followup_fails', [False, True])
def test_native_exchange_persists_reloads_and_projects_for_subsequent_turn(monkeypatch, dialect, followup_fails):
    import sqlite3
    from controllers.model_controller import ModelController
    from controllers.history_controller import HistoryController
    from managers.history_manager import HistoryManager
    from managers.database_manager import DatabaseManager
    from managers.conversation_event_writer import ConversationEventWriter
    from core.request_policy import RequestPolicy
    from schemas.structured_response import StructuredResponse, ToolCall
    connection = sqlite3.connect(':memory:', check_same_thread=False)
    class Connection:
        def __getattr__(self, name):
            return getattr(connection, name)
        def close(self):
            pass
    monkeypatch.setattr(DatabaseManager, 'get_connection', lambda _: Connection())
    monkeypatch.setattr(DatabaseManager, '_instance', None)
    monkeypatch.setattr(DatabaseManager, '_path_override', None)
    monkeypatch.setattr(HistoryManager, '_schedule_history_embeddings', lambda *_: None)
    manager = HistoryManager(storage_name='Crazy', character_id='Crazy')
    character = SimpleNamespace(char_id='Crazy', history_manager=manager, add_messages_to_history=manager.add_messages)
    writer = ConversationEventWriter(lambda cid: character if cid == 'Crazy' else None)
    settings = SimpleNamespace(get=lambda key, default=None: default)
    calls = []
    harness = SimpleNamespace(settings=settings, event_writer=writer,
        _publish_history_commit=lambda *_args, **_kwargs: None,
        event_bus=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
        model=SimpleNamespace(tool_manager=SimpleNamespace(set_char_context=lambda _: None,
            run=lambda *args, **kwargs: calls.append(args) or '42'),
            generate=lambda *_args, **_kwargs: None if followup_fails else LLMResponse(text='{"segments":[{"text":"done"}]}')),
        _build_usage_snapshot=lambda *_args, **_kwargs: None,
        _split_response_thinking=lambda response: (response.text, ''),
        _process_structured_output=lambda **kwargs: kwargs)
    call = {'name': 'calculator', 'arguments': {'value': 41}, 'id': 'call_real', 'assistant_text': None,
            'responses_output': [{'type': 'reasoning', 'id': 'rs', 'encrypted_content': 'cipher', 'summary': []}]}
    if dialect == 'chat':
        call['responses_output'] = []
        call['chat_tool_call'] = {'id': 'call_real', 'type': 'function',
            'function': {'name': 'calculator', 'arguments': '{"value":41}'},
            'extra_content': {'google': {'thought_signature': 'opaque-signature'}}}
    try:
        ModelController._handle_tool_call(harness,
            structured=StructuredResponse(segments=[], tool_call=ToolCall(name='calculator', args={'value': 41})),
            visible_raw='{"segments":[]}', think_text='', usage=None, response_model='m', response_provider='common',
            pricing_info=None, char=character, char_id='Crazy', char_name='Crazy', origin_message_id=None,
            capabilities={'structured_response_profile': profile(), 'tool_mode': {'effective': 'native'}},
            policy=RequestPolicy(write_to_history=True), sender='Player', participants=[], user_input='calculate',
            image_data=[], image_source='', req_id='r', task_uid='t', event_type='chat',
            combined_messages=[{'role': 'user', 'content': 'calculate'}], preset_id=None,
            enabled_tools=['calculator'], tool_depth=0, native_tool_call=call)
        reloaded = HistoryManager(storage_name='Crazy', character_id='Crazy').load_history()['messages']
        assistant = next(message for message in reloaded if message['role'] == 'assistant')
        exchange = assistant['structured_data']['native_tool_history']
        assert exchange[0]['tool_calls'][0]['id'] == 'call_real'
        if dialect == 'responses':
            assert exchange[0]['protocol_history']['openai_responses']['output'][0]['encrypted_content'] == 'cipher'
        else:
            assert exchange[0]['protocol_history']['openai_chat_completions']['tool_calls'][0]['extra_content']['google']['thought_signature'] == 'opaque-signature'
        assert exchange[1] == {'role': 'tool', 'tool_call_id': 'call_real', 'content': '42'}
        assert assistant['message_id'] != 'out:t'
        projector = HistoryController.__new__(HistoryController)
        projector._get_setting = settings.get
        projected = projector._sanitize_history_for_llm(character, reloaded)
        assert projected[-2:] == exchange
        assert calls == [('calculator', {'value': 41})]
        writer.write_turn(responder_character_id='Crazy', sender='Player', participants=[], user_input='',
            image_data=[], req_id='r', origin_message_id=None, assistant_text='done', assistant_target='Player',
            event_type='chat', task_uid='t')
        rows = HistoryManager(storage_name='Crazy', character_id='Crazy').load_history()['messages']
        assert len([row for row in rows if row['role'] == 'assistant']) == 2
        assert rows[-1]['message_id'] == 'out:t'
        assert rows[-2]['structured_data']['native_tool_history'] == exchange
    finally:
        connection.close()


@pytest.mark.parametrize('case', ['wrong_id', 'orphan', 'foreign_owner', 'not_native'])
def test_history_projection_does_not_replay_invalid_or_foreign_exchanges(case):
    from controllers.history_controller import HistoryController
    from services.native_tool_calls import native_tool_followup_messages
    exchange = native_tool_followup_messages({'name': 'calculator', 'arguments': {}, 'id': 'c'}, '42')
    row = {'role': 'assistant', 'content': 'Checking', 'structured_data': {'native_tool_history': exchange}}
    if case == 'wrong_id':
        exchange[1]['tool_call_id'] = 'other'
    elif case == 'orphan':
        exchange.pop()
    elif case == 'foreign_owner':
        row['role'] = 'user'
        row['speaker'] = 'OtherMita'
    else:
        row['structured_data'] = {'tool_call': {'name': 'calculator', 'args': {}}}
    projector = HistoryController.__new__(HistoryController)
    projector._get_setting = lambda key, default=None: default
    result = projector._sanitize_history_for_llm(SimpleNamespace(char_id='Crazy'), [row])
    assert len(result) == 1
    assert 'tool_calls' not in result[0]
