from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.services import services
from game_connections.handlers.actions.get_music_beats import GetMusicBeatsAction
from game_connections.handlers.registry import RequestContext
from services.contracts import SettingsService


class _StubSettings(SettingsService):
    """Настройки читаются через SettingsService, а не через шину событий."""

    def __init__(self, settings: dict[str, object]):
        self._settings = dict(settings)

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        self._settings[key] = value

    def save_settings(self):
        pass

    def update(self, key, value):
        self.set(key, value)


def _install_settings(settings: dict[str, object]) -> None:
    services().register(SettingsService, _StubSettings(settings), replace=True)


class _FakeServer:
    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, writer, payload):
        self.messages.append(payload)


class GetMusicBeatsActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_file_transfer_flag_no_longer_blocks_analysis(self):
        action = GetMusicBeatsAction()
        server = _FakeServer()
        ctx = RequestContext(
            server=server,
            client_id="client_1",
            writer=object(),
            event_bus=SimpleNamespace(),
        )
        _install_settings({"BEAT_SYNC_ENABLED": True, "BEAT_SYNC_USE_FILE_TRANSFER": False})

        fake_result = SimpleNamespace(
            duration=12.5,
            beats=[{"time": 1.0, "confidence": 0.9}],
            method="unit_test",
            bpm_estimate=120.0,
        )
        fake_service = SimpleNamespace(extract_beats=AsyncMock(return_value=fake_result))

        with patch(
            "game_connections.handlers.actions.get_music_beats.get_beat_service",
            return_value=fake_service,
        ):
            await action.handle(
                {
                    "audio_path": "C:/tmp/test.wav",
                    "track_name": "test",
                    "request_id": "req_1",
                    "stream": False,
                },
                ctx,
            )

        self.assertEqual(len(server.messages), 2)
        self.assertEqual(server.messages[0]["type"], "music_beats_job_started")
        self.assertEqual(server.messages[1]["type"], "music_beats_ready")
        fake_service.extract_beats.assert_awaited_once()

    async def test_missing_setting_defaults_to_enabled_file_transfer(self):
        action = GetMusicBeatsAction()
        server = _FakeServer()
        ctx = RequestContext(
            server=server,
            client_id="client_1",
            writer=object(),
            event_bus=SimpleNamespace(),
        )
        _install_settings({"BEAT_SYNC_ENABLED": True})

        fake_result = SimpleNamespace(
            duration=12.5,
            beats=[{"time": 1.0, "confidence": 0.9}],
            method="unit_test",
            bpm_estimate=120.0,
        )
        fake_service = SimpleNamespace(extract_beats=AsyncMock(return_value=fake_result))

        with patch(
            "game_connections.handlers.actions.get_music_beats.get_beat_service",
            return_value=fake_service,
        ):
            await action.handle(
                {
                    "audio_path": "C:/tmp/test.wav",
                    "track_name": "test",
                    "request_id": "req_2",
                    "stream": False,
                },
                ctx,
            )

        self.assertEqual(len(server.messages), 2)
        self.assertEqual(server.messages[0]["type"], "music_beats_job_started")
        self.assertEqual(server.messages[1]["type"], "music_beats_ready")
        fake_service.extract_beats.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
