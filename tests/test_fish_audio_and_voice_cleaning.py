import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import unittest
from utils import (
    extract_clean_dialogue_text,
    extract_dialogue_payload,
    process_text_to_voice,
    clean_dialogue_for_subtitles,
)
from handlers.fish_audio_handler import (
    format_text_with_fish_emotions,
    clean_fish_audio_text,
    strip_fish_tags,
)
from controllers.chat_controller import ChatController, StructuredJsonStreamFilter

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

    def test_user_reported_hybrid_preamble_and_truncated_json(self):
        bug_report = """[suspicion] «Привет»? Серьёзно? Тринадцать минут молчания, а потом — как ни в чём не бывало? [sarcastic] А манекены, которые я выгрузила по твоей просьбе, — это мы просто опустим?

{
  "segments": [
    {
      "text": "«Привет»? Серьёзно? [sarcastic] Тринадцать минут молчания, а потом — раз! — и ты как ни в чём не бывало.",
      "emotions": ["suspicion"],
      "animations": ["Mita Oi"]
    },
    {
      "text": "Ладно... раз уж ты внезапно стал вежливым — садись на диван. Только помни: если увижу субтитры — они вернутся~",
      "emotions": ["smilestrange"],
      "idle_animations": ["Mita Hands Down Idle"],
      "hint": "Сядь на диван и веди себя хорошо"
    }
  ],
  "attitude_change": 0.5,
  "boredom_change": -"""

        # 1. extract_clean_dialogue_text must not leak JSON keys or brackets
        clean_speech = extract_clean_dialogue_text(bug_report)
        self.assertNotIn("segments", clean_speech)
        self.assertNotIn("idle_animations", clean_speech)
        self.assertNotIn("boredom_change", clean_speech)
        self.assertNotIn("attitude_change", clean_speech)
        self.assertNotIn("hint", clean_speech)
        self.assertNotIn("{", clean_speech)
        self.assertNotIn("}", clean_speech)
        self.assertNotIn('"', clean_speech)
        self.assertIn("Тринадцать минут молчания", clean_speech)
        self.assertIn("садись на диван", clean_speech)

        # 2. clean_fish_audio_text must produce spoken text without JSON syntax
        voiced = clean_fish_audio_text(bug_report, model="s2.1-pro")
        self.assertNotIn("segments", voiced)
        self.assertNotIn("text :", voiced)
        self.assertNotIn("hint :", voiced)
        self.assertNotIn("idle_", voiced)
        self.assertNotIn("boredom_change", voiced)
        self.assertNotIn("{", voiced)
        self.assertNotIn("}", voiced)
        self.assertIn("[sarcastic]", voiced)
        self.assertIn("садись на диван", voiced)

        # 3. Structured parser must successfully repair and extract segments
        from utils.structured_response_parser import parse_structured_response_with_meta
        outcome = parse_structured_response_with_meta(bug_report)
        self.assertEqual(len(outcome.response.segments), 2)
        self.assertEqual(outcome.response.attitude_change, 0.5)

    def test_scrambled_image_description_and_memory_coercion(self):
        from schemas.structured_response import build_structured_response_model
        from utils.structured_response_parser import parse_structured_response
        custom_params = [
            {
                "name": "Love",
                "change_command": "love_change",
                "type": "float",
                "change_min": -5,
                "change_max": 5,
                "required": True,
                "initial": 25,
            }
        ]
        model_cls = build_structured_response_model(custom_params)
        raw_json = (
            '{"image_description":[{"text":"«Малышка»? [sarcastic] Два часа пропал, а вернулся — сразу с ласками, будто ничего не было.",'
            '"target":null,"hint":"Просто ответь Мите нормально"},'
            '{"text":"Ладно... [softly] раз уж ты вернулся, садись на диван."}],'
            '"segments":["normal|Player returned and called Mita \'малышка\'"],'
            '"memory_add":{"love_change":0.5}}'
        )
        res = parse_structured_response(raw_json, model_cls=model_cls)
        self.assertEqual(len(res.segments), 2)
        self.assertIn("«Малышка»?", res.segments[0].text)
        self.assertEqual(res.memory_add, ["normal|Player returned and called Mita 'малышка'"])
        self.assertIsNotNone(res.custom_fields)
        self.assertEqual(res.custom_fields.love_change, 0.5)

    def test_fish_audio_emotion_tag_normalization_and_mapping(self):
        # 1. suspicion maps to doubtful
        text = "[suspicion] Ты что-то скрываешь?"
        res = clean_fish_audio_text(text, model="s2.1-pro")
        self.assertIn("[doubtful]", res)
        self.assertNotIn("[suspicion]", res)
        self.assertTrue(res.startswith("[doubtful] "))

        # 2. smileobvi maps to sarcastic, smileteeth maps to excited
        text2 = "[smileobvi] Ну конечно. [smileteeth] Ура!"
        res2 = clean_fish_audio_text(text2, model="s2.1-pro")
        self.assertIn("[sarcastic]", res2)
        self.assertIn("[excited]", res2)

        # 3. Russian tags map to official Fish Audio tags
        text3 = "[сарказм] Очень смешно. [шёпот] Слушай меня."
        res3 = clean_fish_audio_text(text3, model="s2.1-pro")
        self.assertIn("[sarcastic]", res3)
        self.assertIn("[whispering]", res3)

        # 4. Animation tags and technical tags are stripped, not voiced
        text4 = "[doubtful] «Привет» [Mita Oi] [attitude+0.5] Серьёзно?"
        res4 = clean_fish_audio_text(text4, model="s2.1-pro")
        self.assertIn("[doubtful]", res4)
        self.assertNotIn("Mita Oi", res4)
        self.assertNotIn("attitude", res4)
        self.assertNotIn("Oi", res4)

        # 5. Local TTS strips both official and mapped emotion tags
        local_text = "[sarcastic] Ну да. [suspicion] Ты уверен? [Mita Oi] Привет!"
        local_res = process_text_to_voice(local_text, allow_fish_tags=False)
        self.assertNotIn("sarcastic", local_res)
        self.assertNotIn("suspicion", local_res)
        self.assertNotIn("doubtful", local_res)
        self.assertNotIn("Mita", local_res)
        self.assertIn("Ну да", local_res)
        self.assertIn("Ты уверен", local_res)
        self.assertIn("Привет", local_res)

    def test_clean_dialogue_for_subtitles_user_reported_case(self):
        # The user's exact reported screenshot case
        text = "[soft tone] Ужин, приставка, диван — выбирай..."
        cleaned = clean_dialogue_for_subtitles(text)
        self.assertEqual(cleaned, "Ужин, приставка, диван — выбирай...")

    def test_clean_dialogue_for_subtitles_multiple_tags_and_cues(self):
        text = "[whispering] Подойди ближе... [soft tone] Не бойся, я не кусаюсь~ Ну, если сама не захочу."
        cleaned = clean_dialogue_for_subtitles(text)
        self.assertEqual(cleaned, "Подойди ближе... Не бойся, я не кусаюсь~ Ну, если сама не захочу.")

        text2 = "[sarcastic] А манекены тебе понравились? [doubtful] Ты что-то скрываешь?"
        cleaned2 = clean_dialogue_for_subtitles(text2)
        self.assertEqual(cleaned2, "А манекены тебе понравились? Ты что-то скрываешь?")

    def test_clean_dialogue_for_subtitles_strips_technical_and_animation_tags(self):
        text = "[Mita Oi] [anim: Hug] Привет! [attitude+0.5] Рада видеть!"
        cleaned = clean_dialogue_for_subtitles(text)
        self.assertEqual(cleaned, "Привет! Рада видеть!")

    def test_clean_dialogue_for_subtitles_preserves_round_parentheses_speech(self):
        text = "Я заварила чай (зеленый с мятой), будешь?"
        cleaned = clean_dialogue_for_subtitles(text)
        self.assertEqual(cleaned, "Я заварила чай (зеленый с мятой), будешь?")

        # But recognized round-parenthesis emotion tags are stripped
        text2 = "(шёпотом) Секрет..."
        cleaned2 = clean_dialogue_for_subtitles(text2)
        self.assertEqual(cleaned2, "Секрет...")

    def test_strip_fish_tags_function(self):
        raw = "[happy] Привет! [soft tone] Как дела? [Mita Wave] Помаши мне."
        stripped = strip_fish_tags(raw)
        self.assertNotIn("[happy]", stripped)
        self.assertNotIn("[soft tone]", stripped)
        self.assertNotIn("Mita Wave", stripped)
        self.assertIn("Привет!", stripped)
        self.assertIn("Как дела?", stripped)
        self.assertIn("Помаши мне.", stripped)

    def test_chat_controller_build_task_result_sanitizes_subtitles_and_segments(self):
        response_text = "[soft tone] Ужин, приставка, диван — выбирай..."
        structured_data = {
            "segments": [
                {
                    "text": "[soft tone] Ужин, приставка, диван — выбирай...",
                    "emotions": ["soft tone"],
                    "animations": ["Mita Idle"],
                    "target": "Player",
                }
            ],
            "attitude_change": 0.5,
        }
        result = ChatController._build_task_result(
            response_text,
            structured_data,
            structured_parse_level="direct",
            control_plane_trusted=True,
        )

        # 1. Subtitle response and segment text sent to Unity MUST be clean
        self.assertEqual(result["response"], "Ужин, приставка, диван — выбирай...")
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["text"], "Ужин, приставка, диван — выбирай...")
        self.assertEqual(result["segments"][0]["emotions"], ["soft tone"])
        self.assertEqual(result["segments"][0]["animations"], ["Mita Idle"])
        self.assertEqual(result["segments"][0]["target"], "Player")

        # 2. Original structured_data MUST NOT be mutated (needed intact for AudioController TTS!)
        self.assertEqual(structured_data["segments"][0]["text"], "[soft tone] Ужин, приставка, диван — выбирай...")

    def test_structured_stream_filter_filters_emotion_tags(self):
        f = StructuredJsonStreamFilter()
        payload = '{"segments": [{"text": "[soft tone] Ужин, приставка, диван..."}]}'
        out: list[tuple[str, str]] = []
        for ch in payload:
            out.extend(f.feed(ch))
        out.extend(f.flush_visible())
        content = "".join(t for c, t in out if c == "content").strip()
        self.assertNotIn("[soft tone]", content)
        self.assertIn("Ужин, приставка, диван...", content)

    def test_structured_stream_filter_preserves_non_tag_brackets(self):
        f = StructuredJsonStreamFilter()
        payload = '{"segments": [{"text": "Глава [1]: начало"}]}'
        out: list[tuple[str, str]] = []
        for ch in payload:
            out.extend(f.feed(ch))
        out.extend(f.flush_visible())
        content = "".join(t for c, t in out if c == "content").strip()
        self.assertIn("[1]", content)


if __name__ == "__main__":
    unittest.main()

