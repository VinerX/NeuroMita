from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from game_connections.handlers.actions.get_music_beats import GetMusicBeatsAction
from game_connections.handlers.registry import RequestContext


class _FakeEventBus:
    def __init__(self, settings: dict[str, object]):
        self._settings = dict(settings)

    def emit_and_wait(self, _event_name, payload=None, timeout=None):
        key = (payload or {}).get("key")
        default = (payload or {}).get("default")
        return [self._settings.get(key, default)]


class _FakeServer:
    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, writer, payload):
        self.messages.append(payload)


class GetMusicBeatsActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_python_analysis_when_file_transfer_disabled(self):
        action = GetMusicBeatsAction()
        server = _FakeServer()
        ctx = RequestContext(
            server=server,
            client_id="client_1",
            writer=object(),
            event_bus=_FakeEventBus(
                {
                    "BEAT_SYNC_ENABLED": True,
                    "BEAT_SYNC_AUTO_INSTALL": True,
                    "BEAT_SYNC_USE_FILE_TRANSFER": False,
                }
            ),
        )

        with patch(
            "game_connections.handlers.actions.get_music_beats.get_beat_service",
            side_effect=AssertionError("beat service must not be called when file transfer is disabled"),
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

        self.assertEqual(len(server.messages), 1)
        self.assertEqual(server.messages[0]["type"], "music_beats_error")
        self.assertEqual(
            server.messages[0]["body"]["error"],
            "BEAT_SYNC_USE_FILE_TRANSFER is OFF",
        )

    async def test_missing_setting_defaults_to_enabled_file_transfer(self):
        action = GetMusicBeatsAction()
        server = _FakeServer()
        ctx = RequestContext(
            server=server,
            client_id="client_1",
            writer=object(),
            event_bus=_FakeEventBus(
                {
                    "BEAT_SYNC_ENABLED": True,
                    "BEAT_SYNC_AUTO_INSTALL": True,
                }
            ),
        )

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
