from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.gemini_provider import GeminiProvider


class GeminiUsageTests(unittest.TestCase):
    """Ответ Gemini несёт метрики кэша и мыслей — без них статистика врёт нулями."""

    def _usage(self, usage_meta):
        return GeminiProvider._extract_usage(GeminiProvider, {"usageMetadata": usage_meta})

    def test_implicit_cache_hit_is_reported(self) -> None:
        # Живой ответ gemini-3.1-flash-lite: неявный кэш без explicit cachedContent.
        usage = self._usage({
            "promptTokenCount": 12114,
            "candidatesTokenCount": 148,
            "totalTokenCount": 12262,
            "cachedContentTokenCount": 3583,
            "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 2939}],
        })

        self.assertEqual(usage.prompt_tokens, 12114)
        self.assertEqual(usage.cached_prompt_tokens, 3583)

    def test_cache_miss_reports_zero_not_none(self) -> None:
        usage = self._usage({
            "promptTokenCount": 12087,
            "candidatesTokenCount": 154,
            "totalTokenCount": 12241,
        })

        self.assertEqual(usage.cached_prompt_tokens, 0)

    def test_thinking_tokens_land_in_reasoning(self) -> None:
        usage = self._usage({
            "promptTokenCount": 900,
            "candidatesTokenCount": 120,
            "totalTokenCount": 1420,
            "thoughtsTokenCount": 400,
        })

        self.assertEqual(usage.reasoning_tokens, 400)

    def test_snake_case_aliases_are_accepted(self) -> None:
        usage = self._usage({
            "prompt_token_count": 500,
            "candidates_token_count": 50,
            "total_token_count": 550,
            "cached_content_token_count": 128,
        })

        self.assertEqual(usage.prompt_tokens, 500)
        self.assertEqual(usage.cached_prompt_tokens, 128)


if __name__ == "__main__":
    unittest.main()
