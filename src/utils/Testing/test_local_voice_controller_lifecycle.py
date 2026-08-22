from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.local_voice_controller import LocalVoiceController


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


class LocalVoiceControllerSynthesisTests(unittest.IsolatedAsyncioTestCase):
    async def test_uninitialized_model_uses_on_demand_initialization_fallback(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {}
        controller._get_setting = lambda key, default=None: {
            "NM_CURRENT_VOICEOVER": "medium+",
            "LOCAL_VOICE_LOAD_LAST": False,
        }.get(key, default)
        environment_calls = []

        async def ensure_environment(model_id, *, initialize=False):
            environment_calls.append((model_id, initialize))

        controller._ensure_model_environment = ensure_environment
        controller._engine_call_async = lambda *_args, **_kwargs: _completed("voice.wav")
        controller.event_bus = SimpleNamespace(emit=lambda *_args, **_kwargs: None)

        registry = SimpleNamespace(current_profile=lambda: None, get=lambda _id: None)
        with patch("controllers.local_voice_controller.use", return_value=registry):
            result = await controller.synthesize("hello")

        self.assertEqual(result, "voice.wav")
        self.assertEqual(environment_calls, [("medium+", True)])
        self.assertTrue(controller._initialized_cache["medium+"])


async def _completed(value):
    return value


if __name__ == "__main__":
    unittest.main()
