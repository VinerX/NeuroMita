"""Golden-пины чистых хелперов RAG (без БД и без AI-движка).

Этап 1 рефакторинга RAGManager — «зафиксировать поведение тестами». Здесь
пинятся детерминированные функции-кирпичики, на которые опирается пайплайн:
разбиение на предложения, декодер BLOB→ndarray и публичная форма кандидата.
Любая декомпозиция должна сохранять этот вывод байт-в-байт (behaviour-preserving).
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import numpy as np

from managers.rag.rag_manager import RAGManager
from managers.rag.pipeline.types import Candidate


class SplitSentencesGoldenTests(unittest.TestCase):
    def test_punctuation_boundaries(self):
        out = RAGManager._split_sentences(
            "Первое предложение тут. Второе предложение здесь! А третье?", 5
        )
        self.assertEqual(
            out,
            ["Первое предложение тут.", "Второе предложение здесь!", "А третье?"],
        )

    def test_min_len_filters_short_fragments(self):
        out = RAGManager._split_sentences(
            "Короткий. Это предложение достаточно длинное чтобы пройти порог.", 20
        )
        self.assertEqual(out, ["Это предложение достаточно длинное чтобы пройти порог."])

    def test_newlines_split(self):
        out = RAGManager._split_sentences(
            "Строка один\nСтрока два тоже достаточно длинная строка", 10
        )
        self.assertEqual(out, ["Строка один", "Строка два тоже достаточно длинная строка"])

    def test_empty_and_blank(self):
        self.assertEqual(RAGManager._split_sentences("", 5), [])
        self.assertEqual(RAGManager._split_sentences("   ", 5), [])


class BlobToArrayGoldenTests(unittest.TestCase):
    def _rag(self, dim):
        # _blob_to_array трогает только self._current_dimensions()
        return types.SimpleNamespace(_current_dimensions=lambda: dim)

    def test_valid_blob_roundtrips(self):
        blob = np.array([1, 2, 3, 4], dtype=np.float32).tobytes()
        arr = RAGManager._blob_to_array(self._rag(4), blob)
        self.assertEqual(arr.tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertTrue(arr.flags.writeable)  # должен быть .copy(), а не read-only view

    def test_empty_blob_is_none(self):
        self.assertIsNone(RAGManager._blob_to_array(self._rag(4), b""))

    def test_size_not_multiple_of_float32_is_none(self):
        self.assertIsNone(RAGManager._blob_to_array(self._rag(4), b"\x00\x00\x00"))

    def test_wrong_dimension_is_none(self):
        blob = np.array([1, 2, 3], dtype=np.float32).tobytes()
        self.assertIsNone(RAGManager._blob_to_array(self._rag(4), blob))

    def test_nan_is_none(self):
        blob = np.array([1, 2, np.nan, 4], dtype=np.float32).tobytes()
        self.assertIsNone(RAGManager._blob_to_array(self._rag(4), blob))

    def test_dim_zero_accepts_any_length(self):
        blob = np.array([1, 2, 3, 4, 5], dtype=np.float32).tobytes()
        arr = RAGManager._blob_to_array(self._rag(0), blob)
        self.assertEqual(arr.tolist(), [1.0, 2.0, 3.0, 4.0, 5.0])


class CandidatePublicDictGoldenTests(unittest.TestCase):
    def test_memory_shape(self):
        c = Candidate(
            source="memory", id=7, content="c",
            meta={"type": "fact", "priority": "high", "date_created": "d"},
            features={"sim": 0.123456, "kw": 0.5}, score=0.9,
        )
        self.assertEqual(
            c.to_public_dict(),
            {
                "source": "memory", "id": 7, "content": "c", "score": 0.9,
                "features": {"sim": 0.1235, "kw": 0.5},  # округление до 4 знаков
                "type": "fact", "priority": "high", "date_created": "d",
            },
        )

    def test_history_shape(self):
        c = Candidate(
            source="history", id=3, content="hc",
            meta={"role": "user", "date": "dd"}, features={"lex": 0.1}, score=0.2,
        )
        self.assertEqual(
            c.to_public_dict(),
            {
                "source": "history", "id": 3, "content": "hc", "score": 0.2,
                "features": {"lex": 0.1},
                "role": "user", "date": "dd", "message_id": None,
                "speaker": None, "target": None, "participants": [],
            },
        )

    def test_merge_from_maxes_features_and_fills_blanks(self):
        m1 = Candidate(source="memory", id=1, content="",
                       meta={"type": "fact"}, features={"sim": 0.2, "kw": 0.1})
        m2 = Candidate(source="memory", id=1, content="filled",
                       meta={"type": "", "priority": "low"},
                       features={"sim": 0.5, "lex": 0.3})
        m1.merge_from(m2)
        self.assertEqual(m1.content, "filled")           # пустой content заполнен
        self.assertEqual(m1.meta, {"type": "fact", "priority": "low"})  # blank не перетирает
        self.assertEqual(m1.features, {"sim": 0.5, "kw": 0.1, "lex": 0.3})  # max по компонентам

    def test_key_property(self):
        self.assertEqual(Candidate(source="history", id=5).key, ("history", 5))
        self.assertEqual(Candidate(source="memory", id=0).key, ("memory", 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
