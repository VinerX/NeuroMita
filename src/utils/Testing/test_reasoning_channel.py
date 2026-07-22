"""Размышления не должны утекать в текст ответа.

Регресс, ради которого тесты и написаны: reasoning-дельта не несёт поля content,
и наивное `delta.get("content") or delta.get("reasoning_content")` сваливалось на
мысли, склеивая их с ответом без разделителя. На LM Studio + Gemma 4 это
выглядело так: 302 чанка размышлений, потом 82 чанка ответа — и всё одной
простынёй в чате.

Второй регресс, который тут закреплён: мысли нельзя протаскивать <think>-тегами
внутри text — подписчик не должен парсить строку, чтобы понять, что ему пришло.
"""
import json
import sys
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import httpx

from handlers.llm_providers.base import LLMRequest, StreamChannel
from handlers.llm_providers.common_provider import CommonProvider
from handlers.llm_providers.http_transport import LLMHttpTransport
from handlers.llm_providers.streaming import StreamAccumulator


def _sse(*deltas: dict) -> str:
    body = ""
    for delta in deltas:
        chunk = {"model": "gemma-4-12b", "choices": [{"delta": delta, "finish_reason": None}]}
        body += f"data: {json.dumps(chunk)}\n\n"
    body += 'data: {"model":"gemma-4-12b","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    body += "data: [DONE]\n\n"
    return body


class StreamChannelSplitTests(unittest.TestCase):
    """Провайдер разводит каналы на всём пути от SSE до LLMResponse."""

    def _stream(self, *deltas: dict):
        seen: list[tuple[StreamChannel, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(*deltas),
            )

        transport = LLMHttpTransport(
            enable_http2=False,
            client_factory=lambda _p, _h: httpx.Client(transport=httpx.MockTransport(handler)),
        )
        try:
            provider = CommonProvider(http_transport=transport)
            req = LLMRequest(
                model="gemma-4-12b",
                messages=[{"role": "user", "content": "hi"}],
                api_url="http://127.0.0.1:1234/v1/chat/completions",
                provider_name="common",
                stream=True,
                stream_cb=lambda text, channel: seen.append((channel, text)),
            )
            return provider.generate(req), seen
        finally:
            transport.close()

    def test_reasoning_never_lands_in_text(self):
        # Так реально отдаёт LM Studio: сперва мысли, затем ответ.
        response, _ = self._stream(
            {"reasoning_content": "Прикину, "},
            {"reasoning_content": "сколько будет."},
            {"content": "51"},
        )

        self.assertEqual(response.text, "51")
        self.assertEqual(response.reasoning, "Прикину, сколько будет.")

    def test_channels_are_reported_separately(self):
        _, seen = self._stream({"reasoning_content": "думаю"}, {"content": "ответ"})

        self.assertEqual(
            seen,
            [(StreamChannel.REASONING, "думаю"), (StreamChannel.CONTENT, "ответ")],
        )

    def test_content_and_reasoning_in_one_delta_do_not_merge(self):
        response, seen = self._stream({"content": "ответ", "reasoning_content": "мысль"})

        self.assertEqual(response.text, "ответ")
        self.assertEqual(response.reasoning, "мысль")
        self.assertIn((StreamChannel.REASONING, "мысль"), seen)

    def test_text_carries_no_think_tags(self):
        response, _ = self._stream({"reasoning_content": "мысль"}, {"content": "ответ"})

        self.assertNotIn("<think>", response.text or "")


class AccumulatorRescueTests(unittest.TestCase):
    def test_answer_left_in_reasoning_channel_is_rescued(self):
        # Сломанные сборки Qwen3 кладут весь ответ в reasoning-канал.
        req = LLMRequest(model="qwen3", messages=[], stream=True)
        accumulator = StreamAccumulator(req, provider="common", model="qwen3")

        accumulator.add_reasoning("весь ответ тут")
        response = accumulator.complete(finish_reason="stop")

        self.assertEqual(response.text, "весь ответ тут")
        self.assertIsNone(response.reasoning)

    def test_empty_stream_yields_no_text(self):
        req = LLMRequest(model="qwen3", messages=[], stream=True)
        accumulator = StreamAccumulator(req, provider="common", model="qwen3")

        response = accumulator.complete(finish_reason="stop")

        self.assertIsNone(response.text)
        self.assertIsNone(response.reasoning)


if __name__ == "__main__":
    unittest.main()
