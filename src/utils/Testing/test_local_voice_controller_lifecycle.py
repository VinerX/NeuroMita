from __future__ import annotations

import sys
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.local_voice_controller import LocalVoiceController
from core.events import Event, Events


class LocalVoiceControllerLifecycleTests(unittest.TestCase):
    def test_constructing_proxy_does_not_start_tts_worker(self):
        with patch.object(LocalVoiceController, "_subscribe_to_events"), patch.object(
            LocalVoiceController,
            "_get_engine",
            side_effect=AssertionError("constructor must not acquire the AI engine"),
        ):
            LocalVoiceController()

    def test_regular_initialized_check_reads_cache_without_tts_rpc(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {"medium+": True}
        controller._get_engine = lambda: self.fail(
            "a read-only initialized check must not start the TTS worker"
        )

        self.assertTrue(controller.check_initialized("medium+"))
        self.assertFalse(controller.check_initialized("high"))

    def test_selecting_initialized_model_preserves_confirmed_cache_state(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {"high_clf5": True}
        controller._save_setting = lambda *_args: None

        selected = controller._on_select_voice_model(
            Event(Events.Audio.SELECT_VOICE_MODEL, {"model_id": "high_clf5"})
        )

        self.assertTrue(selected)
        self.assertTrue(controller._initialized_cache["high_clf5"])


class LocalVoiceControllerSynthesisTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_timeout_has_actionable_message(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        pending = Future()
        controller._get_engine = lambda: SimpleNamespace(
            call=lambda *_args, **_kwargs: pending
        )

        with self.assertRaisesRegex(
            TimeoutError,
            "Local TTS request 'synthesize' timed out after 0.01 seconds",
        ):
            await controller._engine_call_async("synthesize", timeout=0.01)

    async def test_uninitialized_model_does_not_start_on_demand_initialization(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {}
        controller._get_setting = lambda key, default=None: {
            "NM_CURRENT_VOICEOVER": "medium+",
        }.get(key, default)
        environment_calls = []

        async def ensure_environment(model_id, *, initialize=False):
            environment_calls.append((model_id, initialize))

        controller._ensure_model_environment = ensure_environment

        with self.assertRaisesRegex(RuntimeError, "Initialize it explicitly"):
            await controller.synthesize("hello")

        self.assertEqual(environment_calls, [])


async def _completed(value):
    return value


if __name__ == "__main__":
    unittest.main()
