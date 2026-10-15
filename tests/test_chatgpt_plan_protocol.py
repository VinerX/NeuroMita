import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from handlers.llm_providers.chatgpt_plan_protocol import (
    build_responses_payload,
    normalize_responses_usage,
    parse_sse_data_line,
)


class ChatGPTPlanProtocolTests(unittest.TestCase):
    def test_payload_enforces_preview_contract_and_maps_system_to_developer(self):
        payload = build_responses_payload(
            "gpt-6.1-sol",
            [
                {"role": "system", "content": "System rules"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        )
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertIs(payload["store"], False)
        self.assertIs(payload["stream"], True)
        self.assertEqual(payload['input'][0]['content'], 'System rules')
        self.assertEqual([item["role"] for item in payload["input"]], ["developer", "user", "assistant"])
        for forbidden in (
            "temperature", "top_p", "max_output_tokens", "previous_response_id",
            "background", "conversation", "metadata", "user",
        ):
            self.assertNotIn(forbidden, payload)

    def test_usage_maps_cache_and_reasoning(self):
        usage = normalize_responses_usage({
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {"cached_tokens": 60},
            "output_tokens_details": {"reasoning_tokens": 7},
        })
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["total_tokens"], 120)
        self.assertEqual(usage["cached_prompt_tokens"], 60)
        self.assertEqual(usage["reasoning_tokens"], 7)

    def test_sse_parser_ignores_non_data_and_done(self):
        self.assertIsNone(parse_sse_data_line("event: response.output_text.delta"))
        self.assertIsNone(parse_sse_data_line("data: [DONE]"))
        self.assertEqual(
            parse_sse_data_line('data: {"type":"response.output_text.delta","delta":"hi"}'),
            {"type": "response.output_text.delta", "delta": "hi"},
        )


if __name__ == "__main__":
    unittest.main()
