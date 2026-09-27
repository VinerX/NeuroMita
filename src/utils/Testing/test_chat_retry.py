from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.chat_controller import ChatController
from core.executors import PoolSaturated, Pools
from core.events import Events


class _EventBusStub:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    def emit(self, event_name: str, data: dict) -> None:
        self.emitted.append((event_name, data))


class ChatRetryTests(unittest.TestCase):
    def _controller(self) -> tuple[ChatController, _EventBusStub]:
        controller = ChatController.__new__(ChatController)
        bus = _EventBusStub()
        controller.event_bus = bus
        controller._last_ui_request = {"req_id": "newest", "character_id": "Crazy"}
        controller._ui_requests_by_message_id = {
            "in:older": {"req_id": "older", "character_id": "Crazy"},
        }
        return controller, bus

    def test_retry_uses_request_matched_to_clicked_failed_message(self) -> None:
        controller, bus = self._controller()

        controller._on_retry_last(SimpleNamespace(data={
            "message_id": "in:older",
            "character_id": "Crazy",
        }))

        self.assertEqual(
            bus.emitted,
            [
                (Events.GUI.CLEAR_CHAT_MESSAGE_ERROR, {
                    "message_id": "in:older",
                    "character_id": "Crazy",
                }),
                (Events.Chat.SEND_MESSAGE, {"req_id": "older", "character_id": "Crazy"}),
            ],
        )

    def test_retry_does_not_substitute_newest_request_when_message_id_is_unknown(self) -> None:
        controller, bus = self._controller()

        controller._on_retry_last(SimpleNamespace(data={
            "message_id": "in:missing",
            "character_id": "Crazy",
        }))

        self.assertEqual(bus.emitted, [])

    def test_request_without_req_id_does_not_displace_retryable_ui_request(self) -> None:
        controller, _bus = self._controller()
        submitted = []
        controller._ensure_perf_trace = lambda _data: "trace-1"
        controller._resolve_player_message_source_transition = lambda _source: (None, None)
        controller._normalize_character_id = lambda data: str(data.get("character_id") or "")
        controller._normalize_sender = lambda _data: "Player"
        controller._normalize_participants = lambda _value: []
        controller._submit_request = lambda **kwargs: submitted.append(kwargs)

        controller._on_send_message(SimpleNamespace(data={
            "user_input": "regenerate this",
            "character_id": "Crazy",
        }))

        self.assertEqual(
            controller._ui_requests_by_message_id,
            {"in:older": {"req_id": "older", "character_id": "Crazy"}},
        )
        self.assertEqual(controller._last_ui_request["req_id"], "newest")
        self.assertEqual(submitted[0]["req_id"], None)

    def test_queue_rejection_without_req_id_does_not_invent_message_id(self) -> None:
        controller, bus = self._controller()
        controller._register_generation = lambda *_args: None
        controller._finish_generation = lambda *_args: None

        class _SaturatedRegistry:
            @staticmethod
            def try_submit(*_args, **_kwargs):
                raise PoolSaturated(Pools.GENERATION, 1)

        with patch("controllers.chat_controller.executors", return_value=_SaturatedRegistry()), patch(
            "controllers.chat_controller.performance_traces",
            return_value=SimpleNamespace(finish=lambda *_args, **_kwargs: None),
        ):
            controller._submit_request(req_id="", character_id="Crazy")

        self.assertEqual(
            bus.emitted[-1],
            (Events.Model.ON_FAILED_RESPONSE, {
                "error": "Слишком много запросов одновременно. Подождите ответа.",
                "message_id": "",
                "character_id": "Crazy",
            }),
        )


if __name__ == "__main__":
    unittest.main()
