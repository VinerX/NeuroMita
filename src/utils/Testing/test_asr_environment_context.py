from __future__ import annotations

from typing import Optional

import numpy as np

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface


class _ContextProbeRecognizer(SpeechRecognizerInterface):
    MODEL_CONFIGS = [{"id": "probe", "name": "Probe"}]

    def __init__(self, *, result: bool = True, crash: bool = False) -> None:
        super().__init__(None, None)
        self.result = result
        self.crash = crash
        self.seen_contexts: list[dict] = []

    def is_installed(self, ctx: dict | None = None) -> bool:
        self.seen_contexts.append(dict(ctx or {}))
        if self.crash:
            raise RuntimeError("probe failed")
        return self.result

    async def install(self) -> bool:
        return True

    async def init(self, **kwargs) -> bool:
        return True

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        return None

    async def live_recognition(
        self,
        microphone_index: int,
        handle_voice_callback,
        vad_model,
        active_flag,
        **kwargs,
    ) -> None:
        return None

    def cleanup(self) -> None:
        return None


def test_asr_status_uses_explicit_environment_context() -> None:
    recognizer = _ContextProbeRecognizer(result=True)
    context = {
        "target_dir": "X:/managed/environment/site-packages",
        "python_paths": ["X:/managed/environment/site-packages", "X:/managed/core"],
        "strict_target": True,
        "gpu_vendor": "CPU",
    }

    status = recognizer.status(context)

    assert status.installed is True
    assert recognizer.seen_contexts
    assert recognizer.seen_contexts[-1]["target_dir"] == context["target_dir"]
    assert recognizer.seen_contexts[-1]["strict_target"] is True


def test_asr_post_install_validation_is_fail_closed() -> None:
    recognizer = _ContextProbeRecognizer(crash=True)
    plan = recognizer.build_install_plan(
        {
            "target_dir": "X:/managed/environment/site-packages",
            "python_paths": ["X:/managed/environment/site-packages"],
            "strict_target": True,
            "gpu_vendor": "CPU",
        }
    )
    final_check = plan.actions[-1].fn

    assert callable(final_check)
    assert final_check(ctx={"target_dir": "X:/managed/environment/site-packages"}) is False
