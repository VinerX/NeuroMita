from unittest.mock import Mock

from controllers.telegram_controller import TelegramController
from core.telegram_credentials import telegram_credentials_complete


def test_missing_credentials_cannot_start_or_consume_connection_cooldown():
    controller = TelegramController.__new__(TelegramController)
    controller.silero_connected = False
    controller._connecting = False
    controller.api_id = "123456"
    controller.api_hash = " "
    controller.phone = "+79991234567"
    controller._last_start_attempt_ts = 0
    controller._tg_settings_snapshot = lambda: {}
    controller.start_silero_async = Mock()
    assert not controller.request_start(force=True, source="test")
    assert not controller._connecting
    assert controller._last_start_attempt_ts == 0
    controller.start_silero_async.assert_not_called()
    controller.api_hash = "hash"
    assert controller.request_start(force=True, source="test")
    controller.start_silero_async.assert_called_once()


def test_credential_gate_rejects_whitespace():
    assert not telegram_credentials_complete(
        {
            "NM_TELEGRAM_API_ID": "123456",
            "NM_TELEGRAM_API_HASH": "hash",
            "NM_TELEGRAM_PHONE": "\t ",
        }
    )
