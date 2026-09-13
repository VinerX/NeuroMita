import asyncio
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
