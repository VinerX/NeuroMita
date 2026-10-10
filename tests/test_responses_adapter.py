import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.errors import LLMProviderError
from handlers.llm_providers.protocols.responses import ResponsesAdapter, ResponsesPolicy


def request(**kwargs):
    return LLMRequest(model='m', messages=[], tools_on=True,
                      tools_payload=[{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}], **kwargs)


def call(cid='c1', iid='i1', arguments='{"q":"x"}'):
    return {'type': 'function_call', 'id': iid, 'call_id': cid, 'name': 'lookup', 'arguments': arguments}


def test_generic_encoding_and_explicit_siwc_policy():
    req = request(native_parameters={'temperature': .4, 'max_output_tokens': 100, 'store': True})
    payload = ResponsesAdapter().encode(req, wire_stream=False)
    assert payload['stream'] is False
    assert payload['temperature'] == .4
    assert payload['max_output_tokens'] == 100
    assert payload['tools'][0]['name'] == 'lookup'
    assert 'function' not in payload['tools'][0]
    siwc = ResponsesAdapter(policy=ResponsesPolicy.siwc()).encode(req, wire_stream=False)
    assert siwc['stream'] is True and siwc['store'] is False
    assert siwc['tools'][0]['name'] == 'neuromita'
    assert 'temperature' not in siwc and 'max_output_tokens' not in siwc


def test_decode_plain_text_and_all_tool_calls():
    result = ResponsesAdapter().decode(request(), {'status': 'completed', 'model': 'actual', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': 'hello'}]},
        call(), call('c2', 'i2', '{"q":"y"}'),
        {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'thought'}]},
    ], 'usage': {'input_tokens': 4, 'output_tokens': 3, 'total_tokens': 7, 'input_tokens_details': {'cached_tokens': 2}}})
    assert result.text == 'hello' and result.reasoning == 'thought'
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [('c1', 'lookup', {'q': 'x'}), ('c2', 'lookup', {'q': 'y'})]
    assert result.usage.cached_prompt_tokens == 2 and result.model == 'actual'


@pytest.mark.parametrize('payload', [
    {'status': 'failed', 'error': {'code': 'oops'}},
    {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'no'}]}]},
])
def test_terminal_failures_are_not_success(payload):
    with pytest.raises(LLMProviderError):
        ResponsesAdapter().decode(request(), payload)


def test_stream_correlates_ids_and_keeps_tools_without_terminal_output():
    events = []
    req = request(stream=True, stream_event_cb=events.append)
    result = ResponsesAdapter().consume_stream(req, [
        {'type': 'response.output_item.added', 'output_index': 0, 'item': call(arguments='')},
        {'type': 'response.function_call_arguments.delta', 'item_id': 'i1', 'delta': '{"q":'},
        {'type': 'response.function_call_arguments.delta', 'item_id': 'i1', 'delta': '"x"}'},
        {'type': 'response.function_call_arguments.done', 'item_id': 'i1', 'arguments': '{"q":"x"}'},
        {'type': 'response.output_item.done', 'output_index': 0, 'item': call()},
        {'type': 'response.completed', 'response': {'status': 'completed'}},
    ])
    assert result.tool_calls[0].id == 'c1' and result.tool_calls[0].arguments == {'q': 'x'}
    tool_events = [e for e in events if e.tool_call_id]
    assert {e.tool_call_id for e in tool_events} == {'c1'}
    assert sum(e.type.value == 'tool_call_completed' for e in tool_events) == 1


def test_final_output_authoritative_and_no_double_text():
    result = ResponsesAdapter().consume_stream(request(), [
        {'type': 'response.output_text.delta', 'delta': 'hi'},
        {'type': 'response.completed', 'response': {'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'hi'}]}, call()]}}
    ])
    assert result.text == 'hi' and len(result.tool_calls) == 1


def test_truncated_stream_and_orphan_arguments_rejected():
    with pytest.raises(LLMProviderError):
        ResponsesAdapter().consume_stream(request(), [{'type': 'response.output_text.delta', 'delta': 'partial'}])
    with pytest.raises(LLMProviderError):
        ResponsesAdapter().consume_stream(request(), [
            {'type': 'response.function_call_arguments.delta', 'item_id': 'unknown', 'delta': '{}'},
            {'type': 'response.completed', 'response': {}}])


@pytest.mark.parametrize('arguments', ['[]', 'broken'])
def test_invalid_arguments_rejected(arguments):
    with pytest.raises(ValueError):
        ResponsesAdapter().decode(request(), {'output': [call(arguments=arguments)]})


def test_legacy_wrapper_bridge_only():
    from handlers.llm_providers.chatgpt_plan_protocol import ResponsesInferenceAdapter
    req = request()
    wrapper = ResponsesInferenceAdapter()
    assert wrapper.build(req)['stream'] is True
    item = call()
    item['name'] = 'neuromita.lookup'
    assert json.loads(wrapper.normalize_output(req, {'output': [item]}, 'hello'))['tool_call']['name'] == 'lookup'
    assert wrapper.decode(req, {'output': [item]}).tool_calls[0].name == 'lookup'


def test_empty_native_parameters_do_not_import_extra():
    req = request(native_parameters={}, extra={'temperature': .9})
    assert 'temperature' not in ResponsesAdapter().encode(req, wire_stream=False)


def test_followup_preserves_raw_reasoning_and_namespace():
    reasoning = {'type': 'reasoning', 'id': 'r1', 'summary': [], 'encrypted_content': 'opaque'}
    req = request()
    req.messages = [{'role': 'assistant', 'responses_reasoning_items': [reasoning], 'tool_calls': [
        {'id': 'c1', 'function': {'name': 'lookup', 'arguments': '{"q":"x"}'}}]},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'ok'}]
    generic = ResponsesAdapter().encode(req, wire_stream=False)
    assert generic['input'][0] == reasoning and generic['input'][0] is not reasoning
    assert generic['input'][1]['name'] == 'lookup'
    siwc = ResponsesAdapter(policy=ResponsesPolicy.siwc()).encode(req, wire_stream=True)
    assert siwc['input'][0]['encrypted_content'] == 'opaque'
    assert siwc['input'][1]['name'] == 'neuromita.lookup'


def test_added_empty_message_does_not_hide_text_deltas():
    result = ResponsesAdapter().consume_stream(request(), [
        {'type': 'response.output_item.added', 'output_index': 0, 'item': {'id': 'i1', 'type': 'message', 'content': []}},
        {'type': 'response.output_text.delta', 'delta': 'hello'},
        {'type': 'response.completed', 'response': {}},
    ])
    assert result.text == 'hello'


def test_cancelled_request_never_consumes_stream():
    from handlers.llm_providers.base import RequestCancellation, RequestCancelledError
    cancellation = RequestCancellation()
    cancellation.cancel('stop')
    with pytest.raises(RequestCancelledError):
        ResponsesAdapter().consume_stream(request(extra={'_request_cancellation': cancellation}), [
            {'type': 'response.completed', 'response': {}}])


def test_stream_preserves_tools_and_reasoning_when_terminal_output_is_sparse():
    reasoning = {'type': 'reasoning', 'id': 'r1', 'summary': [], 'encrypted_content': 'encrypted'}
    result = ResponsesAdapter().consume_stream(request(), [
        {'type': 'response.output_item.done', 'output_index': 0, 'item': reasoning},
        {'type': 'response.output_item.done', 'output_index': 1, 'item': call()},
        {'type': 'response.completed', 'response': {'output': [
            {'id': 'msg', 'type': 'message', 'content': [{'type': 'output_text', 'text': 'hi'}]}]}},
    ])
    assert result.text == 'hi' and result.tool_calls[0].id == 'c1'
    assert reasoning in result.raw['output']


def test_pending_argument_deltas_do_not_duplicate_final_arguments():
    result = ResponsesAdapter().consume_stream(request(), [
        {'type': 'response.function_call_arguments.delta', 'item_id': 'i1', 'delta': '{"q":"x"}'},
        {'type': 'response.completed', 'response': {'output': [call()]}},
    ])
    assert result.tool_calls[0].arguments == {'q': 'x'}


def test_multiple_tools_interleaved_stream():
    result = ResponsesAdapter().consume_stream(request(), [
        {'type': 'response.output_item.added', 'output_index': 0, 'item': call(arguments='')},
        {'type': 'response.output_item.added', 'output_index': 1, 'item': call('c2', 'i2', '')},
        {'type': 'response.function_call_arguments.delta', 'item_id': 'i2', 'delta': '{"q":"y"}'},
        {'type': 'response.function_call_arguments.delta', 'item_id': 'i1', 'delta': '{"q":"x"}'},
        {'type': 'response.completed', 'response': {}},
    ])
    assert [(c.id, c.arguments) for c in result.tool_calls] == [('c1', {'q': 'x'}), ('c2', {'q': 'y'})]


def test_full_raw_output_history_prevents_reconstructed_duplicates():
    reasoning = {'type': 'reasoning', 'id': 'r1', 'summary': [], 'encrypted_content': 'opaque'}
    output = [reasoning, call(), {'type': 'message', 'id': 'msg', 'content': [{'type': 'output_text', 'text': 'checking'}]}]
    req = request()
    req.messages = [{'role': 'assistant', 'responses_output': output,
                     'responses_reasoning_items': [reasoning], 'content': 'checking',
                     'tool_calls': [{'id': 'c1', 'function': {'name': 'lookup', 'arguments': '{"q":"x"}'}}]},
                    {'role': 'tool', 'tool_call_id': 'c1', 'content': 'ok'}]
    encoded = ResponsesAdapter().encode(req, wire_stream=False)['input']
    assert encoded[:-1] == output
    assert encoded[0] is not reasoning and encoded[-1]['call_id'] == 'c1'


@pytest.mark.parametrize('kind', ['response.content_part.added', 'response.content_part.done'])
def test_stream_content_refusal_rejected_even_without_terminal_output(kind):
    with pytest.raises(LLMProviderError) as caught:
        ResponsesAdapter().consume_stream(request(), [
            {'type': kind, 'part': {'type': 'refusal', 'refusal': 'no'}},
            {'type': 'response.completed', 'response': {}},
        ])
    assert caught.value.code == 'responses.refusal'
