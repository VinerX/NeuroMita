import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.protocols.registry import adapter_for
from services.contracts import RuntimeCapabilities
from services.structured_response_capabilities import resolve_structured_response_capabilities


@pytest.mark.parametrize("sparse", [False, True])
def test_both_dialects_use_authoritative_profile_schema(sparse):
    profile = resolve_structured_response_capabilities(settings={}, runtime=RuntimeCapabilities(),
        character=SimpleNamespace(), structured_output=True, tools_enabled=False, enabled_tools=[],
        tools_mode="off", tool_depth=0, tool_max_depth=1, images_available=False,
        has_custom_params=False, schema_reasoning=False, sparse_enabled=sparse)
    req = LLMRequest(model="m", messages=[], capabilities={"structured_output": True,
        "structured_response_profile": profile, "sparse_response": sparse})
    completions = adapter_for("openai_chat_completions").encode(req, wire_stream=False)["response_format"]["json_schema"]["schema"]
    responses = adapter_for("openai_responses").encode(req, wire_stream=False)["text"]["format"]["schema"]
    assert completions["properties"].keys() == responses["properties"].keys()
    assert "tool_call" not in responses["properties"]
    assert "reasoning" not in responses["properties"]
    if sparse:
        assert "changes" in responses["properties"]


def test_profile_intent_and_custom_field_options_reach_both_encoders():
    req = LLMRequest(model="m", messages=[], capabilities={"structured_output": True,
        "schema_intents": False, "custom_params": [{"name": "energy", "type": "float"}]})
    chat = adapter_for("openai_chat_completions").encode(req, wire_stream=False)["response_format"]["json_schema"]["schema"]
    responses = adapter_for("openai_responses").encode(req, wire_stream=False)["text"]["format"]["schema"]
    for schema in (chat, responses):
        assert schema["properties"]["custom_fields"]["anyOf"][0]["properties"]["energy"]["type"] == "number"
        assert "intents" not in schema["properties"]["segments"]["items"]["properties"]
