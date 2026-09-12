import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx

from handlers.fish_audio_handler import synthesize, voice_id, save_config, load_config
from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.common_provider import CommonProvider
from presets.api_templates import API_TEMPLATES_DATA
from presets.api_protocols import API_PROTOCOLS_DATA
from utils.provider_urls import models_url

CONFIG = {"api_key": "test-secret", "voice_id": "a" * 32, "model": "s2.1-pro", "speed": 1.0}


class FishTests(unittest.IsolatedAsyncioTestCase):
    async def test_game_audio_delivery_and_failure_status(self):
        from unittest.mock import AsyncMock, Mock
        from controllers.audio_controller import AudioController
        from core.events import Events
        from services.contracts import GameLinkService
        from managers.task_manager import TaskStatus
        controller = AudioController.__new__(AudioController)
        controller.settings = {}
        controller.event_bus = Mock()
        controller.waiting_answer = True
        game = Mock()
        game.is_connected.return_value = True
        def service(kind):
            self.assertIs(kind, GameLinkService, "Fish must not require LocalVoiceService")
            return game
        with patch("controllers.audio_controller.use", side_effect=service):
            with patch("handlers.fish_audio_handler.synthesize", new=AsyncMock(return_value="/tmp/voice.wav")):
                await controller._await_local_voiceover_and_postprocess("Hi", "Hi", "task-1", method="Fish Audio")
        updates = [c.args[1] for c in controller.event_bus.emit.call_args_list if c.args[0] == Events.Task.UPDATE_TASK_STATUS]
        self.assertEqual(updates[0]["status"], TaskStatus.SUCCESS)
        self.assertEqual(updates[0]["result"]["voiceover_path"], "/tmp/voice.wav")
        self.assertFalse(controller.waiting_answer)
        controller.event_bus.reset_mock()
        with patch("handlers.fish_audio_handler.synthesize", new=AsyncMock(side_effect=ValueError("Fish Audio: HTTP 402"))):
            await controller._await_local_voiceover_and_postprocess("Hi", "Hi", "task-2", method="Fish Audio")
        updates = [c.args[1] for c in controller.event_bus.emit.call_args_list if c.args[0] == Events.Task.UPDATE_TASK_STATUS]
        self.assertEqual(updates[0]["status"], TaskStatus.FAILED_ON_VOICEOVER)

    async def test_synthesis_request_and_playable_wav(self):
        def respond(req):
            self.assertEqual(str(req.url), "https://api.fish.audio/v1/tts")
            self.assertEqual(req.headers["authorization"], "Bearer test-secret")
            self.assertEqual(req.headers["model"], "s2.1-pro")
            body = json.loads(req.content)
            self.assertEqual(body["reference_id"], "a" * 32)
            self.assertEqual(body["text"], "Привет")
            self.assertEqual(body["format"], "pcm")
            return httpx.Response(200, content=b"\x01\x00" * 4410, headers={"content-type": "audio/pcm"})
        with tempfile.TemporaryDirectory() as directory:
            path = await synthesize("Привет", config=CONFIG, output_dir=directory, transport=httpx.MockTransport(respond))
            with wave.open(path) as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()), (44100, 1, 2, 4410))

    async def test_api_errors_leave_no_partial_file_or_secret(self):
        for status in (401, 402, 403, 404, 422, 429, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                transport = httpx.MockTransport(lambda r: httpx.Response(status, text="test-secret"))
                with self.assertRaises(ValueError) as raised:
                    await synthesize("test", config=CONFIG, output_dir=directory, transport=transport)
                self.assertNotIn("test-secret", str(raised.exception))
                self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_corrupt_or_non_audio_response(self):
        for data, content_type in ((b"", "audio/pcm"), (b"x", "audio/pcm"), (b"{}", "application/json")):
            with tempfile.TemporaryDirectory() as directory:
                transport = httpx.MockTransport(lambda r: httpx.Response(200, content=data, headers={"content-type": content_type}))
                with self.assertRaises(ValueError):
                    await synthesize("test", config=CONFIG, output_dir=directory, transport=transport)
                self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_timeout_and_cancellation_cleanup(self):
        for error in (httpx.ReadTimeout("test-secret"), asyncio.CancelledError()):
            async def respond(req):
                raise error
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises((ValueError, asyncio.CancelledError)):
                    await synthesize("test", config=CONFIG, output_dir=directory, transport=httpx.MockTransport(respond))
                self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_missing_voice_does_not_send_request(self):
        def unexpected(req):
            self.fail("Should validate before HTTP")
        with self.assertRaises(ValueError):
            await synthesize("test", config={**CONFIG, "voice_id": ""}, transport=httpx.MockTransport(unexpected))

    def test_voice_ids_and_urls(self):
        self.assertEqual(voice_id("A" * 32), "a" * 32)
        self.assertEqual(voice_id("https://fish.audio/m/" + "a" * 32 + "/?x=1"), "a" * 32)
        for bad in ("", "garbage", "https://example.com/" + "a" * 32):
            with self.assertRaises(ValueError):
                voice_id(bad)

    def test_private_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fish_audio.json"
            with patch("handlers.fish_audio_handler.settings_path", return_value=path):
                save_config(CONFIG)
                self.assertEqual(load_config(), CONFIG)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                save_config({**CONFIG, "api_key": ""})
                self.assertEqual(load_config()["api_key"], "")


class ProviderTests(unittest.TestCase):
    def test_custom_model_listing_uses_editor_url(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from controllers.api_presets_controller import ApiPresetsController, ApiTemplate
        from core.events import Event, Events
        controller = ApiPresetsController.__new__(ApiPresetsController)
        controller.presets = {}
        controller.templates = {1: ApiTemplate(id=1, name="old", url="https://old.example/v1/chat/completions", test_url="https://old.example/v1/models")}
        controller.event_bus = Mock()
        for base in (None, 1):
            supervisor = Mock()
            event = Event(Events.ApiPresets.TEST_CONNECTION, {
                "id": 5, "base": base, "key": "dummy", "url": "https://new.example/gateway/v1",
                "protocol_id": "custom_openai_default",
            })
            with patch("controllers.api_presets_controller.task_supervisor", return_value=supervisor):
                controller._on_test_connection(event)
            pid, template, key = supervisor.start_thread.call_args.kwargs["args"]
            self.assertEqual(template.test_url, "https://new.example/gateway/v1/models")
            self.assertEqual(template.protocol_id, "custom_openai_default")
            self.assertEqual(key, "dummy")

    def test_models_endpoint(self):
        for endpoint in ("https://nano-gpt.com/api/v1", "https://nano-gpt.com/api/v1/chat/completions/", "https://nano-gpt.com/api/v1/models"):
            self.assertEqual(models_url(endpoint), "https://nano-gpt.com/api/v1/models")
        self.assertEqual(models_url("http://localhost:1234/v1"), "http://localhost:1234/v1/models")
        self.assertEqual(models_url("https://example.com/gateway/chat/completions?x=1"), "https://example.com/gateway/models?x=1")
        for bad in ("", "example.com", "file:///tmp/test", "https://user:pass@example.com/v1"):
            with self.assertRaises(ValueError):
                models_url(bad)

    def test_nanogpt_template_and_protocol(self):
        tpl = next(t for t in API_TEMPLATES_DATA if t["name"] == "NanoGPT")
        protocol = next(p for p in API_PROTOCOLS_DATA if p["id"] == tpl["protocol_id"])
        self.assertEqual(protocol["provider"], "common")
        self.assertFalse(protocol["capabilities"]["structured_output"])
        self.assertEqual(len({t["id"] for t in API_TEMPLATES_DATA}), len(API_TEMPLATES_DATA))

    def test_cliproxyapi_template_and_protocol(self):
        tpl = next(t for t in API_TEMPLATES_DATA if t["name"] == "CLIProxyAPI (Local)")
        self.assertEqual(tpl["id"], 10002)
        self.assertEqual(tpl["badge_kind"], "local")
        self.assertEqual(tpl["default_model"], "gemini-3.7-flash")
        self.assertIn("claude-4.6-sonnet", tpl["known_models"])
        protocol = next(p for p in API_PROTOCOLS_DATA if p["id"] == tpl["protocol_id"])
        self.assertEqual(protocol["provider"], "common")
        self.assertFalse(protocol["capabilities"]["structured_output"])


    def test_custom_provider_complete_http_flow(self):
        # Real HTTP stack against an ephemeral localhost server, including SSE.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append((self.path, self.headers["Authorization"], body))
                if body.get("stream"):
                    payload = b'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                    kind = "text/event-stream"
                else:
                    payload = json.dumps({"model": body["model"], "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}]}).encode()
                    kind = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        provider = CommonProvider()
        try:
            for stream in (False, True):
                req = LLMRequest(model="any-provider/any-model", messages=[{"role": "user", "content": "Hi"}],
                                 api_key="dummy", api_url=f"http://127.0.0.1:{server.server_port}/api/v1",
                                 provider_name="common", protocol_id="custom_openai_default",
                                 dialect_id="openai_chat_completions", stream=stream)
                result = provider.generate(req)
                self.assertEqual(result.text, "Hello")
            for path, auth, body in captured:
                self.assertEqual(path, "/api/v1/chat/completions")
                self.assertEqual(auth, "Bearer dummy")
                self.assertEqual(body["model"], "any-provider/any-model")
                self.assertNotIn("response_format", body)
        finally:
            provider.close()
            server.shutdown()
            server.server_close()
            thread.join()


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_voice_panel_switching_and_persistence(self):
        from PyQt6.QtWidgets import QWidget, QVBoxLayout
        from ui.settings.voiceover_settings.ui import build_voiceover_settings_ui
        from controllers.gui.voiceover_controller import VoiceoverGuiController
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            with patch("handlers.fish_audio_handler.settings_path", return_value=Path(directory)/"fish_audio.json"):
                host = QWidget()
                class Settings(dict):
                    def set(self, key, value):
                        self[key] = value
                host.settings = Settings(USE_VOICEOVER=True, VOICEOVER_METHOD="Fish Audio")
                host._save_setting = lambda k, v: host.settings.__setitem__(k, v)
                layout = QVBoxLayout(host)
                build_voiceover_settings_ui(host, layout, actions=SimpleNamespace(dispatch=lambda x: None))
                self.assertGreaterEqual(host.method_combobox.findText("Fish Audio"), 0)
                ctl = SimpleNamespace(view=host, _effective_use_voice=lambda: True,
                                      _effective_method=lambda: host.method_combobox.currentText())
                host.show()
                for method in ("Fish Audio", "TG", "Local", "Fish Audio"):
                    host.method_combobox.setCurrentText(method)
                    VoiceoverGuiController._apply_voiceover_visibility_from_widgets(ctl)
                    self.app.processEvents()
                    self.assertEqual(host.fish_settings_frame.isVisible(), method == "Fish Audio")
                    self.assertEqual(host.local_settings_frame.isVisible(), method == "Local")
                    self.assertEqual(host.tg_settings_frame.isVisible(), method == "TG")
                fish = host.fish_settings_frame
                fish.key.setText("test-secret")
                fish.voice.setText("b" * 32)
                fish._save()
                self.assertEqual(load_config()["voice_id"], "b" * 32)
                fish.key.setText("")
                fish._save()
                self.assertEqual(load_config()["api_key"], "")
                host.close()

    def test_fish_does_not_download_ffmpeg(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from controllers.gui.system_controller import SystemController
        controller = SimpleNamespace(main_controller=SimpleNamespace(settings={"VOICEOVER_METHOD": "Fish Audio"}))
        supervisor = Mock()
        with patch("controllers.gui.system_controller.task_supervisor", return_value=supervisor):
            SystemController._check_and_install_ffmpeg_impl(controller)
        supervisor.start_thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
