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
    async def test_uninitialized_model_does_not_start_worker_when_autoload_is_disabled(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {}
        controller._get_setting = lambda key, default=None: {
            "NM_CURRENT_VOICEOVER": "medium+",
            "LOCAL_VOICE_LOAD_LAST": False,
        }.get(key, default)
        controller._ensure_model_environment = lambda *_args, **_kwargs: self.fail(
            "synthesis must not activate the TTS environment"
        )
        controller.event_bus = SimpleNamespace(emit=lambda *_args, **_kwargs: None)

        with self.assertRaises(RuntimeError):
            await controller.synthesize("hello")

    async def test_string_false_does_not_enable_automatic_initialization(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {}
        controller._get_setting = lambda key, default=None: {
            "NM_CURRENT_VOICEOVER": "medium+",
            "LOCAL_VOICE_LOAD_LAST": "false",
        }.get(key, default)

        with self.assertRaises(RuntimeError):
            await controller.synthesize("hello")


if __name__ == "__main__":
    unittest.main()
