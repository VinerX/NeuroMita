from copy import deepcopy


def normalize_history_message(message: dict) -> dict:
    """Read old inline history into the protocol-scoped persistence contract."""
    result = deepcopy(message)
    history = result.get('protocol_history') or {}
    output = result.pop('responses_output', None)
    reasoning = result.pop('responses_reasoning_items', None)
    if output is not None or reasoning is not None:
        responses = history.setdefault('openai_responses', {})
        if output is not None:
            responses.setdefault('output', output)
        if reasoning is not None:
            responses.setdefault('reasoning_items', reasoning)
    if history:
        result['protocol_history'] = history
    return result


def normalize_tool_call_history(call: dict) -> dict:
    """Accept runtime tool metadata saved before protocol-scoped history."""
    history = deepcopy(call.get('protocol_history') or {})
    if call.get('responses_output'):
        history.setdefault('openai_responses', {'output': deepcopy(call['responses_output'])})
    if call.get('chat_tool_call'):
        history.setdefault('openai_chat_completions', {'tool_calls': [deepcopy(call['chat_tool_call'])]})
    return history
