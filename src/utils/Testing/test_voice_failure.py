import asyncio
from unittest.mock import Mock, patch

import pytest

from controllers.audio_controller import AudioController
from controllers.local_voice_controller import LocalVoiceController
from core.events import Events
from core.remote_voice import RemoteVoiceError
from core.voice_failure import VoiceFailureCode, classify_voice_failure
from managers.task_manager import TaskManager


def test_uninitialized_model_delivers_typed_failure_and_preserves_generated_text():
    local = LocalVoiceController.__new__(LocalVoiceController)
    local._initialized_cache = {}
    local._get_setting = lambda key, default=None: {"NM_CURRENT_VOICEOVER": "edge_tts_rvc_onnx"}.get(key, default)
    manager = TaskManager()
    task = manager.create_task("dialogue", {"character": "Crazy"})
    manager.update_task_status(task.uid, task.status, {"response": "generated answer"})
    audio = AudioController.__new__(AudioController)
    audio.settings = {}
    audio.event_bus = Mock()

    def update(name, data=None):
        if name == Events.Task.UPDATE_TASK_STATUS:
            manager.update_task_status(data["uid"], data["status"], data.get("result"), data.get("error"))
    audio.event_bus.emit.side_effect = update
    with patch("controllers.audio_controller.use", return_value=local):
        asyncio.run(audio._synthesize_and_deliver("text", "text", task.uid, method="Local"))
    packet = manager.get_task(task.uid).to_dict()
    assert packet["status"] == "FAILED_ON_VOICEOVER"
    assert packet["result"]["response"] == "generated answer"
    details = packet["result"]["error_details"]
    assert details["code"] == "voice.model_not_initialized"
    assert details["model_id"] == "edge_tts_rvc_onnx"
    assert details["domain"] == "voice"
    assert details["version"] == 1
    assert "not initialized" in packet["error"]
    assert "RuntimeError" not in details["short_message"]


@pytest.mark.parametrize("code,expected", [
    ("http.401", VoiceFailureCode.AUTHENTICATION),
    ("http.429", VoiceFailureCode.RATE_LIMITED),
    ("http.503", VoiceFailureCode.PROVIDER_UNAVAILABLE),
])
def test_remote_voice_code_survives_task_classification(code, expected):
    assert classify_voice_failure(RemoteVoiceError("diagnostic", code=code)).code == expected


def test_unknown_error_does_not_leak_exception_into_hud_message():
    details = classify_voice_failure(RuntimeError("internal implementation details")).to_dict()
    assert details["code"] == "voice.synthesis_failed"
    assert "internal implementation details" not in details["short_message"]
