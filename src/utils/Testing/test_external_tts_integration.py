from __future__ import annotations

import asyncio
import concurrent.futures
import tempfile
import sys
import types
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.ai_engine.services.tts_service import TTSService


class ExternalTTSIntegrationTests(unittest.TestCase):
    def test_external_mode_does_not_initialize_local_tts(self):
        from services.contracts import GameLinkService, LocalVoiceService

        controller = self._audio_controller()
        synthesize = AsyncMock(return_value="D:/remote.wav")
        with patch("controllers.audio_controller.use", return_value=SimpleNamespace(is_connected=lambda: True)) as resolve:
            asyncio.run(controller._await_voiceover_and_postprocess(
                synthesize, method="external", original_text="hello", task_uid="task-3",
            ))
        synthesize.assert_awaited_once()
        resolve.assert_called_once_with(GameLinkService)
        self.assertNotEqual(resolve.call_args.args[0], LocalVoiceService)

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
        try:
            controller._client.synthesize = AsyncMock(return_value="file.wav")
            config = controller.configuration_snapshot()
            result = asyncio.run(controller.synthesize("hello", character_id="mita", voice_id="mita-rvc", config_snapshot=config))
            self.assertEqual(result, "file.wav")
            self.assertEqual(controller._client.synthesize.await_args.kwargs["voice_id"], "mita-rvc")
            self.assertEqual(controller._client.synthesize.await_args.kwargs["character_id"], "mita")
        finally:
            controller.close()

    def test_audio_controller_forwards_voice_profile_override(self):
        from controllers.external_voice_controller import ExternalVoiceController

        with patch.dict(
            sys.modules,
            {"handlers.audio_handler": types.SimpleNamespace(AudioHandler=object)},
        ):
            from controllers.audio_controller import AudioController
            audio_module = sys.modules["controllers.audio_controller"]
        sys.modules["controllers.audio_controller"] = audio_module

        external = ExternalVoiceController({"EXTERNAL_TTS_BASE_URL": "http://localhost"})
        try:
            external.synthesize = AsyncMock(return_value="voice.wav")
            controller = object.__new__(AudioController)
            controller.main_controller = SimpleNamespace(external_voice_controller=external)
            result = asyncio.run(controller._synthesize_external_voice(
                "hello", character_id="mita", voice_id="mita-rvc", config_snapshot=None
            ))
        finally:
            external.close()
        self.assertEqual(result, "voice.wav")
        self.assertEqual(external.synthesize.await_args.kwargs["voice_id"], "mita-rvc")

    def test_init_after_external_switch_waits_for_pending_unload(self):
        from controllers.local_voice_controller import LocalVoiceController

        class EventsRecorder:
            def emit(self, *_args, **_kwargs): pass

        controller = object.__new__(LocalVoiceController)
        controller._unload_future = concurrent.futures.Future()
        controller._unload_future_lock = __import__("threading").Lock()
        controller._initialized_cache = {}
        controller.event_bus = EventsRecorder()
        controller._ensure_model_environment = AsyncMock(return_value=None)

        async def check_order():
            init = asyncio.create_task(controller._async_init_model("local-model"))
            await asyncio.sleep(0)
            controller._ensure_model_environment.assert_not_awaited()
            controller._unload_future.set_result(True)
            await init

        asyncio.run(check_order())
        controller._ensure_model_environment.assert_awaited_once_with("local-model", initialize=True)

    def test_external_output_cleanup_runs_without_a_synthesis_request(self):
        from controllers.external_voice_controller import ExternalVoiceController

        with tempfile.TemporaryDirectory() as folder:
            settings = {
                "EXTERNAL_TTS_BASE_URL": "http://localhost",
                "EXTERNAL_TTS_OUTPUT_DIR": folder,
            }
            with patch.object(ExternalVoiceController, "CLEANUP_INTERVAL_SECONDS", 0.02):
                controller = ExternalVoiceController(settings)
                try:
                    stale = Path(folder) / "external_tts_old.wav"
                    stale.write_bytes(b"old")
                    import os
                    os.utime(stale, (1, 1))
                    for _ in range(100):
                        if not stale.exists():
                            break
                        time.sleep(0.01)
                    self.assertFalse(stale.exists())
                finally:
                    controller.close()

    def test_external_task_receives_local_voiceover_path(self):
        from managers.task_manager import TaskStatus

        audio_controller = self._audio_controller()
        with patch("controllers.audio_controller.use", return_value=SimpleNamespace(is_connected=lambda: True)):
            asyncio.run(audio_controller._await_voiceover_and_postprocess(
                AsyncMock(return_value="D:/voice.wav"), method="external",
                original_text="hello", task_uid="task-1",
            ))
        event = next(item[1] for item in audio_controller.event_bus.items if isinstance(item[1], dict) and getattr(item[1].get("status"), "value", item[1].get("status")) == TaskStatus.SUCCESS.value)
        self.assertEqual(event["result"]["voiceover_path"], "D:/voice.wav")

    def test_unity_task_status_maps_voiceover_path_to_audio_path(self):
        from game_connections.handlers.actions.get_task_status import GetTaskStatusAction
        from managers.task_manager import TaskStatus
        from services.contracts import SettingsService, TaskService, TelegramService

        task = SimpleNamespace(
            status=TaskStatus.SUCCESS,
            result={"voiceover_path": "D:/voice.wav"},
            to_dict=lambda: {"status": "SUCCESS", "result": {"voiceover_path": "D:/voice.wav"}},
        )
        response = {}
        server = SimpleNamespace(send_json=AsyncMock(side_effect=lambda _writer, data: response.update(data)))
        context = SimpleNamespace(server=server, writer=object())

        def resolve(service_type):
            if service_type is TaskService:
                return SimpleNamespace(get_task=lambda _uid: task)
            if service_type is TelegramService:
                return SimpleNamespace(is_silero_connected=lambda: False)
            if service_type is SettingsService:
                return SimpleNamespace(get=lambda _key, default=None: default)
            raise AssertionError(service_type)

        with patch("game_connections.handlers.actions.get_task_status.use", side_effect=resolve):
            asyncio.run(GetTaskStatusAction().handle({"task_uid": "task-1"}, context))
        self.assertEqual(response["result"]["audio_path"], "D:/voice.wav")

    def test_external_failure_marks_task_failed_on_voiceover(self):
        from managers.task_manager import TaskStatus

        audio_controller = self._audio_controller()
        with patch("controllers.audio_controller.use", return_value=SimpleNamespace(is_connected=lambda: True)):
            asyncio.run(audio_controller._await_voiceover_and_postprocess(
                AsyncMock(side_effect=TimeoutError("offline")), method="external",
                original_text="hello", task_uid="task-2",
            ))
        event = next(item[1] for item in audio_controller.event_bus.items if isinstance(item[1], dict) and getattr(item[1].get("status"), "value", item[1].get("status")) == TaskStatus.FAILED_ON_VOICEOVER.value)
        self.assertIn("offline", event["error"])

    def test_external_desktop_path_uses_existing_playback_handler(self):
        audio_controller = self._audio_controller()
        audio_controller.settings["VOICEOVER_LOCAL_CHAT"] = True
        import controllers.audio_controller as audio_module
        handler = SimpleNamespace(handle_voice_file=AsyncMock())
        with patch.object(audio_module, "AudioHandler", handler), patch(
            "controllers.audio_controller.use", return_value=SimpleNamespace(is_connected=lambda: False)
        ):
            asyncio.run(audio_controller._await_voiceover_and_postprocess(
                AsyncMock(return_value="D:/voice.wav"), method="external",
                original_text="hello", task_uid=None,
            ))
        handler.handle_voice_file.assert_awaited_once()

    @staticmethod
    def _audio_controller():
        with patch.dict(
            sys.modules,
            {"handlers.audio_handler": types.SimpleNamespace(AudioHandler=object)},
        ):
            from controllers.audio_controller import AudioController
            audio_module = sys.modules["controllers.audio_controller"]
        sys.modules["controllers.audio_controller"] = audio_module

        class EventRecorder:
            def __init__(self): self.items = []
            def emit(self, *args, **kwargs): self.items.append((args[0], args[1] if len(args) > 1 else kwargs))

        controller = object.__new__(AudioController)
        controller.settings = {"VOICEOVER_LOCAL_CHAT": False, "VOICEOVER_LOCAL_VOLUME": 100}
        controller.event_bus = EventRecorder()
        controller.waiting_answer = True
        controller._emit_show_voicing = lambda *_args, **_kwargs: None
        controller._set_mita_speaking = lambda *_args, **_kwargs: None
        return controller
