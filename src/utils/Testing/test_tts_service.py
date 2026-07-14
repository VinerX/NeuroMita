from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from handlers.ai_engine.services.tts_service import TTSService


class _FakeLocalVoice:
    def __init__(self, *, init_ok: bool = True, voiceover_result: str | Exception | None = None):
        self.init_ok = bool(init_ok)
        self.voiceover_result = voiceover_result
        self.voiceover_calls = 0

    def initialize_model(self, _model_id: str, *, init: bool = False) -> bool:
        return self.init_ok

    async def voiceover(self, text: str, *, output_file: str, character=None):
        self.voiceover_calls += 1
        result = self.voiceover_result
        if isinstance(result, Exception):
            raise result
        if result is None:
            return None
        out = str(output_file)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        Path(out).write_bytes(b"RIFF")
        return out


class TTSServiceTests(unittest.TestCase):
    def test_handle_init_model_emits_step_logs(self):
        logs: list[str] = []
        service = TTSService(emit_event=lambda event, payload: logs.append(str(payload)) if event == "log" else None)
        service._local_voice = _FakeLocalVoice(init_ok=True, voiceover_result="ok")

        ok = asyncio.run(service.handle("init_model", {"model_id": "high+low", "warmup": True}))

        self.assertTrue(ok)
        joined = "\n".join(logs)
        self.assertIn("[tts:init] start model_id=high+low warmup=True", joined)
        self.assertIn("[tts:init] runtime initialized for model_id=high+low", joined)
        self.assertIn("[tts:init] warmup finished for model_id=high+low", joined)

    def test_warmup_logs_runtime_error_details(self):
        logs: list[str] = []
        service = TTSService(emit_event=lambda event, payload: logs.append(str(payload)) if event == "log" else None)
        service._local_voice = _FakeLocalVoice(init_ok=True, voiceover_result=RuntimeError("hubert timeout"))

        ok = asyncio.run(service._warmup_model(service._local_voice, "high+low"))

        self.assertFalse(ok)
        joined = "\n".join(logs)
        self.assertIn("[tts:warmup] runtime error for model_id=high+low: hubert timeout", joined)

    def test_edge_model_init_warms_up_once(self):
        logs: list[str] = []
        service = TTSService(emit_event=lambda event, payload: logs.append(str(payload)) if event == "log" else None)
        service._local_voice = _FakeLocalVoice(init_ok=True, voiceover_result="ok")

        first = asyncio.run(service.handle(
            "init_model",
            {"model_id": "edge_tts_rvc_onnx", "warmup": True},
        ))
        second = asyncio.run(service.handle(
            "init_model",
            {"model_id": "edge_tts_rvc_onnx", "warmup": True},
        ))

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(service._warmup_status["edge_tts_rvc_onnx"], "ready")
        self.assertEqual(service._local_voice.voiceover_calls, 1)
        self.assertIn("warmup already ready", "\n".join(logs))

    def test_failed_warmup_rejects_initialization(self):
        logs: list[str] = []
        service = TTSService(emit_event=lambda event, payload: logs.append(str(payload)) if event == "log" else None)
        service._local_voice = _FakeLocalVoice(
            init_ok=True,
            voiceover_result=RuntimeError("probe failed"),
        )

        ok = asyncio.run(service.handle(
            "init_model",
            {"model_id": "silero_rvc_onnx", "warmup": True},
        ))

        self.assertFalse(ok)
        self.assertEqual(service._warmup_status["silero_rvc_onnx"], "failed")
        self.assertIn("initialization rejected", "\n".join(logs))


if __name__ == "__main__":
    unittest.main()
