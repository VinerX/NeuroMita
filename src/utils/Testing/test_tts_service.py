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

    def initialize_model(self, _model_id: str, *, init: bool = False) -> bool:
        return self.init_ok

    async def voiceover(self, text: str, *, output_file: str, character=None):
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

        ok = asyncio.run(service._best_effort_warmup(service._local_voice, "high+low"))

        self.assertFalse(ok)
        joined = "\n".join(logs)
        self.assertIn("[tts:warmup] runtime error for model_id=high+low: hubert timeout", joined)

    def test_edge_model_init_skips_network_warmup(self):
        logs: list[str] = []
        service = TTSService(emit_event=lambda event, payload: logs.append(str(payload)) if event == "log" else None)
        service._local_voice = _FakeLocalVoice(
            init_ok=True,
            voiceover_result=RuntimeError("must not be called"),
        )

        ok = asyncio.run(service.handle(
            "init_model",
            {"model_id": "edge_tts_rvc_onnx", "warmup": True},
        ))

        self.assertTrue(ok)
        self.assertEqual(service._warmup_status["edge_tts_rvc_onnx"], "skipped-network")
        self.assertIn("warmup skipped", "\n".join(logs))

    def test_failed_best_effort_warmup_does_not_invalidate_runtime_init(self):
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

        self.assertTrue(ok)
        self.assertEqual(service._warmup_status["silero_rvc_onnx"], "failed")
        self.assertIn("runtime remains initialized", "\n".join(logs))


if __name__ == "__main__":
    unittest.main()
