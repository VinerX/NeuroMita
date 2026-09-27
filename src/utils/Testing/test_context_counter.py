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
from utils.context_token_stats import (
    classify_message_section as _classify_message_section,
    compute_token_usage as _compute_token_usage,
)


class UnityRuntimeSectionTests(unittest.TestCase):
    """Unity-рантайм ([RUNTIME EVENT] ...) — активный контекст, не история."""

    def test_converted_unity_event_is_not_history(self):
        # Провайдер превращает role=event в role=user с префиксом [RUNTIME EVENT];
        # без учёта текста такое сообщение уезжало в «историю».
        caps = {"role": "user", "content": "[RUNTIME EVENT] [Unity Runtime Capabilities]\nlight,music"}
        events = {"role": "user", "content": "[RUNTIME EVENT] [Unity Runtime Events]\n- door opened"}
        self.assertEqual(_classify_message_section(caps, is_last_user=False), "Unity runtime")
        self.assertEqual(_classify_message_section(events, is_last_user=False), "Unity runtime")

    def test_static_unity_contract_before_history_is_prompt(self):
        # Rules/Intent теперь в статике промпта (до истории) → часть промпта;
        # если после истории — рантайм-контекст.
        rules = {"role": "system", "content": "[Unity Runtime Rules]\nchannels"}
        intent = {"role": "system", "content": "[Unity Intent Contract]\nintents"}
        self.assertEqual(_classify_message_section(rules, is_last_user=False, seen_dialogue=False), "Unity contract")
        self.assertEqual(_classify_message_section(intent, is_last_user=False, seen_dialogue=False), "Unity contract")
        self.assertEqual(_classify_message_section(rules, is_last_user=False, seen_dialogue=True), "Unity runtime")

    def test_dynamic_unity_capabilities_events_are_context(self):
        caps = {"role": "user", "content": "[RUNTIME EVENT] [Unity Runtime Capabilities]\nWave"}
        events = {"role": "user", "content": "[RUNTIME EVENT] [Unity Runtime Events]\n- door opened"}
        self.assertEqual(_classify_message_section(caps, is_last_user=False, seen_dialogue=True), "Unity runtime")
        self.assertEqual(_classify_message_section(events, is_last_user=False, seen_dialogue=True), "Unity runtime")

    def test_converted_world_state_keeps_its_section(self):
        ws = {"role": "user", "content": "[RUNTIME EVENT] [NeuroMita World State]\nkitchen"}
        self.assertEqual(_classify_message_section(ws, is_last_user=False), "NeuroMita World State")

    def test_real_dialogue_still_history_and_input(self):
        self.assertEqual(_classify_message_section({"role": "user", "content": "hi"}, is_last_user=False), "history")
        self.assertEqual(_classify_message_section({"role": "user", "content": "hi"}, is_last_user=True), "user input")

    def test_unmarked_system_before_history_is_prompt_after_is_history(self):
        # Безмаркерное system-сообщение до истории — промпт персонажа; после
        # начала истории (idle «игрок молчит») — история хода, НЕ активный
        # контекст (его мы явно не задавали).
        silence = {"role": "system", "content": "The player has been silent for 90 seconds. React naturally."}
        self.assertEqual(_classify_message_section(silence, is_last_user=False, seen_dialogue=False), "character prompts")
        self.assertEqual(_classify_message_section(silence, is_last_user=False, seen_dialogue=True), "history")

    def test_designated_context_blocks_stay_context(self):
        # Явно оформленные нами блоки остаются активным контекстом даже после истории.
        for content, expected in [
            ("<active_memory>\nlikes cats</active_memory>", "memories"),
            # Острова памяти идут своим сообщением и ведут блок своим тегом —
            # без этого маркера они «выезжали» в историю (start-of-line match).
            ("<memory_islands>\n[Relationship] N:1 friends</memory_islands>", "memories"),
            ("[System State]\noffline", "System State"),
            ("[Current State]\nDate", "System State"),
            ("[NeuroMita World State]\nkitchen", "NeuroMita World State"),
            ("[Character World Context]\nyour home", "Character World Context"),
            ("[Character Environment]\nready", "Character Environment"),
            ("[WORKING STATE]\nFocus: test", "working state"),
            ("[RECENT ACTIONS BEFORE SUMMARY BOUNDARY]\n- animation: Dance_07", "retained actions"),
            ("[REQUESTED ACTIONS THIS TURN]\n- animation: Dance_07", "requested actions"),
        ]:
            self.assertEqual(
                _classify_message_section({"role": "system", "content": content}, is_last_user=False, seen_dialogue=True),
                expected,
            )


class IdleTurnInputTests(unittest.TestCase):
    """В idle-ходе триггер — idle-событие «игрок молчит»: оно последнее и по
    смыслу заменяет ввод игрока, поэтому идёт в «Ввод игрока» (внизу), а прошлые
    реплики остаются историей (её блок не рвётся)."""

    def test_idle_event_is_current_input_at_bottom(self):
        # Реальная форма: провайдер конвертирует idle-событие в role="user" с
        # префиксом [RUNTIME EVENT] (см. message_preprocessor).
        messages = [
            {"role": "system", "content": "You are Crazy Mita." * 40},
            {"role": "system", "content": "[HISTORY SUMMARY]\nearlier"},
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hi"},
            {"role": "system", "content": "<active_memory>\nlikes cats</active_memory>"},
            {"role": "user", "content": "[RUNTIME EVENT] The player has been silent for 90 seconds. React naturally to this silence."},
        ]
        usage = _compute_token_usage(messages)
        sections = [m["section"] for m in usage["per_message"]]
        self.assertEqual(sections[2], "history")      # прошлая реплика игрока
        self.assertEqual(sections[4], "memories")     # активный контекст не тронут
        self.assertEqual(sections[-1], "user input")  # idle-событие = текущий ввод, внизу

    def test_idle_event_as_raw_event_role_also_input(self):
        # Провайдер с кастомным обработчиком оставляет role="event" (без префикса).
        messages = [
            {"role": "system", "content": "You are Crazy Mita." * 40},
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hi"},
            {"role": "event", "content": "The player has been silent for 90 seconds."},
        ]
        usage = _compute_token_usage(messages)
        sections = [m["section"] for m in usage["per_message"]]
        self.assertEqual(sections[1], "history")      # отвеченная реплика игрока
        self.assertEqual(sections[-1], "user input")  # idle-событие внизу

    def test_normal_turn_last_user_is_input(self):
        messages = [
            {"role": "system", "content": "You are Crazy Mita." * 40},
            {"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hi"},
            {"role": "system", "content": "<active_memory>\nlikes cats</active_memory>"},
            {"role": "user", "content": "what is your name?"},
        ]
        usage = _compute_token_usage(messages)
        sections = [m["section"] for m in usage["per_message"]]
        self.assertEqual(sections[-1], "user input")
        self.assertEqual(sections[1], "history")  # earlier user answered → history


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
            {"role": "system", "content": "[NeuroMita World State]\nThe player is in the kitchen."},
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
        for expected in ["character prompts", "memories", "NeuroMita World State", "history", "user input"]:
            self.assertIn(expected, usage["estimated_by_section"])


if __name__ == "__main__":
    unittest.main()
