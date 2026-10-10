from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from schemas.structured_response import StructuredResponse, build_structured_response_model
from schemas.sparse_structured_response import build_sparse_response_model, normalize_sparse_response
from services.contracts import RuntimeCapabilities
from services.structured_response_capabilities import resolve_structured_response_capabilities
from utils.structured_response_parser import parse_structured_response_with_meta, StructuredResponseParseError


def profile(*, sparse_enabled=True, **settings):
    return resolve_structured_response_capabilities(
        settings=settings, runtime=RuntimeCapabilities(connected=True, remote_only=False),
        character=SimpleNamespace(secret_capable=False, secret_revealed=False),
        structured_output=True, tools_enabled=True, enabled_tools=("calculator",),
        tools_mode="schema", tool_depth=0, tool_max_depth=2, images_available=True,
        has_custom_params=False, schema_reasoning=False,
        sparse_enabled=sparse_enabled,
    ).with_prompt_intents(True)


def segment_variants(schema):
    items = schema["properties"]["segments"]["items"]
    return items.get("anyOf", [items])


def complete_segment(text, *, variant="full", **values):
    from schemas.structured_response import ResponseSegment
    defaults = ResponseSegment(text=text).model_dump()
    defaults.update(values)
    names = {"text", "emotions", "animations", "idle_animations", "face_params"}
    if variant == "action":
        names |= {"commands", "intents", "target"}
    elif variant == "full":
        names = set(defaults) - set(profile().excluded_segment_fields)
    return {name: value for name, value in defaults.items() if name in names}


def test_all_wire_model_fields_are_required_even_without_a_profile():
    from typing import get_args
    from pydantic import BaseModel

    def check(annotation):
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            for field in annotation.model_fields.values():
                assert field.is_required(), annotation.__name__
                check(field.annotation)
        else:
            for arg in get_args(annotation):
                check(arg)

    check(build_sparse_response_model(StructuredResponse, profile()))
    check(build_sparse_response_model(StructuredResponse))


@pytest.mark.parametrize("segment", [
    {"text": "Hi", "emotions": ["happy"]},
    {"text": "Hi", "commands": ["camera_snapshot"]},
    {"text": "Hi", "clothes": ["outfit"]},
])
def test_incomplete_segment_variants_are_rejected(segment):
    with pytest.raises(StructuredResponseParseError) as exc:
        parse_structured_response_with_meta(json.dumps({"segments": [segment], "changes": []}), profile=profile())
    assert exc.value.code == "structured_sparse_invalid"


def test_missing_variant_fields_get_defaults_only_in_internal_response():
    normalized = normalize_sparse_response({"segments": [{"text": "Hi"}], "changes": []}, profile=profile())
    assert normalized["segments"] == [{"text": "Hi"}]
    assert "attitude_change" not in normalized
    response = StructuredResponse.model_validate(normalized)
    assert response.segments[0].emotions == []
    assert response.segments[0].commands == []
    assert response.segments[0].target is None
    assert response.attitude_change == 0


def test_segment_schema_has_four_nested_variants_for_common_combinations():
    from schemas.structured_response import ResponseSegment
    caps = profile()
    schema = build_sparse_response_model(StructuredResponse, caps).json_schema_dict()
    variants = segment_variants(schema)
    assert len(variants) == 4
    expression = {"text", "emotions", "animations", "idle_animations", "face_params"}
    actions = expression | {"commands", "intents", "target"}
    assert [set(v["properties"]) for v in variants] == [
        {"text"}, expression, actions,
        set(ResponseSegment.model_fields) - set(caps.excluded_segment_fields),
    ]
    assert "anyOf" not in schema
    for variant in variants:
        assert set(variant["required"]) == set(variant["properties"])
        assert variant["additionalProperties"] is False


def test_segment_variants_deduplicate_after_capability_filtering():
    from dataclasses import replace
    from schemas.structured_response import ResponseSegment
    caps = replace(profile(), excluded_segment_fields=tuple(set(ResponseSegment.model_fields) - {"text"}))
    schema = build_sparse_response_model(StructuredResponse, caps).json_schema_dict()
    assert [set(v["properties"]) for v in segment_variants(schema)] == [{"text"}]


def test_mixed_segment_variants_keep_actions_and_full_fallback():
    data = {"segments": [
        {"text": "Neutral"},
        {"text": "Expressive", "emotions": ["happy"], "animations": ["wave"],
         "idle_animations": [], "face_params": ["smile"]},
        {"text": "Action", "emotions": [], "animations": [], "idle_animations": [], "face_params": [],
         "commands": ["camera_snapshot"], "intents": [{"type": "inventory.collect", "payload": '{"object":"Cat"}'}], "target": "Kind"},
        complete_segment("Rare", clothes=["outfit"], music=["Calm"], allow_sleep=False),
    ], "changes": []}
    outcome = parse_structured_response_with_meta(json.dumps(data), profile=profile())
    assert outcome.control_plane_trusted
    segments = outcome.response.segments
    assert segments[0].commands == []
    assert segments[1].face_params == ["smile"]
    assert segments[2].target == "Kind"
    assert segments[2].commands == ["camera_snapshot"]
    assert segments[2].intents[0].payload == {"object": "Cat"}
    assert segments[3].clothes == ["outfit"]
    assert segments[3].music == ["Calm"]
    assert segments[3].allow_sleep is False


def test_responses_adapter_preserves_nested_segment_anyof():
    from handlers.llm_providers.base import LLMRequest
    from handlers.llm_providers.chatgpt_plan_protocol import ResponsesInferenceAdapter
    caps = profile()
    wire = build_sparse_response_model(StructuredResponse, caps)
    req = LLMRequest(model="test", messages=[], structured_model=wire,
        capabilities={"structured_output": True, "structured_response_profile": caps})
    fmt = ResponsesInferenceAdapter().build(req)["text"]["format"]
    assert fmt["strict"] is True
    assert fmt["schema"] == wire.json_schema_dict()
    assert len(segment_variants(fmt["schema"])) == 4


def test_neutral_reply_has_only_two_root_fields_and_normalizes_defaults():
    caps = profile()
    wire = build_sparse_response_model(StructuredResponse, caps)
    schema = wire.openai_response_format()["json_schema"]
    assert schema["strict"] is True
    assert set(schema["schema"]["properties"]) == {"segments", "changes"}
    segment_fields = set(segment_variants(schema["schema"])[-1]["properties"])
    assert {"text", "commands", "intents", "target"} <= segment_fields
    outcome = parse_structured_response_with_meta(
        '{"segments":[{"text":"Hello"}],"changes":[]}', profile=caps,
    )
    assert outcome.control_plane_trusted
    assert outcome.response.full_text() == "Hello"
    assert outcome.response.attitude_change == 0
    assert outcome.response.memory_add is None


def test_changes_preserve_segment_positions_lists_and_memory_semantics():
    data = {"segments": [
        complete_segment("First", music=["Calm"]),
        complete_segment("Second", variant="action", commands=["camera_snapshot"], target="Kind",
            intents=[{"type": "inventory.collect", "payload": '{"object":"Cat"}'}]),
    ], "changes": [
        {"type": "memory_add", "value": "island:language|Русский"},
        {"type": "memory_add", "value": "normal|Tea"},
        {"type": "attitude_change", "value": 1.5},
    ]}
    response = StructuredResponse.model_validate(normalize_sparse_response(data, StructuredResponse, profile()))
    assert response.segments[0].commands == []
    assert response.segments[1].commands == ["camera_snapshot"]
    assert response.segments[1].target == "Kind"
    assert response.segments[1].intents[0].payload == {"object": "Cat"}
    assert response.memory_add == ["island:language|Русский", "normal|Tea"]
    assert response.attitude_change == 1.5


@pytest.mark.parametrize("payload", ["broken", "[]", "{\"x\":NaN}"])
def test_invalid_segment_intent_payload_is_rejected_before_execution(payload):
    data = {"segments": [complete_segment("Hi", variant="action", intents=[{"type": "inventory.collect", "payload": payload}])], "changes": []}
    with pytest.raises(StructuredResponseParseError):
        parse_structured_response_with_meta(json.dumps(data), profile=profile())


def test_changes_never_advertise_segment_fields_and_disabled_segments_stay_excluded():
    from schemas.structured_response import ResponseSegment
    caps = profile(ENABLE_GAMES=False).with_prompt_intents(False)
    wire = build_sparse_response_model(StructuredResponse, caps)
    schema = wire.json_schema_dict()
    variants = schema["properties"]["changes"]["items"]["anyOf"]
    names = {variant["properties"]["type"]["enum"][0] for variant in variants}
    assert not names & set(ResponseSegment.model_fields)
    assert all("segment" not in variant["properties"] for variant in variants)
    for variant in segment_variants(schema):
        assert not set(caps.excluded_segment_fields) & set(variant["properties"])
    with pytest.raises(ValidationError):
        wire.model_validate({"segments": [{"text": "Hi", "intents": []}], "changes": []})


def test_prompt_base_example_contains_all_strict_segment_fields():
    from services.sparse_response_prompt import render_sparse_response_contract
    caps = profile()
    wire = build_sparse_response_model(StructuredResponse, caps)
    contract = render_sparse_response_contract(caps)
    example_line = next(line for line in contract.splitlines() if line.startswith("Base example"))
    example = json.loads(example_line.split(": ", 1)[1])
    wire.model_validate(example)
    required = segment_variants(wire.json_schema_dict())[0]["required"]
    assert set(example["segments"][0]) == set(required)


def test_old_events_wrapper_is_rejected_instead_of_silently_losing_actions():
    with pytest.raises(StructuredResponseParseError):
        parse_structured_response_with_meta('{"segments":[{"text":"Hi"}],"events":[]}', profile=profile())


@pytest.mark.parametrize("change", [
    {"type": "commands", "segment": -1, "value": "x"},
    {"type": "commands", "segment": 1, "value": "x"},
    {"type": "commands", "segment": True, "value": "x"},
    {"type": "memory_add", "value": 12},
    {"type": "unknown", "value": "x"},
    {"type": "tool_call", "name": "calculator", "args": "[]"},
    {"type": "intents", "segment": 0, "intent_type": "x", "payload": "broken"},
])
def test_invalid_sparse_change_is_rejected_before_execution(change):
    raw = json.dumps({"segments": [{"text": "Hi"}], "changes": [change]})
    with pytest.raises(StructuredResponseParseError) as exc:
        parse_structured_response_with_meta(raw, profile=profile())
    assert exc.value.code == "structured_sparse_invalid"


def test_duplicates_and_mixed_formats_are_rejected():
    for data in (
        {"segments": [{"text": "Hi"}], "changes": [
            {"type": "stress_change", "value": 1}, {"type": "stress_change", "value": 2}]},
        {"segments": [{"text": "Hi"}], "changes": [{"type": "memory_add", "segment": 0, "value": "x"}]},
        {"segments": [{"text": "Hi"}], "changes": [], "memory_add": ["x"]},
    ):
        with pytest.raises((ValidationError, ValueError)):
            normalize_sparse_response(data, StructuredResponse, profile())


def test_schema_contains_only_enabled_changes_and_all_objects_are_closed():
    caps = profile(REMINDERS_ENABLED=False, ENABLE_GAMES=False)
    schema = build_sparse_response_model(StructuredResponse, caps).gemini_schema_dict()
    variants = schema["properties"]["changes"]["items"]["anyOf"]
    names = {variant["properties"]["type"]["enum"][0] for variant in variants}
    assert "memory_add" in names
    assert not names & {"entities", "relations", "reminder_add", "reminder_delete", "timer_add", "start_game", "end_game"}
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "$ref" not in node
            assert "default" not in node
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(schema)
    exhausted = build_sparse_response_model(StructuredResponse, caps.at_tool_depth(2)).gemini_schema_dict()
    assert "tool_call" not in {v["properties"]["type"]["enum"][0] for v in exhausted["properties"]["changes"]["items"]["anyOf"]}


def test_secret_and_custom_fields_keep_their_explicit_decisions_and_constraints():
    from dataclasses import replace
    caps = replace(profile(), excluded_fields=tuple(n for n in profile().excluded_fields if n not in {"secret_exposed", "custom_fields"}),
        required_fields=("secret_exposed",), has_custom_params=True)
    internal = build_structured_response_model([{"name": "trust", "type": "float", "required": True, "change_min": 0, "change_max": 10}])
    wire = build_sparse_response_model(internal, caps)
    data = {"segments": [{"text": "Hi"}], "changes": [], "secret_exposed": None, "custom_fields": {"trust": 3}}
    response = internal.model_validate(normalize_sparse_response(data, internal, caps))
    assert response.custom_fields.trust == 3
    schema = wire.openai_response_format()["json_schema"]["schema"]
    assert "secret_exposed" in schema["required"]
    assert {"type": "null"} in schema["properties"]["secret_exposed"]["anyOf"]
    with pytest.raises(ValidationError):
        wire.model_validate({k: v for k, v in data.items() if k != "secret_exposed"})
    with pytest.raises(ValidationError):
        wire.model_validate({**data, "custom_fields": {"trust": 99}})


def test_legacy_and_repaired_trust_are_preserved():
    legacy = parse_structured_response_with_meta('{"segments":[{"text":"Hi","commands":["x"]}],"attitude_change":1}')
    assert legacy.response.segments[0].commands == ["x"]
    assert legacy.control_plane_trusted
    repaired = parse_structured_response_with_meta('{"segments":[{"text":"Hi"}],"changes":[],}', profile=profile())
    assert repaired.response.full_text() == "Hi"
    assert not repaired.control_plane_trusted


def test_disabled_variant_is_rejected_and_internal_result_shape_stays_full():
    from utils.structured_response_parser import structured_response_to_result_dict
    caps = profile(REMINDERS_ENABLED=False)
    with pytest.raises(StructuredResponseParseError):
        parse_structured_response_with_meta(json.dumps({"segments": [{"text": "Hi"}], "changes": [
            {"type": "timer_add", "value": "5|Hello"}]}), profile=caps)
    response = parse_structured_response_with_meta('{"segments":[{"text":"Hi"}],"changes":[]}', profile=caps).response
    saved = structured_response_to_result_dict(response)
    assert "changes" not in saved
    assert saved["memory_add"] == []
    assert saved["attitude_change"] == 0
    assert "commands" not in saved["segments"][0]


def test_working_state_and_image_changes_normalize_to_full_models():
    caps = profile(ENABLE_WORKING_STATE=True, IMAGE_INLINE_DESCRIPTION=True)
    data = {"segments": [{"text": "Hello"}], "changes": [
        {"type": "image_description", "value": "A cat"},
        {"type": "working_state", "value": {"focus": "Tea", "situation": [], "assumptions": [], "open_loops": [], "next_steps": []}},
    ]}
    response = parse_structured_response_with_meta(json.dumps(data), profile=caps).response
    assert response.working_state.focus == "Tea"
    assert response.image_description == "A cat"


def test_sparse_contract_and_stream_filter_do_not_expose_changes_as_speech():
    from services.sparse_response_prompt import render_sparse_response_contract
    from controllers.chat_controller import StructuredJsonStreamFilter
    contract = render_sparse_response_contract(profile())
    assert '"type": "memory_add"' in contract
    assert '"type": "timer_add"' in contract
    assert '"type": "entities"' not in contract
    assert "primary conversation language" in contract
    assert "changes never contain a segment index" in contract
    assert "Segment intents: type" in contract
    state_contract = render_sparse_response_contract(profile(ENABLE_WORKING_STATE=True))
    assert '"focus"' in state_contract
    assert '"next_steps"' in state_contract
    exhausted = render_sparse_response_contract(profile().at_tool_depth(2))
    assert '"type": "tool_call"' not in exhausted
    raw = json.dumps({"segments": [{"text": "Hello"}], "changes": [{"type": "memory_add", "value": "normal|secret technical text"}]})
    stream = StructuredJsonStreamFilter()
    pieces = []
    for char in raw:
        pieces.extend(stream.feed(char))
    pieces.extend(stream.flush_visible())
    assert "".join(value for channel, value in pieces if channel == "content").strip() == "Hello"


def test_gamemaster_and_legacy_provider_selection_remain_unchanged():
    from schemas.game_master_response import GameMasterResponse
    from schemas.sparse_structured_response import provider_structured_model
    assert provider_structured_model(GameMasterResponse, {"structured_response_profile": profile()}) is GameMasterResponse
    assert provider_structured_model(StructuredResponse, {}) is StructuredResponse
    assert provider_structured_model(StructuredResponse, {"structured_response_profile": profile()}) is build_sparse_response_model(StructuredResponse, profile())


def test_openai_http_and_sdk_and_gemini_send_same_sparse_union():
    import httpx
    from handlers.llm_providers.base import LLMRequest
    from handlers.llm_providers.common_provider import CommonProvider
    from handlers.llm_providers.gemini_provider import GeminiProvider
    from handlers.llm_providers.openai_compatible import OpenAICompatibleProvider
    from unittest.mock import Mock

    caps = {"structured_output": True, "structured_response_profile": profile()}
    req = LLMRequest(model="test", messages=[], capabilities=caps, structured_model=StructuredResponse,
        api_url="https://example.test", provider_name="common")
    transport = Mock()
    http_provider = CommonProvider(http_transport=transport)
    expected = http_provider._build_payload(req, "test", [])["response_format"]
    assert expected["json_schema"]["strict"] is True
    captured = {}

    class SDK(OpenAICompatibleProvider):
        name = "mock"
        def is_applicable(self, req):
            return True
        def _get_client(self, req):
            client = Mock()
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"segments":[{"text":"Hi"}],"changes":[]}'), finish_reason="stop")], usage=None, model="test")
            client.chat.completions.create.side_effect = create
            return client

    assert SDK(http_transport=transport).generate(req).text
    assert captured["response_format"] == expected
    transport.post_json.return_value = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})
    req.provider_name = "gemini"
    GeminiProvider(http_transport=transport).generate(req)
    gemini_schema = transport.post_json.call_args.kwargs["payload"]["generationConfig"]["responseJsonSchema"]
    assert gemini_schema == expected["json_schema"]["schema"]


@pytest.mark.parametrize("support_intents", [False, True])
def test_prompt_controller_renders_sparse_contract_after_template_intent_resolution(support_intents):
    from controllers.prompt_controller import PromptController
    from DSL.dsl_engine import DslInterpreter
    from core.request_policy import RequestPolicy
    script = Path(__file__).resolve().parents[3] / "extra" / "Prompts" / "Structural" / "response_format_json.script"
    class Resolver:
        def resolve_path(self, path):
            return path
        def load_text(self, path, _context):
            return f"support_intents={support_intents}\n[<format.script>]" if path == "main_template.txt" else script.read_text(encoding="utf-8")
        def get_dirname(self, _path):
            return ""
    variables = {}
    character = SimpleNamespace(char_id="Test", base_data_path="unused", main_template_path_relative="main_template.txt",
        variables=variables, app_vars={}, custom_params=[],
        set_variable=lambda key, value: variables.update({key: value}))
    character.dsl_interpreter = DslInterpreter(character, Resolver())
    controller = PromptController()
    controller._setup_character_for_prompt = lambda *args, **kwargs: None
    controller._apply_reply_defaults = lambda *args: None
    controller._resolve_examples_profile = lambda *args: "none"
    caps = {"structured_output": True, "structured_response_profile": profile(), "structured_prompt_features": profile().prompt_features()}
    stable, volatile, _ = controller._build_system_messages(character, "chat", True, RequestPolicy(), caps)
    text = "\n".join(message["content"] for message in stable + volatile)
    assert "sparse_changes_v1" in text
    assert "All other segment fields are optional" not in text
    assert '"attitude_change": <number' not in text
    assert ('Segment intents: type' in text) == support_intents
    assert "response_sparse_format" not in variables
    assert "25-70 words total" in text
    from dataclasses import replace
    caps["structured_response_profile"] = replace(profile(), sparse_enabled=False)
    stable, _, _ = controller._build_system_messages(character, "chat", True, RequestPolicy(), caps)
    old_text = "\n".join(message["content"] for message in stable)
    assert "sparse_changes_v1" not in old_text
    assert '"attitude_change": <number' in old_text
    caps["structured_output"] = False
    stable, _, _ = controller._build_system_messages(character, "chat", True, RequestPolicy(), caps)
    assert "sparse_changes_v1" not in "\n".join(message["content"] for message in stable)


def test_reasoning_order_is_preserved_for_streaming():
    from dataclasses import replace
    caps = replace(profile(), schema_reasoning=True,
        excluded_fields=tuple(name for name in profile().excluded_fields if name != "reasoning"))
    schema = build_sparse_response_model(StructuredResponse, caps).json_schema_dict()
    assert next(iter(schema["properties"])) == "reasoning"


@pytest.mark.parametrize("provider", ["chatgpt_plan", "common", "gemini"])
@pytest.mark.parametrize("enabled", [False, True])
def test_chat_model_selects_wire_dto_before_any_provider_and_keeps_retry_snapshot(monkeypatch, provider, enabled):
    from handlers.chat_handler import ChatModel
    from schemas.sparse_structured_response import SparseStructuredResponse
    from unittest.mock import Mock
    import handlers.chat_handler as chat_module
    monkeypatch.setattr(chat_module, "_save_last_request_context", lambda *args, **kwargs: None)
    model = object.__new__(ChatModel)
    model._error_state = SimpleNamespace(last_error=None)
    from threading import Lock
    model._last_error_lock = Lock()
    model.cfg = SimpleNamespace(max_request_attempts=2, request_delay=0)
    model.cfg_loader = Mock()
    model.settings = {"SPARSE_STRUCTURED_RESPONSE": not enabled}
    model.tool_manager = None
    model._log_generation_start = lambda *args: None
    preset = SimpleNamespace(native_parameters={}, capabilities={"structured_output": True},
        api_key=None, api_url="https://example.test", protocol_id="test", dialect_id="test",
        provider_name=provider, provider_display_name=provider, headers={}, transforms=[])
    captured = []
    class Runner:
        last_error = None
        def run(self, **kwargs):
            for _ in range(2):
                captured.append(kwargs["build_request"](preset, "model"))
            return None
    model.request_runner = Runner()
    caps = profile(sparse_enabled=enabled)
    model._generate_chat_response([], capabilities_override={"structured_response_profile": caps},
        structured_model=StructuredResponse)
    assert len(captured) == 2
    for req in captured:
        assert issubclass(req.structured_model, SparseStructuredResponse) == enabled
        properties = req.structured_model.openai_response_format()["json_schema"]["schema"]["properties"]
        assert ("changes" in properties) == enabled
        assert ("attitude_change" in properties) != enabled
        assert req.capabilities["structured_response_profile"].sparse_enabled == enabled
    assert captured[0].structured_model is captured[1].structured_model
