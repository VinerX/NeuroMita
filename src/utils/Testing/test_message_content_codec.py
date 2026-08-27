"""Единый кодек содержимого сообщения.

Регресс: content разбирался в четырёх местах, каждое знало только про `text` и
`image_url`. Часть любого другого типа (tool_result, file, что угодно новое)
доезжала до SQLite и после round-trip исчезала — молча, без единой ошибки.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.message_content import MessageContentCodec
from managers.history_manager import HistoryManager


class MessageContentCodecTests(unittest.TestCase):
    def test_prompt_text_keeps_images_out_of_the_prompt(self):
        content = [
            {"type": "text", "text": "смотри"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
        self.assertEqual(MessageContentCodec.to_prompt_text(content), "смотри [image]")

    def test_prompt_text_marks_unknown_parts_instead_of_dropping_them(self):
        content = [
            {"type": "text", "text": "итог"},
            {"type": "tool_result", "content": "42"},
        ]
        self.assertEqual(MessageContentCodec.to_prompt_text(content), "итог [tool_result]")

    def test_embedding_text_uses_only_real_text(self):
        content = [
            {"type": "text", "text": "первое"},
            {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
            {"type": "text", "text": "второе"},
        ]
        self.assertEqual(MessageContentCodec.to_embedding_text(content), "первое\nвторое")

    def test_prepend_text_does_not_lose_non_text_parts(self):
        content = [
            {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
            {"type": "text", "text": "привет"},
        ]
        merged = MessageContentCodec.prepend_text(content, "[Gap: 2 hours] ")
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["type"], "image_url")
        self.assertEqual(merged[1]["text"], "[Gap: 2 hours] привет")


class MultimodalDbRoundTripTests(unittest.TestCase):
    """Сериализация в БД и обратно — без потерь, включая незнакомые типы."""

    @staticmethod
    def _manager() -> HistoryManager:
        # Ни БД, ни файлы не нужны: обе функции — чистая сериализация, к диску
        # они ходят только за data:image-картинками, которых тут нет.
        return HistoryManager.__new__(HistoryManager)

    def _round_trip(self, content):
        manager = self._manager()
        db_content, db_meta = manager._prepare_message_for_db("user", content)
        return manager._reconstruct_message_from_db("user", db_content, db_meta)

    def test_unknown_part_type_survives_round_trip(self):
        content = [
            {"type": "text", "text": "что там по инструменту"},
            {"type": "tool_result", "tool_call_id": "42", "content": "ok"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ]
        restored = self._round_trip(content)
        self.assertEqual(restored["role"], "user")
        self.assertEqual(restored["content"], content)

    def test_file_part_survives_round_trip(self):
        content = [
            {"type": "text", "text": "лог"},
            {"type": "file", "file": {"name": "run.log", "size": 12}},
        ]
        restored = self._round_trip(content)
        self.assertEqual(restored["content"], content)

    def test_image_detail_and_display_role_are_preserved(self):
        content = [
            {"type": "text", "text": "кадр"},
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/a.png", "detail": "high"},
                "display_role": "camera",
            },
        ]
        restored = self._round_trip(content)
        self.assertEqual(restored["content"], content)

    def test_multiple_text_parts_are_joined_and_survive(self):
        content = [
            {"type": "text", "text": "первая строка"},
            {"type": "text", "text": "вторая строка"},
            {"type": "audio", "audio": {"url": "http://x/y.wav"}},
        ]
        restored = self._round_trip(content)
        self.assertEqual(
            restored["content"],
            [
                {"type": "text", "text": "первая строка\nвторая строка"},
                {"type": "audio", "audio": {"url": "http://x/y.wav"}},
            ],
        )


if __name__ == "__main__":
    unittest.main()
