import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from handlers.asr_models.registry import engine_class, engine_ids
from handlers.asr_models.nanogpt_recognizer import NanoGPTRecognizer
from handlers.asr_handler import SpeechRecognition
from installables.catalog_manifest import CATALOG_ENTRIES


class TestNanoGPTASR(unittest.IsolatedAsyncioTestCase):
    def test_registry_registration(self):
        self.assertIn('nanogpt', engine_ids())
        cls = engine_class('nanogpt')
        self.assertIs(cls, NanoGPTRecognizer)

    def test_catalog_manifest_entry(self):
        entry = next((e for e in CATALOG_ENTRIES if e.id == 'asr:nanogpt'), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.metadata_ru.get('item_id'), 'nanogpt')
        self.assertIn('NanoGPT', entry.metadata_ru.get('title', ''))

    def test_settings_and_metadata(self):
        rec = NanoGPTRecognizer(None, None)
        self.assertEqual(rec.item_id, 'nanogpt')
        specs = rec.settings_spec()
        keys = [s['key'] for s in specs]
        self.assertIn('api_key', keys)
        self.assertIn('model', keys)
        self.assertIn('language', keys)

        rec.apply_settings({'api_key': 'test-custom-key', 'model': 'gpt-4o-mini-transcribe', 'language': 'en'})
        self.assertEqual(rec.api_key, 'test-custom-key')
        self.assertEqual(rec.model, 'gpt-4o-mini-transcribe')
        self.assertEqual(rec.language, 'en')

    def test_speech_recognition_lifecycle(self):
        SpeechRecognition.set_recognizer_type('nanogpt')
        self.assertEqual(SpeechRecognition._recognizer_type, 'nanogpt')
        inst = SpeechRecognition._new_instance('nanogpt')
        self.assertIsInstance(inst, NanoGPTRecognizer)

    async def test_transcribe_mock(self):
        rec = NanoGPTRecognizer(None, None)
        await rec.init()
        self.assertTrue(rec.is_initialized)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'text': 'Привет Мита'}

        audio = np.zeros(16000, dtype=np.float32)
        with patch('requests.post', return_value=mock_resp) as mock_post:
            res = await rec.transcribe(audio, 16000)
            self.assertEqual(res, 'Привет Мита')
            self.assertTrue(mock_post.called)
            kwargs = mock_post.call_args[1]
            self.assertEqual(kwargs['data']['model'], 'Whisper-Large-V3')
            self.assertEqual(kwargs['data']['language'], 'ru')
            self.assertIn('Authorization', kwargs['headers'])

    async def test_transcribe_hallucination_filtered(self):
        rec = NanoGPTRecognizer(None, None)
        await rec.init()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'text': 'Продолжение следует...'}

        audio = np.zeros(16000, dtype=np.float32)
        with patch('requests.post', return_value=mock_resp):
            res = await rec.transcribe(audio, 16000)
            self.assertIsNone(res)

    def test_nanogpt_asr_config_load_and_save(self):
        from handlers.asr_models.nanogpt_recognizer import (
            load_nanogpt_asr_config,
            save_nanogpt_asr_config,
        )

        test_cfg = {
            "api_key": "sk-nano-test-12345",
            "model": "gpt-4o-mini-transcribe",
            "language": "en",
        }
        save_nanogpt_asr_config(test_cfg)

        loaded = load_nanogpt_asr_config()
        self.assertEqual(loaded["api_key"], "sk-nano-test-12345")
        self.assertEqual(loaded["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(loaded["language"], "en")

    def test_find_key_in_api_presets(self):
        from handlers.asr_models.nanogpt_recognizer import find_nanogpt_key_in_api_presets

        fake_presets = {
            "presets": {
                "10004": {
                    "id": "10004",
                    "name": "NanoGPT",
                    "key": "sk-nano-preset-found",
                }
            }
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(fake_presets))), \
             patch("os.path.exists", return_value=True):
            key = find_nanogpt_key_in_api_presets()
            self.assertEqual(key, "sk-nano-preset-found")

    def test_is_nanogpt_asr_configured(self):
        from handlers.asr_models.nanogpt_recognizer import (
            is_nanogpt_asr_configured,
            save_nanogpt_asr_config,
        )

        save_nanogpt_asr_config({"api_key": "sk-nano-valid-key"})
        self.assertTrue(is_nanogpt_asr_configured())

        save_nanogpt_asr_config({"api_key": ""})
        with patch("handlers.asr_models.nanogpt_recognizer.find_nanogpt_key_in_api_presets", return_value=""):
            self.assertFalse(is_nanogpt_asr_configured())
