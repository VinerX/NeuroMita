from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.base import LLMUsage
from managers.finetune_collector import FineTuneCollector


def _request() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        model="gemini-3.1-flash-lite",
        provider_name="gemini",
        protocol_id="google_gemini_default",
        dialect_id=None,
        extra={},
        messages=[{"role": "user", "content": "Привет"}],
    )


class SampleUsageTests(unittest.TestCase):
    """Просмотр контекста открывает сохранённую выборку: без usage там нет
    ни фактического input, ни кэша — только локальная оценка."""

    def _collector(self) -> FineTuneCollector:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        collector = FineTuneCollector(base_dir=tmp.name)
        collector.is_enabled = lambda: True  # type: ignore[method-assign]
        return collector

    def _saved(self, usage) -> dict:
        collector = self._collector()
        collector.save_sample(
            req=_request(),
            response_text="ответ",
            character_id="Crazy",
            character_name="Crazy Mita",
            usage=usage,
        )
        return collector.load_samples()[0]

    def test_usage_is_stored_with_sample(self) -> None:
        record = self._saved(LLMUsage(
            prompt_tokens=12054,
            completion_tokens=148,
            total_tokens=12202,
            cached_prompt_tokens=7165,
        ))

        self.assertEqual(record["usage"]["prompt_tokens"], 12054)
        self.assertEqual(record["usage"]["cached_prompt_tokens"], 7165)

    def test_missing_usage_keeps_field_present(self) -> None:
        record = self._saved(None)

        self.assertIn("usage", record)
        self.assertIsNone(record["usage"])


class UsagePayloadTests(unittest.TestCase):
    def test_payload_carries_cache_and_cost(self) -> None:
        payload = LLMUsage(
            prompt_tokens=100,
            cached_prompt_tokens=80,
            cache_write_tokens=20,
            cost=0.0012,
            cost_currency="USD",
            cost_source="pricing",
        ).to_payload()

        self.assertEqual(payload["cached_prompt_tokens"], 80)
        self.assertEqual(payload["cache_write_tokens"], 20)
        self.assertEqual(payload["cost"], 0.0012)
        self.assertEqual(payload["cost_currency"], "USD")


if __name__ == "__main__":
    unittest.main()
