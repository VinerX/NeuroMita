"""Проверки служебного состояния, добавляемого в контекст генерации."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.prompt_controller import PromptController


class PromptSystemStateTests(unittest.TestCase):
    def test_remote_sandbox_state_is_explicit(self):
        message = PromptController._format_system_state_message(
            remote_only=True,
            voice_enabled=True,
            voice_method="Local",
            microphone_enabled=False,
            image_status="disabled",
        )

        content = message["content"]
        self.assertEqual(message["role"], "system")
        self.assertIn("communicating with the Player online through the NeuroMita computer program", content)
        self.assertIn("they may come to your home later", content)
        self.assertIn("Your voice (TTS): enabled; method: Local. This is your voice.", content)
        self.assertIn("The Player's voice (microphone): disabled.", content)
        self.assertIn("Your sight (image recognition): disabled.", content)
        self.assertNotIn("Structured output", content)

    def test_connected_state_does_not_claim_remote_only(self):
        message = PromptController._format_system_state_message(
            remote_only=False,
            voice_enabled=False,
            voice_method="Local",
            microphone_enabled=True,
            image_status="enabled",
        )

        content = message["content"]
        self.assertIn("while the game runtime is connected", content)
        self.assertIn("Your voice (TTS): disabled.", content)
        self.assertIn("The Player's voice (microphone): enabled.", content)
        self.assertIn("Your sight (image recognition): enabled.", content)
        self.assertNotIn("it is separate from your own voice", content)


if __name__ == "__main__":
    unittest.main()
