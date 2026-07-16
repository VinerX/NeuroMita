"""Размышления не должны утекать в текст ответа.

Регресс, ради которого тесты и написаны: у reasoning-чанка нет поля content,
и `delta.get("content") or delta.get("reasoning_content")` сваливался на мысли,
склеивая их с ответом без разделителя. На LM Studio + Gemma 4 это выглядело так:
148 чанков размышлений, потом 2 чанка ответа — и всё одной простынёй в чате.
"""
import json
import sys
import types
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from handlers.llm_providers.base import LLMRequest, StreamChannel
from handlers.llm_providers.openai_http_base import OpenAIHTTPProviderBase


class _FakeResponse:
    """Минимальный стенд под SSE-поток OpenAI-совместимого провайдера."""

    def __init__(self, deltas):
        self._deltas = deltas
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        for delta in self._deltas:
            chunk = {"choices": [{"delta": delta, "finish_reason": None}], "model": "gemma-4-12b"}
            yield f"data: {json.dumps(chunk)}".encode("utf-8")
        yield b"data: [DONE]"

    def close(self):
        self.closed = True


class _Provider(OpenAIHTTPProviderBase):
    name = "test"

    def is_applicable(self, req):
        return True


def _req():
    return LLMRequest(model="gemma-4-12b", messages=[])


class StreamReasoningSplitTests(unittest.TestCase):
    def setUp(self):
        self.provider = _Provider()

    def _run(self, deltas):
        seen = []
        resp = _FakeResponse(deltas)
        result = self.provider._handle_stream(
            resp, "http://127.0.0.1:1234/v1/chat/completions", _req(),
            lambda text, channel: seen.append((channel, text)),
        )
        return result, seen

    def test_reasoning_never_lands_in_text(self):
        # Так реально отдаёт LM Studio: сперва мысли, затем ответ.
        result, seen = self._run([
            {"reasoning_content": "Прикину, "},
            {"reasoning_content": "сколько будет."},
            {"content": "51"},
        ])

        self.assertEqual(result.text, "51")
        self.assertEqual(result.reasoning, "Прикину, сколько будет.")

    def test_channels_are_reported_separately(self):
        _, seen = self._run([
            {"reasoning_content": "думаю"},
            {"content": "ответ"},
        ])

        self.assertEqual(seen, [
            (StreamChannel.REASONING, "думаю"),
            (StreamChannel.CONTENT, "ответ"),
        ])

    def test_content_and_reasoning_in_one_delta_do_not_merge(self):
        result, seen = self._run([{"content": "ответ", "reasoning_content": "мысль"}])

        self.assertEqual(result.text, "ответ")
        self.assertEqual(result.reasoning, "мысль")
        self.assertIn((StreamChannel.REASONING, "мысль"), seen)

    def test_reasoning_only_stream_rescues_the_answer(self):
        # Сломанные сборки Qwen3 кладут весь ответ в reasoning_content и
        # оставляют content пустым — иначе игрок получит пустоту.
        result, _ = self._run([{"reasoning_content": "весь ответ тут"}])

        self.assertEqual(result.text, "весь ответ тут")
        self.assertIsNone(result.reasoning)

    def test_empty_stream_reports_error(self):
        result, _ = self._run([{}])

        self.assertIsNone(result.text)
        self.assertIsNone(result.reasoning)


class NonStreamReasoningSplitTests(unittest.TestCase):
    def setUp(self):
        self.provider = _Provider()

    def test_reasoning_kept_out_of_text(self):
        content, reasoning = self.provider._resolve_content_and_reasoning("51", "прикидываю")

        self.assertEqual(content, "51")
        self.assertEqual(reasoning, "прикидываю")

    def test_answer_in_reasoning_is_rescued(self):
        content, reasoning = self.provider._resolve_content_and_reasoning("", "ответ сюда")

        self.assertEqual(content, "ответ сюда")
        self.assertEqual(reasoning, "")


if __name__ == "__main__":
    unittest.main()
