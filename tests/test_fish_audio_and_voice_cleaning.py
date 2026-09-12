import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import unittest
from utils import extract_clean_dialogue_text, process_text_to_voice
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
