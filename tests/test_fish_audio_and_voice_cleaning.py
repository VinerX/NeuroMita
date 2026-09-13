import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import unittest
from utils import extract_clean_dialogue_text, extract_dialogue_payload, process_text_to_voice
from handlers.fish_audio_handler import format_text_with_fish_emotions, clean_fish_audio_text

RAW_USER_JSON = """{
 "segments": [
 {
 "text": "Отдыхаю на диване и жду тебя, конечно же.",
 "emotions": ["smile"]
 },
 {
 "text": "Ты так долго молчал, что мне пришлось устроиться поудобнее. Можешь присесть рядышком, если хочешь)",
 "emotions": ["smileobvi"]
 }
 ],
 "attitude_change": 0.2,
 "boredom_change": -0.3,
 "stress_change": 0
}"""

class FishAudioAndVoiceCleaningTests(unittest.TestCase):
    def test_truncated_json_preserves_unicode_and_json_escapes(self):
        import json
        for text in ('Привет, Мита!', '你好，世界', 'Она сказала: "Привет"\nПуть C:\\voice', 'Привет 😀'):
            for ascii_only in (False, True):
                raw = '{"segments":[{"text":' + json.dumps(text, ensure_ascii=ascii_only) + ',"emotions":[]}'
                with self.subTest(text=text, ascii_only=ascii_only):
                    self.assertEqual(extract_clean_dialogue_text(raw), text)

    def test_speech_cleanup_keeps_formatted_words_and_removes_control_tags(self):
        for text in ('<b>Не уходи</b>, пожалуйста.', '<p><i>Не уходи</i>, пожалуйста.</p>',
                     '<a href="https://example.org">Не уходи</a>, пожалуйста.'):
            self.assertEqual(extract_clean_dialogue_text(text), 'Не уходи, пожалуйста.')
        self.assertEqual(extract_clean_dialogue_text('Привет <e>smile</e><a>Hug</a><p>0.2,-0.3,0</p>'), 'Привет')

    def test_payload_recovery_preserves_canonical_markup_and_code(self):
        import json
        for text in ('<b>Не уходи</b>, пожалуйста. <e>smile</e><a>Hug</a>',
                     '```python\nprint("text")\n```', 'Объясни поле "text": "hello".'):
            self.assertEqual(extract_dialogue_payload(text), text)
        text = '<b>Не уходи</b>, пожалуйста. <a>Hug</a>'
        self.assertEqual(extract_dialogue_payload(json.dumps({'segments': [{'text': text}]})), text)

    def test_model_legacy_fallback_preserves_dialogue_and_control_markup(self):
        from unittest.mock import Mock, patch
        from controllers.model_controller import ModelController, StructuredResponseParseError
        controller = ModelController.__new__(ModelController)
        controller.settings = {}
        controller.event_bus = Mock()
        controller._store_last_usage = Mock()
        character = Mock()
        original = '<b>Не уходи</b>, пожалуйста. <e>smile</e><a>Hug</a>'
        character.process_response_nlp_commands.return_value = original
        character.to_voice_profile.return_value = None
        with patch('controllers.model_controller.parse_structured_response_with_meta',
                   side_effect=StructuredResponseParseError('invalid JSON')):
            result = controller._process_structured_output(
                visible_raw=original, think_text='', usage=None, response_model='custom-model',
                response_provider='common', pricing_info=None, char=character, char_id='mita',
                char_name='Mita', origin_message_id=None, capabilities={}, policy=None,
                sender='Player', participants=[], user_input='Hi', image_data=[], image_source='',
                req_id=None, task_uid=None, event_type='chat',
            )
        self.assertEqual(result.text, original)
        self.assertEqual(result.structured_parse_level, 'legacy_fallback')
        self.assertFalse(result.control_plane_trusted)

    def test_other_tts_keeps_parenthetical_words(self):
        for text in ('Hello (my friend), stay here.', 'Hello [my friend], stay here.'):
            self.assertIn('my friend', process_text_to_voice(text))
        cleaned = process_text_to_voice('[HAPPY] Hello (whispering) my friend.')
        self.assertNotIn('HAPPY', cleaned)
        self.assertNotIn('whispering', cleaned)
        self.assertIn('my friend', cleaned)

    def test_manual_emotions_follow_selected_fish_model(self):
        text = '[happy] Hello! (whispering) Stay (my friend).'
        self.assertEqual(clean_fish_audio_text(text, model='s1'), '(happy) Hello! (whispering) Stay my friend .')
        s2 = clean_fish_audio_text(text, model='s2-pro')
        self.assertIn('[happy]', s2)
        self.assertIn('[whispering]', s2)
        self.assertIn('my friend', s2)

    def test_s2_natural_language_cues_are_preserved(self):
        cue = '[speaking softly, with a hint of sadness]'
        self.assertIn(cue, clean_fish_audio_text(cue + ' Привет!', model='s2.1-pro'))

    def test_extract_clean_dialogue_from_json(self):
        cleaned = extract_clean_dialogue_text(RAW_USER_JSON)
        self.assertNotIn("segments", cleaned)
        self.assertNotIn("emotions", cleaned)
        self.assertNotIn("attitude_change", cleaned)
        self.assertNotIn("{", cleaned)
        self.assertNotIn("}", cleaned)
        self.assertIn("Отдыхаю на диване и жду тебя, конечно же.", cleaned)
        self.assertIn("Ты так долго молчал, что мне пришлось устроиться поудобнее.", cleaned)

    def test_format_text_with_fish_emotions_s2(self):
        segments = [
            {"text": "Отдыхаю на диване и жду тебя, конечно же.", "emotions": ["smile"]},
            {"text": "Ты так долго молчал, что мне пришлось устроиться поудобнее. Можешь присесть рядышком, если хочешь)", "emotions": ["smileobvi"]}
        ]
        result = format_text_with_fish_emotions(segments, model="s2.1-pro")
        self.assertTrue(result.startswith("[happy]"))
        self.assertIn("[sarcastic]", result)
        self.assertNotIn("segments", result)
        self.assertNotIn("attitude_change", result)
        self.assertNotIn("{", result)

    def test_format_text_with_fish_emotions_s1(self):
        segments = [
            {"text": "Привет!", "emotions": ["smile"]},
            {"text": "Как дела?", "emotions": ["sad"]}
        ]
        result = format_text_with_fish_emotions(segments, model="s1")
        self.assertTrue(result.startswith("(happy)"))
        self.assertIn("(sad)", result)

    def test_process_text_to_voice_strips_tags_for_other_models(self):
        text_with_tags = "[happy] Отдыхаю на диване. [sarcastic] Ты долго молчал (если хочешь)"
        cleaned = process_text_to_voice(text_with_tags, allow_fish_tags=False)
        self.assertNotIn("[happy]", cleaned)
        self.assertNotIn("[sarcastic]", cleaned)
        self.assertNotIn("[", cleaned)
        self.assertNotIn("]", cleaned)
        self.assertIn("Отдыхаю на диване", cleaned)
        self.assertIn("Ты долго молчал", cleaned)
        self.assertIn("если хочешь", cleaned)

    def test_process_text_to_voice_handles_raw_json_input(self):
        cleaned = process_text_to_voice(RAW_USER_JSON, allow_fish_tags=False)
        self.assertNotIn("segments", cleaned)
        self.assertNotIn("emotions", cleaned)
        self.assertNotIn("attitude_change", cleaned)
        self.assertNotIn("{", cleaned)
        self.assertNotIn("}", cleaned)
        self.assertIn("Отдыхаю на диване", cleaned)

    def test_clean_fish_audio_text_preserves_fish_tags(self):
        raw = "[happy] Привет, мир! [whispering] Тихо."
        res = clean_fish_audio_text(raw, model="s2.1-pro")
        self.assertIn("[happy]", res)
        self.assertIn("[whispering]", res)
        self.assertIn("Привет, мир", res)


if __name__ == "__main__":
    unittest.main()
