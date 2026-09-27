"""Tests for the semantic ChatAPI boundary introduced for 0.1.1."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.chat_controller import ChatController
from core.chat_api import ChatAPI


class _ChatService:
    def __init__(self):
        self.calls = []

    def reply(self, **kwargs):
        self.calls.append(("reply", kwargs))
        return True

    def react(self, **kwargs):
        self.calls.append(("react", kwargs))
        return True

    def initiate(self, **kwargs):
        self.calls.append(("initiate", kwargs))
        return True


class ChatApiFacadeTests(unittest.TestCase):
    def test_static_facade_delegates_to_registered_chat_service(self) -> None:
        service = _ChatService()
        with patch("core.chat_api.use", return_value=service):
            self.assertTrue(
                ChatAPI.react(
                    character_id="Mita",
                    instruction="event",
                    visible=True,
                )
            )

        self.assertEqual(service.calls[0][0], "react")
        self.assertEqual(service.calls[0][1]["character_id"], "Mita")
        self.assertEqual(service.calls[0][1]["instruction"], "event")


class ChatControllerSemanticApiTests(unittest.TestCase):
    def _controller(self, **settings):
        controller = object.__new__(ChatController)
        controller.settings = settings
        return controller

    def test_visible_react_owns_admission_and_l2_policy(self) -> None:
        controller = self._controller(REACT_ENABLED=True, REACT_L2_ENABLED=True)
        with patch.object(controller, "_submit_semantic_turn", return_value=True) as submit:
            self.assertTrue(
                controller.react(
                    character_id="Mita",
                    instruction="game event",
                    visible=True,
                )
            )

        kwargs = submit.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "react")
        self.assertEqual(kwargs["policy"].react_level, 2)
        self.assertEqual(kwargs["instruction"] if "instruction" in kwargs else kwargs["system_input"], "game event")

    def test_react_is_dropped_when_global_reactions_are_disabled(self) -> None:
        controller = self._controller(REACT_ENABLED=False, REACT_L2_ENABLED=True)
        with patch.object(controller, "_submit_semantic_turn") as submit:
            self.assertFalse(
                controller.react(
                    character_id="Mita",
                    instruction="game event",
                    visible=True,
                )
            )
        submit.assert_not_called()

    def test_react_is_dropped_when_requested_level_is_disabled(self) -> None:
        controller = self._controller(REACT_ENABLED=True, REACT_L2_ENABLED=False)
        with patch.object(controller, "_submit_semantic_turn") as submit:
            self.assertFalse(
                controller.react(
                    character_id="Mita",
                    instruction="game event",
                    visible=True,
                )
            )
        submit.assert_not_called()

    def test_reply_requires_message_id(self) -> None:
        controller = self._controller()
        with self.assertRaises(ValueError):
            controller.reply(character_id="Mita", message_id="")

    def test_reply_maps_message_id_to_existing_origin_message_id(self) -> None:
        controller = self._controller()
        with patch.object(controller, "_submit_semantic_turn", return_value=True) as submit:
            self.assertTrue(
                controller.reply(
                    character_id="Mita",
                    message_id="in:123",
                    user_input="hello",
                )
            )

        kwargs = submit.call_args.kwargs
        self.assertEqual(kwargs["origin_message_id"], "in:123")
        self.assertEqual(kwargs["event_type"], "chat")
        self.assertIsNone(kwargs["policy"].react_level)


if __name__ == "__main__":
    unittest.main()
