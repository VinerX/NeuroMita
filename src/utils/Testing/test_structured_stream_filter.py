"""StructuredJsonStreamFilter разводит JSON-поток на каналы content/reasoning.

Регресс, ради которого написаны тесты: при json_schema-грамматике (LM Studio +
Gemma 4) нативный reasoning_content подавляется, и модель кладёт мысли прямо в
поле "reasoning" JSON-ответа. Фильтр обязан вытащить их в отдельный канал, а не
уронить в текст ответа и не потерять вовсе — иначе окно размышлений при стриминге
остаётся пустым (issue про «не вывелись размышления визуально»).
"""
import sys
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from controllers.chat_controller import StructuredJsonStreamFilter


def _drain(f: StructuredJsonStreamFilter, *chunks: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for chunk in chunks:
        out.extend(f.feed(chunk))
    out.extend(f.flush_visible())
    # Склеиваем соседние куски одного канала для устойчивого сравнения.
    merged: list[tuple[str, str]] = []
    for channel, text in out:
        if merged and merged[-1][0] == channel:
            merged[-1] = (channel, merged[-1][1] + text)
        else:
            merged.append((channel, text))
    return merged


def _by_channel(pieces: list[tuple[str, str]], channel: str) -> str:
    return "".join(t for c, t in pieces if c == channel)


class StructuredJsonStreamFilterTests(unittest.TestCase):
    def test_plain_text_passthrough_as_content(self):
        f = StructuredJsonStreamFilter()
        pieces = _drain(f, "Привет, ", "как дела?")
        self.assertEqual(pieces, [("content", "Привет, как дела?")])
        self.assertFalse(f.is_json_mode())

    def test_reasoning_field_goes_to_reasoning_channel(self):
        f = StructuredJsonStreamFilter()
        payload = '{"reasoning": "Прикидываю ответ", "segments": [{"text": "Привет!"}]}'
        pieces = _drain(f, payload)
        self.assertEqual(_by_channel(pieces, "reasoning"), "Прикидываю ответ")
        self.assertEqual(_by_channel(pieces, "content").strip(), "Привет!")

    def test_reasoning_streams_before_content(self):
        f = StructuredJsonStreamFilter()
        payload = '{"reasoning": "думаю", "segments": [{"text": "ответ"}]}'
        pieces = _drain(f, payload)
        # Порядок каналов: сперва мысли, потом ответ.
        self.assertEqual(pieces[0][0], "reasoning")
        self.assertEqual(pieces[-1][0], "content")

    def test_multiple_segments_joined_with_space(self):
        f = StructuredJsonStreamFilter()
        payload = '{"segments": [{"text": "Раз"}, {"text": "Два"}]}'
        pieces = _drain(f, payload)
        self.assertEqual(_by_channel(pieces, "content").split(), ["Раз", "Два"])
        self.assertEqual(_by_channel(pieces, "reasoning"), "")

    def test_chunked_feed_splits_key_and_value(self):
        f = StructuredJsonStreamFilter()
        # Ключи и значения рвём посередине — как реальный SSE-поток.
        chunks = ['{"reaso', 'ning": "мыс', 'ль", "segments": [{"te', 'xt": "отв', 'ет"}]}']
        pieces = _drain(f, *chunks)
        self.assertEqual(_by_channel(pieces, "reasoning"), "мысль")
        self.assertEqual(_by_channel(pieces, "content").strip(), "ответ")

    def test_escaped_characters_decoded(self):
        f = StructuredJsonStreamFilter()
        payload = '{"segments": [{"text": "строка\\nс переносом"}]}'
        pieces = _drain(f, payload)
        self.assertIn("строка\nс переносом", _by_channel(pieces, "content"))

    def test_markdown_fenced_json(self):
        f = StructuredJsonStreamFilter()
        payload = '```json\n{"segments": [{"text": "внутри забора"}]}\n```'
        pieces = _drain(f, payload)
        self.assertEqual(_by_channel(pieces, "content").strip(), "внутри забора")


if __name__ == "__main__":
    unittest.main()
