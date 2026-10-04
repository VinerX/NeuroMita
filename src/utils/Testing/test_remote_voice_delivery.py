import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from controllers.audio_controller import AudioController
from core.remote_voice import RemoteVoiceError
from services.contracts import RemoteVoiceService, GameLinkService


@pytest.mark.parametrize("connected,task_uid,chat,expect_play,expect_keep", [
    (True, "task", True, False, True),
    (True, None, True, True, False),
    (False, None, True, True, False),
    (False, None, False, False, False),
])
def test_api_reuses_delivery_and_releases_files(tmp_path, connected, task_uid, chat, expect_play, expect_keep):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"audio")
    remote = SimpleNamespace(synthesize=AsyncMock(return_value=str(path)))
    game = SimpleNamespace(is_connected=lambda: connected)
    controller = AudioController.__new__(AudioController)
    controller.settings = {"VOICEOVER_LOCAL_CHAT": chat, "VOICEOVER_LOCAL_VOLUME": 125}
    controller.event_bus = Mock()
    controller._emit_show_voicing = Mock()
    controller._set_mita_speaking = Mock()
    controller._update_task_failed_voiceover = Mock()
    services = {RemoteVoiceService: remote, GameLinkService: game}
    with patch("controllers.audio_controller.use", side_effect=services.__getitem__), \
         patch("controllers.audio_controller.AudioHandler.handle_voice_file", new_callable=AsyncMock) as play:
        asyncio.run(controller._synthesize_and_deliver("prepared", "original", task_uid, character_id="Kind", method="API"))
    remote.synthesize.assert_awaited_once_with("original", character_id="Kind")
    assert bool(play.await_count) == expect_play
    if expect_play:
        assert play.call_args.kwargs["volume"] == 125
        assert controller._set_mita_speaking.call_args_list[0].args == (True,)
        assert controller._set_mita_speaking.call_args_list[-1].args == (False,)
    else:
        controller._set_mita_speaking.assert_not_called()
    assert path.exists() == expect_keep
    assert not controller.waiting_answer
    controller._update_task_failed_voiceover.assert_not_called()


def test_api_error_is_attached_to_task_without_playback():
    remote = SimpleNamespace(synthesize=AsyncMock(side_effect=RemoteVoiceError("API ключ не принят", code="http.401")))
    controller = AudioController.__new__(AudioController)
    controller.settings = {}
    controller.event_bus = Mock()
    controller._update_task_failed_voiceover = Mock()
    with patch("controllers.audio_controller.use", return_value=remote), \
         patch("controllers.audio_controller.AudioHandler.handle_voice_file", new_callable=AsyncMock) as play:
        asyncio.run(controller._synthesize_and_deliver("prepared", "original", "task", method="API"))
    play.assert_not_awaited()
    assert controller._update_task_failed_voiceover.call_args.args[0] == "task"
    assert "API ключ не принят" in controller._update_task_failed_voiceover.call_args.args[1]
