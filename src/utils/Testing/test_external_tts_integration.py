from __future__ import annotations

import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.ai_engine.services.tts_service import TTSService


class ExternalTTSIntegrationTests(unittest.TestCase):
    def test_external_mode_does_not_initialize_local_tts(self):
        service = TTSService(emit_event=lambda *_args: None)
        service._local_voice = None
        result = asyncio.run(service.handle("ping", {}))
        self.assertTrue(result)
        self.assertIsNone(service._local_voice)

    def test_unload_clears_only_local_tts_runtime(self):
        local = type("Local", (), {"shutdown": lambda self: setattr(self, "closed", True)})()
        service = TTSService(emit_event=lambda *_args: None)
        service._local_voice = local
        service._current_model_id = "local-model"
        service._warmup_status["local-model"] = "ready"
        self.assertTrue(asyncio.run(service.handle("unload_model", {})))
        self.assertTrue(local.closed)
        self.assertIsNone(service._local_voice)
        self.assertIsNone(service._current_model_id)
        self.assertFalse(service._warmup_status)

    def test_external_voice_controller_forwards_character_voice_override(self):
        from controllers.external_voice_controller import ExternalVoiceController

        settings = {"EXTERNAL_TTS_BASE_URL": "http://localhost", "EXTERNAL_TTS_VOICE_ID": "fallback"}
        controller = ExternalVoiceController(settings)
        controller._client.synthesize = AsyncMock(return_value="file.wav")
        config = controller.configuration_snapshot()
        result = asyncio.run(controller.synthesize("hello", character_id="mita", voice_id="mita-rvc", config_snapshot=config))
        self.assertEqual(result, "file.wav")
        self.assertEqual(controller._client.synthesize.await_args.kwargs["voice_id"], "mita-rvc")
        self.assertEqual(controller._client.synthesize.await_args.kwargs["character_id"], "mita")

    def test_audio_controller_forwards_voice_profile_override(self):
        from controllers.external_voice_controller import ExternalVoiceController

        with patch.dict(
            sys.modules,
            {"handlers.audio_handler": types.SimpleNamespace(AudioHandler=object)},
        ):
            from controllers.audio_controller import AudioController

            external = ExternalVoiceController({"EXTERNAL_TTS_BASE_URL": "http://localhost"})
            external.synthesize = AsyncMock(return_value="voice.wav")
            controller = object.__new__(AudioController)
            controller.main_controller = SimpleNamespace(external_voice_controller=external)
            result = asyncio.run(controller._synthesize_external_voice(
                "hello", character_id="mita", voice_id="mita-rvc", config_snapshot=None
            ))
        self.assertEqual(result, "voice.wav")
        self.assertEqual(external.synthesize.await_args.kwargs["voice_id"], "mita-rvc")
