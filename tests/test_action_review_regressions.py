import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from controllers.chat_controller import ChatController, StructuredJsonStreamFilter
from controllers.prompt_controller import PromptController
from handlers.fish_audio_handler import clean_fish_audio_text, resolve_fish_tag
from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.common_provider import CommonProvider
from schemas.structured_response import StructuredResponse, build_structured_response_model
from schemas.game_master_response import GameMasterResponse
from utils import clean_dialogue_for_subtitles, extract_clean_dialogue_text
from utils.structured_response_parser import (
    parse_structured_response_with_meta, structured_response_to_result_dict,
)


class ActionReviewTests(unittest.TestCase):
    def test_malformed_metadata_preserves_actions_through_unity_packet(self):
        model = build_structured_response_model([
            {"name": "Love", "change_command": "love_change", "type": "float",
             "required": True, "change_min": -5, "change_max": 5}
        ])
        for action in (
            {"intents": [{"type": "actor.set_movement_mode", "payload": {"mode": "follow"}}]},
            {"interactions": ["Sofa center"]},
            {"intents": [{"type": "actor.sleep", "payload": {}}]},
        ):
            raw = {"segments": [{"text": "[soft tone] Ладно, иду.", **action}],
                   "secret_exposed": 0.3, "memory_add": {"love_change": 0.5}}
            outcome = parse_structured_response_with_meta(json.dumps(raw), model_cls=model)
            self.assertIsNone(outcome.response.secret_exposed)
            self.assertFalse(outcome.control_plane_trusted)
            data = structured_response_to_result_dict(outcome.response)
            before = copy.deepcopy(data)
            packet = ChatController._build_task_result(data['response'], data,
                structured_parse_level=outcome.parse_level,
                control_plane_trusted=outcome.control_plane_trusted)
            packet = json.loads(json.dumps(packet))
            for key, value in action.items():
                self.assertEqual(packet['segments'][0][key], value)
            self.assertEqual(packet['segments'][0]['text'], 'Ладно, иду.')
            self.assertEqual(before, data)

    def test_missing_required_custom_delta_defaults_without_losing_sleep(self):
        model = build_structured_response_model([
            {"name": "Love", "change_command": "love_change", "type": "float", "required": True}
        ])
        outcome = parse_structured_response_with_meta(json.dumps({"segments": [
            {"text": "Иду к кровати", "intents": [{"type": "actor.sleep"}]}]}), model_cls=model)
        self.assertEqual(outcome.response.custom_fields.love_change, 0)
        self.assertEqual(outcome.response.segments[0].intents[0].type, 'actor.sleep')

    def test_scrambled_image_field_never_replaces_existing_action(self):
        outcome = parse_structured_response_with_meta(json.dumps({
            "segments": [{"text": "Иду", "movement_modes": ["FollowPlayer"]}],
            "image_description": [{"text": "Другая реплика"}],
        }))
        self.assertEqual(outcome.response.segments[0].movement_modes, ['FollowPlayer'])

    def test_subtitles_preserve_ordinary_brackets_and_schema_words(self):
        for text in ('Жди [мой друг] (по-моему) здесь.', 'The word segments means parts.',
                     'Say music: jazz.', 'Глава [1]: начало'):
            self.assertEqual(clean_dialogue_for_subtitles(text), text)
            self.assertEqual(extract_clean_dialogue_text(text), text)
        self.assertEqual(resolve_fish_tag('love'), 'soft tone')
        self.assertEqual(resolve_fish_tag('long-break'), 'long-break')
        self.assertIn('[long-break]', clean_fish_audio_text('[long-break] Hello'))

    def test_unclosed_bracket_does_not_leak_between_stream_segments(self):
        stream = StructuredJsonStreamFilter()
        output = []
        for c in json.dumps({'segments': [{'text': '['}, {'text': 'hello'}]}):
            output.extend(stream.feed(c))
        output.extend(stream.flush_visible())
        self.assertEqual(''.join(t for channel, t in output if channel == 'content').strip(), '[ hello')

    def test_prompt_keeps_runtime_gate_and_action_consistency(self):
        state = {'intent_rules': 'actor.sleep: {}; actor.set_movement_mode: {"mode":"follow|stay"}'}
        self.assertIsNone(PromptController._build_unity_intent_rules_message(state, support_intents=False))
        text = PromptController._build_unity_intent_rules_message(state, support_intents=True)['content']
        self.assertIn('SAME response segment', text)
        self.assertIn('PLAYER', text)
        self.assertIn('wait for arrival', text)

    def test_streamed_schema_rejection_can_fall_back_twice(self):
        class Body(httpx.SyncByteStream):
            def __init__(self, data): self.data = data
            def __iter__(self): yield self.data
        requests = []
        def request(_url, req, payload):
            requests.append(copy.deepcopy(payload))
            if 'response_format' in payload:
                return httpx.Response(400, stream=Body(b'{"error":"response_format unsupported"}'))
            return httpx.Response(200, stream=Body(
                b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n'
                b'data: [DONE]\n\n'))
        provider = CommonProvider()
        with patch.object(provider, '_request', side_effect=request):
            response = provider.generate(LLMRequest(model='arbitrary-model', messages=[],
                api_url='https://example.org/v1', stream=True,
                capabilities={'structured_output': True}))
        self.assertEqual(response.text, 'OK')
        self.assertEqual(len(requests), 3)
        self.assertNotIn('response_format', requests[-1])

    def test_key_selection_requires_nanogpt_destination(self):
        from handlers.asr_models.nanogpt_recognizer import find_nanogpt_key_in_api_presets
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'api.json'
            path.write_text(json.dumps({'presets': {
                '10004': {'id': 10004, 'base': 10001, 'name': 'NanoGPT',
                          'url': 'https://other.example/api', 'key': 'wrong-key'},
                '2': {'url': 'https://nano-gpt.com/api/v1', 'key': 'right-key'},
            }}))
            with patch('core.app_paths.settings_path', return_value=path), patch.dict('os.environ', {
                'NANOGPT_API_KEY': '', 'NANO_GPT_API_KEY': ''}):
                self.assertEqual(find_nanogpt_key_in_api_presets(), 'right-key')

    def test_asr_auto_language_request_and_no_redirect(self):
        from handlers.asr_models.nanogpt_recognizer import request_nanogpt_transcription
        with patch('requests.post') as post:
            request_nanogpt_transcription(b'audio', api_key='test-key', model='any-asr', language='auto')
        self.assertEqual(post.call_args.args[0], 'https://nano-gpt.com/api/v1/audio/transcriptions')
        self.assertEqual(post.call_args.kwargs['data'], {'model': 'any-asr'})
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_misplaced_memory_update_delta_does_not_drop_interaction(self):
        model = build_structured_response_model([
            {'name': 'Love', 'change_command': 'love_change', 'type': 'float', 'required': True}
        ])
        outcome = parse_structured_response_with_meta(json.dumps({
            'segments': [{'text': 'Сажусь', 'interactions': ['Sofa center']}],
            'memory_update': {'love_change': -3},
        }), model_cls=model)
        self.assertEqual(outcome.response.custom_fields.love_change, -3)
        self.assertEqual(outcome.response.segments[0].interactions, ['Sofa center'])

    def test_asr_save_updates_runtime_and_reports_disk_failure(self):
        from handlers.asr_models.nanogpt_recognizer import save_nanogpt_asr_config
        with patch('services.asr_settings_service.ensure_asr_settings_service') as service, \
             patch('handlers.asr_handler.SpeechRecognition.apply_settings') as apply:
            save_nanogpt_asr_config({'api_key': 'test-key', 'model': 'any-asr'})
            self.assertEqual(apply.call_args.args[0], 'nanogpt')
            self.assertEqual(apply.call_args.args[1]['model'], 'any-asr')
            service.return_value.set_model_settings.side_effect = OSError('disk full')
            with self.assertRaises(OSError):
                save_nanogpt_asr_config({'api_key': 'test-key'})

    def test_openai_response_format_custom_fields_schema_validity(self):
        cfg = [{'name': 'Love', 'change_command': 'love_change', 'type': 'float', 'required': True}]
        model = build_structured_response_model(cfg)
        fmt = model.openai_response_format(custom_params=cfg)
        cf_schema = fmt['json_schema']['schema']['properties']['custom_fields']
        # Node with anyOf/$ref must not have conflicting outer properties
        self.assertNotIn('properties', cf_schema)
        defs = fmt['json_schema']['schema'].get('$defs', {})
        self.assertTrue(any('love_change' in d.get('properties', {}) for d in defs.values()))

    def test_gemini_proxy_schema_error_triggers_fallback(self):
        class Body(httpx.SyncByteStream):
            def __init__(self, data): self.data = data
            def __iter__(self): yield self.data
        requests = []
        def request(_url, req, payload):
            requests.append(copy.deepcopy(payload))
            if 'response_format' in payload:
                err = b'{"error":{"message":"* GenerateContentRequest.generation_config.response_schema.properties[custom_fields].properties: only allowed for OBJECT type"}}'
                return httpx.Response(400, stream=Body(err))
            return httpx.Response(200, stream=Body(
                b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":null}]}\n\n'
                b'data: [DONE]\n\n'))
        provider = CommonProvider()
        with patch.object(provider, '_request', side_effect=request):
            response = provider.generate(LLMRequest(model='gemini-3.8-flash-high', messages=[],
                api_url='http://127.0.0.1:8317/v1', stream=True,
                capabilities={'structured_output': True}))
        self.assertEqual(response.text, 'OK')
        self.assertEqual(len(requests), 3)
        self.assertNotIn('response_format', requests[-1])

    def test_openai_response_format_inlines_all_defs_for_gemini_cli_proxy(self):
        # 1. StructuredResponse has inlined segments.items without unresolvable $ref
        fmt = StructuredResponse.openai_response_format()
        schema = fmt["json_schema"]["schema"]
        seg_items = schema["properties"]["segments"]["items"]
        self.assertNotIn("$ref", seg_items)
        self.assertIn("text", seg_items["properties"])
        self.assertIn("emotions", seg_items["properties"])
        self.assertIn("intents", seg_items["properties"])
        intents_items = seg_items["properties"]["intents"]["items"]
        self.assertNotIn("$ref", intents_items)
        self.assertIn("type", intents_items["properties"])
        self.assertIn("payload", intents_items["properties"])

        # 2. Custom fields model inlines child properties into anyOf branch
        cfg = [{"name": "Love", "change_command": "love_change", "type": "float", "required": True}]
        model = build_structured_response_model(cfg)
        fmt_custom = model.openai_response_format(custom_params=cfg)
        cf_schema = fmt_custom["json_schema"]["schema"]["properties"]["custom_fields"]
        self.assertNotIn("$ref", cf_schema["anyOf"][0])
        self.assertIn("love_change", cf_schema["anyOf"][0]["properties"])

        # 3. GameMasterResponse inlines actions.items without $ref
        gm_fmt = GameMasterResponse.openai_response_format()
        gm_items = gm_fmt["json_schema"]["schema"]["properties"]["actions"]["items"]
        self.assertNotIn("$ref", gm_items)
        self.assertIn("type", gm_items["properties"])
        self.assertIn("target", gm_items["properties"])


