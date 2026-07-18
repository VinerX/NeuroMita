"""Тесты оценки токенов ContextCounter, включая работу БЕЗ tiktoken.

В рантайме игры tiktoken часто недоступен (отдельная зависимость + первый вызов
tiktoken тянет данные кодировки из сети). Раньше без него счётчик отдавал 0 и в
просмотрщике не было ни процентов, ни оценок. Проверяем, что теперь оценка всегда
есть — по эвристике, если токенайзера нет.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.context_counter import ContextCounter
from handlers.chat_handler import _compute_token_usage


def _heuristic_counter() -> ContextCounter:
    """Счётчик, принудительно без tiktoken (эмулируем рантайм игры)."""
    c = ContextCounter()
    c._has_tokenizer = False
    c._tokenizer = None
    return c


class HeuristicFallbackTests(unittest.TestCase):
    def test_available_without_tokenizer(self):
        c = _heuristic_counter()
        self.assertTrue(c.available)          # оценка есть всегда
        self.assertFalse(c.is_exact)          # но не точная
        self.assertEqual(c.method, "heuristic")

    def test_heuristic_nonzero_for_text(self):
        c = _heuristic_counter()
        n = c.count_tokens([{"role": "system", "content": "You are a helpful assistant."}])
        self.assertGreater(n, 0)

    def test_heuristic_russian_not_underestimated_vs_english(self):
        # Кириллица дробится мельче — надбавка за не-ASCII должна поднять оценку
        # относительно наивных «символы/4».
        c = _heuristic_counter()
        ru = "Привет, как твои дела сегодня вечером на самом деле"
        naive = len(ru) / 4.0
        self.assertGreater(c.count_tokens([{"role": "user", "content": ru}]), naive)

    def test_images_not_counted_but_text_is(self):
        c = _heuristic_counter()
        msg = {"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": "<image redacted: 40000 chars>"}},
        ]}
        text_only = c.count_tokens([{"role": "user", "content": [{"type": "text", "text": "what is this?"}]}])
        with_image = c.count_tokens([msg])
        self.assertEqual(text_only, with_image)  # картинка не добавляет токенов
        self.assertGreater(with_image, 0)

    def test_tool_calls_counted(self):
        c = _heuristic_counter()
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "get_x", "args": {"a": 1}}]}
        self.assertGreater(c.count_tokens([msg]), 0)

    def test_empty_and_nonlist(self):
        c = _heuristic_counter()
        self.assertEqual(c.count_tokens([]), 0)
        self.assertEqual(c.count_tokens([{"role": "user", "content": ""}]), 0)


class ComputeUsageWithoutTokenizerTests(unittest.TestCase):
    """_compute_token_usage должен давать разбивку даже без tiktoken."""

    def setUp(self):
        # Подменяем ContextCounter внутри chat_handler на heuristic-only.
        import managers.context_counter as cc
        self._orig = cc.ContextCounter

        class _HeuristicOnly(cc.ContextCounter):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._has_tokenizer = False
                self._tokenizer = None

        cc.ContextCounter = _HeuristicOnly

    def tearDown(self):
        import managers.context_counter as cc
        cc.ContextCounter = self._orig

    def test_breakdown_present_without_tokenizer(self):
        messages = [
            {"role": "system", "content": "You are Crazy Mita, playful and controlling."},
            {"role": "system", "content": "<active_memory>\nN:1 player likes cats</active_memory>"},
            {"role": "system", "content": "[MiSide World State]\nThe player is in the kitchen."},
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": [{"type": "text", "text": "what is your name?"}]},
        ]
        usage = _compute_token_usage(messages)
        self.assertTrue(usage["available"])
        self.assertFalse(usage["exact"])
        self.assertEqual(usage["method"], "heuristic")
        self.assertGreater(usage["estimated_total"], 0)
        self.assertEqual(len(usage["per_message"]), len(messages))
        self.assertEqual(usage["estimated_total"], sum(usage["estimated_by_section"].values()))
        self.assertEqual(usage["estimated_total"], sum(m["estimated_tokens"] for m in usage["per_message"]))
        for expected in ["character prompts", "memories", "MiSide World State", "history", "user input"]:
            self.assertIn(expected, usage["estimated_by_section"])


if __name__ == "__main__":
    unittest.main()
