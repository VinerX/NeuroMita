from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.audio_controller import AudioController
from controllers.chat_controller import ChatController
from controllers.gui.chat_controller import ChatController as GuiChatController
from controllers.model_controller import ModelController
from ui.windows.app_window_base import AppWindowBase
from controllers.speech_controller import SpeechController
from core.events import Event, Events
from core.executors import PoolSaturated, Pools
from core.performance_trace import performance_traces
from core.request_policy import RequestPolicy
from core.services import services
from handlers.llm_providers.base import LLMRequest, LLMResponse
from managers.api_preset_resolver import PresetSettings
from managers.llm_request_runner import LLMRequestRunner
from managers.tools.base import Tool
from managers.tools.tool_manager import ToolManager
from schemas.structured_response import ResponseSegment, StructuredResponse, ToolCall
from services.contracts import (
    CharacterRegistry,
    ChatGenerationRequest,
    ChatGenerationResult,
    GameLinkService,
    GenerationService,
    LocalVoiceService,
)


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Registry(CharacterRegistry):
    def get(self, character_id):
        return None

    def all_ids(self):
        return ["Crazy"]

    def current(self):
        return None

    def current_id(self):
        return "Crazy"

    def current_profile(self):
        return {"character_id": "Crazy", "name": "Crazy"}

    def current_name(self):
        return "Crazy"

    def name_of(self, character_id):
        return str(character_id or "")


class _Bus:
    def __init__(self):
        self.events = []

    def subscribe(self, *_args, **_kwargs):
        return None

    def unsubscribe(self, *_args, **_kwargs):
        return None

    def emit(self, name, data=None, **_kwargs):
        self.events.append((name, data))
        return True


class _Generation(GenerationService):
    def __init__(self, result=None, error=None):
        self.request = None
        self.result = result
        self.error = error

    def generate_chat(self, request: ChatGenerationRequest):
        self.request = request
        if self.error is not None:
            raise self.error
        return self.result or ChatGenerationResult(text="ok", character_id="Crazy")

    def generate_utility(self, request):
        raise AssertionError("not used")


class _VoiceService(LocalVoiceService):
    def model_configs(self):
        return []

    def is_installed(self, model_id):
        return True

    def check_initialized(self, model_id, *, strict=False):
        return True

    def select_model(self, model_id):
        return True

    def initialize_model(self, model_id):
        return True

    def triton_status(self, *, refresh=False):
        return {}

    async def synthesize(self, text, *, character_id=None, voice_profile=None):
        return "voice.wav"


class _GameLink(GameLinkService):
    def __init__(self, owner=""):
        self.owner = owner

    def is_connected(self):
        return bool(self.owner)

    def player_turn_owner(self):
        return self.owner


class _Calculator(Tool):
    @property
    def name(self):
        return "calculator"

    @property
    def description(self):
        return "test calculator"

    def run(self, **kwargs):
        return str(int(kwargs.get("value", 0)) + 1)


class _ToolModel:
    def __init__(self):
        self.tool_manager = ToolManager()
        self.tool_manager.register(_Calculator())
        self.responses = [LLMResponse(text='{"segments":[{"text":"done"}]}')]

    def generate(self, *_args, **_kwargs):
        return self.responses.pop(0)


class _ModelHarness:
    def __init__(self):
        self.settings = _Settings()
        self.event_bus = _Bus()
        self.model = _ToolModel()

    def _build_usage_snapshot(self, *_args, **_kwargs):
        return None

    def _split_response_thinking(self, response):
        return response.text, ""

    def _process_structured_output(self, **_kwargs):
        return ChatGenerationResult(text="done", character_id="Crazy")


class _RunnerSettings:
    def get(self, key, default=None):
        return default


class _RunnerEvents:
    def emit(self, *_args, **_kwargs):
        return None


class _RunnerResolver:
    def __init__(self, presets):
        self.presets = presets

    def resolve_chain(self, _preset_id):
        return list(self.presets)

    def apply_key_rotation(self, preset, _attempt):
        return preset


def _preset(name):
    return PresetSettings(
        protocol_id="openai_compatible_default",
        dialect_id="openai_chat_completions",
        provider_name="common",
        headers={},
        transforms=[],
        capabilities={},
        api_key="",
        api_url="http://localhost:1234/v1",
        api_model=name,
        preset_name=name,
        reserve_keys=[],
    )


class PerformanceTraceIntegrationTests(unittest.TestCase):
    def setUp(self):
        performance_traces().clear()
        services().register(CharacterRegistry, _Registry(), replace=True)

    def tearDown(self):
        performance_traces().clear()

    def _chat_controller(self, settings, bus):
        with patch("controllers.chat_controller.get_event_bus", return_value=bus):
            return ChatController(settings)

    def test_chat_success_passes_trace_id_and_finishes_ok(self):
        bus = _Bus()
        generation = _Generation()
        services().register(GenerationService, generation, replace=True)
        controller = self._chat_controller(_Settings({"ENABLE_STREAMING": False}), bus)
        trace = performance_traces().start("desktop")

        with patch("controllers.chat_controller.executors") as registry:
            registry.return_value.try_submit.side_effect = (
                lambda _pool, fn, **kwargs: fn(**kwargs)
            )
            controller._on_send_message(
                Event(
                    Events.Chat.SEND_MESSAGE,
                    {"user_input": "hello", "trace_id": trace.trace_id},
                )
            )

        self.assertEqual(generation.request.trace_id, trace.trace_id)
        snapshot = performance_traces().snapshot(trace.trace_id)
        self.assertEqual(snapshot["status"], "ok")
        self.assertIn("response.generated", [mark["name"] for mark in snapshot["marks"]])

    def test_chat_exception_finishes_error_and_pool_rejection_finishes_rejected(self):
        bus = _Bus()
        services().register(
            GenerationService,
            _Generation(error=RuntimeError("generation exploded")),
            replace=True,
        )
        controller = self._chat_controller(_Settings({"ENABLE_STREAMING": False}), bus)
        error_trace = performance_traces().start("desktop")
        controller._run_request("hello", character_id="Crazy", trace_id=error_trace.trace_id)
        error_snapshot = performance_traces().snapshot(error_trace.trace_id)
        self.assertEqual(error_snapshot["status"], "error")
        self.assertEqual(error_snapshot["error_type"], "RuntimeError")

        rejected_trace = performance_traces().start("desktop")
        with patch("controllers.chat_controller.executors") as registry:
            registry.return_value.try_submit.side_effect = PoolSaturated(Pools.GENERATION, 1)
            controller._submit_request(trace_id=rejected_trace.trace_id)
        rejected_snapshot = performance_traces().snapshot(rejected_trace.trace_id)
        self.assertEqual(rejected_snapshot["status"], "rejected")
        self.assertEqual(rejected_snapshot["error_stage"], "generation.pool")

    def test_voice_handoff_stays_open_until_audio_controller_finishes(self):
        bus = _Bus()
        result = ChatGenerationResult(
            text="spoken response",
            character_id="Crazy",
            voice_profile={"character_id": "Crazy", "silero_command": "/speaker Crazy"},
        )
        services().register(GenerationService, _Generation(result=result), replace=True)
        settings = _Settings({"ENABLE_STREAMING": False, "USE_VOICEOVER": True})
        controller = self._chat_controller(settings, bus)
        trace = performance_traces().start("desktop")

        controller._run_request("hello", character_id="Crazy", trace_id=trace.trace_id)

        voice_event = next(data for name, data in bus.events if name == Events.Audio.VOICEOVER_REQUESTED)
        self.assertIsNotNone(performance_traces().get(trace.trace_id))
        self.assertEqual(voice_event["trace_id"], trace.trace_id)

        audio = object.__new__(AudioController)
        audio.settings = _Settings({"VOICEOVER_LOCAL_CHAT": True, "LOCAL_VOICE_DELETE_AUDIO": True})
        audio.event_bus = _Bus()
        audio.waiting_answer = True

        def resolve_service(contract):
            if contract is LocalVoiceService:
                return _VoiceService()
            if contract is GameLinkService:
                return _GameLink()
            raise AssertionError("unexpected service")

        with patch("controllers.audio_controller.use", side_effect=resolve_service), patch(
            "controllers.audio_controller.AudioHandler.handle_voice_file", new=AsyncMock()
        ):
            asyncio.run(
                audio._await_local_voiceover_and_postprocess(
                    "spoken response",
                    "spoken response",
                    None,
                    character_id="Crazy",
                    voice_profile=voice_event["voice_profile"],
                    trace_id=trace.trace_id,
                )
            )

        snapshot = performance_traces().snapshot(trace.trace_id)
        self.assertEqual(snapshot["status"], "ok")
        self.assertIn("tts.synthesis", [span["name"] for span in snapshot["spans"]])
        self.assertIn("audio.playback", [span["name"] for span in snapshot["spans"]])

    def test_asr_trace_reaches_gui_but_game_payload_stays_python_free(self):
        class _AsrSettings:
            def snapshot(self):
                return {"engine": "test"}

        speech_bus = _Bus()
        speech = object.__new__(SpeechController)
        speech.settings = _Settings(
            {"MIC_ACTIVE": True, "MIC_MUTE_WHILE_SPEAKING": False, "MIC_INSTANT_SENT": True}
        )
        speech.asr_settings = _AsrSettings()
        speech.events_bus = speech_bus
        speech._last_text = ""
        speech._last_text_norm = ""
        speech._last_text_time = 0.0
        speech._speaking_window = SimpleNamespace(is_active=lambda: False)
        speech._is_asr_duplicate = lambda _text, _now: False
        speech._instant_send_policy = lambda: (True, 0.0)
        speech._turns_lock = __import__("threading").Lock()
        speech._turns_in_game = {}
        speech._player_turn_owner = lambda: ""
        trace = performance_traces().start("asr")

        speech._on_speech_text_recognized(
            Event(Events.Speech.SPEECH_TEXT_RECOGNIZED, {"text": "hello", "trace_id": trace.trace_id})
        )
        gui_payload = next(data for name, data in speech_bus.events if name == Events.GUI.SEND_TEXT_MESSAGE)

        class _Signal:
            def __init__(self):
                self.payloads = []

            def emit(self, payload):
                self.payloads.append(payload)

        signal = _Signal()
        gui = object.__new__(GuiChatController)
        gui.view = SimpleNamespace(send_text_message_signal=signal)
        gui._on_send_text_message(Event(Events.GUI.SEND_TEXT_MESSAGE, gui_payload))
        self.assertEqual(signal.payloads, [{"text": "hello", "trace_id": trace.trace_id}])
        self.assertEqual(performance_traces().snapshot(trace.trace_id)["status"], "active")
        performance_traces().finish(trace.trace_id, "ok")

        game_bus = _Bus()
        game = object.__new__(SpeechController)
        game.settings = speech.settings
        game.asr_settings = _AsrSettings()
        game.events_bus = game_bus
        game._last_text = ""
        game._last_text_norm = ""
        game._last_text_time = 0.0
        game._speaking_window = SimpleNamespace(is_active=lambda: False)
        game._is_asr_duplicate = lambda _text, _now: False
        game._instant_send_policy = lambda: (True, 0.0)
        game._turns_lock = __import__("threading").Lock()
        game._turns_in_game = {}
        game._player_turn_owner = lambda: "game#1"
        game_trace = performance_traces().start("asr")
        game._on_speech_text_recognized(
            Event(Events.Speech.SPEECH_TEXT_RECOGNIZED, {"text": "hello", "trace_id": game_trace.trace_id})
        )
        game_payload = next(data for name, data in game_bus.events if name == Events.Server.SEND_ASR_TEXT)
        self.assertNotIn("trace_id", game_payload)
        self.assertEqual(performance_traces().snapshot(game_trace.trace_id)["status"], "sent_to_game")

    def test_tool_followup_has_two_llm_spans_and_tool_span(self):
        trace = performance_traces().start("structured-chat")
        harness = _ModelHarness()
        structured = StructuredResponse(
            segments=[ResponseSegment(text="Checking")],
            tool_call=ToolCall(name="calculator", args={"value": 41}),
        )
        with trace.span("llm.total", phase="initial"):
            pass
        result = ModelController._handle_tool_call(
            harness,
            structured=structured,
            visible_raw='{"segments":[{"text":"Checking"}]}',
            think_text="",
            usage=None,
            response_model="model",
            response_provider="provider",
            pricing_info=None,
            char=object(),
            char_id="Crazy",
            char_name="Crazy",
            origin_message_id=None,
            capabilities={},
            policy=RequestPolicy(write_to_history=False),
            sender="Player",
            participants=[],
            user_input="calculate",
            image_data=[],
            image_source="",
            req_id=None,
            task_uid=None,
            event_type="chat",
            combined_messages=[],
            preset_id=None,
            enabled_tools=["calculator"],
            tool_depth=0,
            trace_id=trace.trace_id,
        )
        self.assertEqual(result.text, "done")
        snapshot = performance_traces().finish(trace.trace_id)
        llm_spans = [span for span in snapshot["spans"] if span["name"] == "llm.total"]
        self.assertEqual(len(llm_spans), 2)
        self.assertAlmostEqual(
            snapshot["metrics"]["llm_total_ms"],
            sum(span["duration_ms"] for span in llm_spans),
            places=6,
        )
        self.assertEqual(len([span for span in snapshot["spans"] if span["name"] == "tool.call"]), 1)

    def test_app_window_keeps_legacy_fourth_positional_argument(self):
        class _ShellActions:
            def __init__(self):
                self.calls = []

            def send_message(self, **kwargs):
                self.calls.append(kwargs)
                return True

        window = AppWindowBase.__new__(AppWindowBase)
        window._shell_actions = _ShellActions()
        window.show_send_error = lambda _message: None

        AppWindowBase.send_message(window, "", None, "typed", True)

        self.assertEqual(
            window._shell_actions.calls,
            [{
                "system_input": "",
                "image_data": None,
                "user_input": "typed",
                "trace_id": None,
                "merge_input_from_entry": True,
            }],
        )
    def test_fallback_attempt_is_success_with_fallback_attribute(self):
        class _Provider:
            def generate(self, request):
                if request.model == "main":
                    return LLMResponse(text=None, model="main", provider_name="common", error_message="empty")
                return LLMResponse(text="fallback ok", model="fallback", provider_name="common")

            def close(self):
                return None

        runner = LLMRequestRunner(
            _RunnerSettings(),
            _RunnerResolver([_preset("main"), _preset("fallback")]),
            _RunnerEvents(),
        )
        runner.provider_manager.close()
        runner.provider_manager = _Provider()
        trace = performance_traces().start("runner")
        response = runner.run(
            messages=[],
            preset_id=None,
            stream_callback=None,
            build_request=lambda _preset, model: LLMRequest(
                model=model,
                messages=[],
                api_url="http://localhost:1234/v1",
                provider_name="common",
            ),
            max_attempts=1,
            retry_delay=0.0,
            request_timeout=1.0,
            trace_id=trace.trace_id,
        )
        self.assertEqual(response.text, "fallback ok")
        snapshot = performance_traces().finish(trace.trace_id)
        fallback_span = next(
            span
            for span in snapshot["spans"]
            if span["name"] == "llm.attempt" and span["attributes"].get("fallback")
        )
        self.assertEqual(fallback_span["attributes"]["result"], "success")
        runner.close()


if __name__ == "__main__":
    unittest.main()