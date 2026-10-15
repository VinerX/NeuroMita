import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from handlers.llm_providers.chatgpt_plan_provider import ChatGPTPlanProvider


class ChatGPTPlanProviderTests(unittest.TestCase):
    def test_extracts_structured_subscription_error_code(self):
        body = '{"error":{"code":"subscription_sharing_usage_limit_exceeded","message":"limit"}}'
        self.assertEqual(
            ChatGPTPlanProvider._error_code_from_body(body),
            "subscription_sharing_usage_limit_exceeded",
        )

    def test_error_code_parser_tolerates_direct_admission_body(self):
        self.assertEqual(ChatGPTPlanProvider._error_code_from_body('{"detail":"unavailable"}'), "")
        self.assertEqual(ChatGPTPlanProvider._error_code_from_body("not-json"), "")


if __name__ == "__main__":
    unittest.main()
