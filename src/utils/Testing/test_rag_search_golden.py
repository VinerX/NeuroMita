"""Golden-тест сквозного пайплайна ``RAGManager.search_relevant``.

Этап 1 рефакторинга RAGManager — «зафиксировать поведение тестами».

Идея: прогнать РЕАЛЬНЫЙ пайплайн (QueryBuilder → векторный/keyword-ретриверы →
combiner → enrichers → to_public_dict) на фиксированном сценарии, но с
ДЕТЕРМИНИРОВАННЫМ фейковым движком эмбеддингов (текст → хеш-мешок токенов,
L2-normalize). Так убирается ML-джиттер и вывод пинится точно по порядку
``(source, id)``. Любая behaviour-preserving декомпозиция обязана сохранить
этот порядок и структурные инварианты (ключи публичного словаря, монотонно
невозрастающий score, число проиндексированных эмбеддингов).

Семантическое качество здесь НЕ проверяется — это отдельный слой (реальные
эмбеддинги + пороги Recall/MRR). Здесь фейковый движок нарочно простой, его
задача — быть tripwire на изменение «водопровода», а не оценивать релевантность.

Требует Venv-python (numpy). Фейковый движок обходит torch/transformers.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

import numpy as np

from services.contracts import AIEngineService, EmbeddingReadiness, EmbeddingService

DIM = 256

_TOKEN_RE = re.compile(r"[\wа-яё]+", re.IGNORECASE | re.UNICODE)


def _fake_vec(text: str) -> np.ndarray:
    """Детерминированный эмбеддинг: хеш-мешок токенов, L2-normalize."""
    v = np.zeros(DIM, dtype=np.float32)
    for tok in _TOKEN_RE.findall((text or "").lower()):
        h = 0
        for ch in tok:
            h = (h * 131 + ord(ch)) & 0x7FFFFFFF
        v[h % DIM] += 1.0
    norm = float(np.linalg.norm(v))
    if norm > 0:
        v /= norm
    return v


class _FakeEngine(AIEngineService):
    """Синхронный движок: отдаёт детерминированные вектора без ML."""

    def get_engine(self):
        return self

    def wait_ready(self, service, timeout=3.0):
        return True

    def call(self, service, method, payload=None, *, timeout=None) -> Future:
        f: Future = Future()
        try:
            p = payload or {}
            m = str(method).lower()
            if m == "get_embeddings":
                f.set_result([_fake_vec(t) for t in (p.get("texts") or [])])
            elif m == "ping":
                f.set_result(True)
            elif m == "get_reranker_status":
                f.set_result({})
            else:
                f.set_result([])
        except Exception as e:  # noqa: BLE001
            f.set_exception(e)
        return f


class _FakeEmbeddingService(EmbeddingService):
    """Продовый hot-path для local-эмбеддингов: RAG зовёт EmbeddingService
    напрямую. Отдаёт те же детерминированные вектора, что и _FakeEngine."""

    def readiness(self):
        return EmbeddingReadiness(model_loaded=True)

    def embed_one(self, text, prefix=""):
        return _fake_vec(text)

    def embed_many(self, texts, prefix="", batch_size=None, priority="hot"):
        return [_fake_vec(t) for t in (texts or [])]


# Фиксированный сценарий -------------------------------------------------------
_HISTORY = [
    (1, "user",      "Я вчера ходил в горы, поднимался на Маттерхорн возле Церматта.", "01.03.2026 10:00:00"),
    (2, "assistant", "Ого, Альпы прекрасны! Как погода на вершине?", "01.03.2026 10:01:00"),
    (3, "user",      "Планирую поездку в Швейцарию этим летом.", "02.03.2026 11:00:00"),
    (4, "user",      "У меня есть кошка Мурка, она любит спать на диване.", "03.03.2026 12:00:00"),
    (5, "assistant", "Мурка звучит очень мило!", "03.03.2026 12:01:00"),
    (6, "user",      "Сегодня получил оффер от Яндекса после собеседования.", "04.03.2026 09:00:00"),
    (7, "user",      "Читаю Мастер и Маргарита, дошёл до сцены с Понтием Пилатом.", "05.03.2026 20:00:00"),
    (8, "user",      "Изучаю PyTorch и нейросети по вечерам.", "06.03.2026 21:00:00"),
]
_MEMORIES = [
    (1, "Пользователь увлекается горным туризмом в Альпах.", "fact",  "high",   "01.03.2026 10:05:00"),
    (2, "У пользователя есть кошка по имени Мурка.",          "fact",  "medium", "03.03.2026 12:05:00"),
    (3, "Пользователь получил оффер от Яндекса.",             "event", "high",   "04.03.2026 09:05:00"),
]

# Захваченный golden: точный порядок (source, id) для каждого запроса.
# Пересобирается только осознанно при намеренном изменении пайплайна.
_GOLDEN = {
    "Что я рассказывал про горы и Альпы?": [
        ("history", 2), ("history", 1), ("history", 8), ("memory", 3), ("memory", 1),
    ],
    "Расскажи про мою кошку": [
        ("history", 1), ("memory", 3), ("memory", 1), ("memory", 2), ("history", 8),
    ],
    "Что у меня с работой?": [
        ("history", 4), ("memory", 2), ("history", 7), ("history", 1), ("memory", 3),
    ],
    "Какую книгу я читаю?": [
        ("history", 7), ("history", 1), ("memory", 3), ("memory", 1), ("memory", 2),
    ],
}

_EXPECTED_STORED = 11  # 8 history + 3 memory

_HISTORY_KEYS = {
    "source", "id", "content", "score", "features",
    "role", "date", "message_id", "speaker", "target", "participants",
}
_MEMORY_KEYS = {"source", "id", "content", "score", "features", "type", "priority", "date_created"}

# Герметичные настройки: вектор включён, реранкер/граф/шум/лемматизация выключены.
_SETTINGS = {
    "RAG_ENABLED": True,
    "RAG_VECTOR_SEARCH_ENABLED": True,
    "RAG_CROSS_ENCODER_ENABLED": False,
    "RAG_NOISE_MAX": 0.0,
    "RAG_DETAILED_LOGS": False,
    "RAG_SEARCH_GRAPH": False,
    "RAG_LEMMATIZATION": False,
    "RAG_FTS_MORPH_EXPAND": False,
}


class RagSearchGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from managers.settings_manager import SettingsManager
        from managers.database_manager import DatabaseManager
        from core.services import services
        from managers.rag.rag_manager import RAGManager

        cls._SettingsManager = SettingsManager
        cls._DatabaseManager = DatabaseManager
        cls._services = services
        cls._RAGManager = RAGManager

        # --- монипатч настроек ---
        cls._orig_get = SettingsManager.get
        SettingsManager.get = staticmethod(
            lambda key, default=None: _SETTINGS.get(key, default)
        )

        # --- временная БД ---
        cls._tmp = tempfile.mkdtemp(prefix="nm_rag_golden_")
        DatabaseManager._instance = None
        DatabaseManager._path_override = os.path.join(cls._tmp, "world.db")

        # --- фейковый движок + hot-path EmbeddingService ---
        cls._prev_engine = services().get_optional(AIEngineService)
        cls._prev_embed = services().get_optional(EmbeddingService)
        services().register(AIEngineService, _FakeEngine(), replace=True)
        services().register(EmbeddingService, _FakeEmbeddingService(), replace=True)

        # --- размерность под фейковый вектор + отключить фоновый трекинг доступа ---
        cls._orig_dims = RAGManager._current_dimensions
        cls._orig_track = RAGManager._track_access_async
        RAGManager._current_dimensions = lambda self: DIM
        RAGManager._track_access_async = lambda self, cands: None

        cls._cid = "GOLDEN"
        cls._rag = RAGManager(cls._cid)
        cls._seed()

    @classmethod
    def _seed(cls):
        rag = cls._rag
        with rag.db.connection() as conn:
            conn.execute("DELETE FROM history WHERE character_id=?", (cls._cid,))
            conn.execute("DELETE FROM memories WHERE character_id=?", (cls._cid,))
            conn.execute("DELETE FROM embeddings WHERE character_id=?", (cls._cid,))
            for hid, role, content, ts in _HISTORY:
                conn.execute(
                    "INSERT INTO history (id, character_id, role, content, is_active, is_deleted, timestamp) "
                    "VALUES (?,?,?,?,?,0,?)",
                    (hid, cls._cid, role, content, 0, ts),
                )
            for eid, content, typ, prio, dc in _MEMORIES:
                conn.execute(
                    "INSERT INTO memories (eternal_id, character_id, content, type, priority, is_deleted, date_created) "
                    "VALUES (?,?,?,?,?,0,?)",
                    (eid, cls._cid, content, typ, prio, dc),
                )
            conn.commit()
        for hid, role, content, ts in _HISTORY:
            rag.update_history_embedding(hid, content)
        for eid, content, typ, prio, dc in _MEMORIES:
            rag.update_memory_embedding(eid, content)

    @classmethod
    def tearDownClass(cls):
        SM = cls._SettingsManager
        SM.get = cls._orig_get
        cls._RAGManager._current_dimensions = cls._orig_dims
        cls._RAGManager._track_access_async = cls._orig_track
        # восстановить прежние сервисы (или снять фейковые)
        if cls._prev_engine is not None:
            cls._services().register(AIEngineService, cls._prev_engine, replace=True)
        else:
            cls._services().unregister(AIEngineService)
        if cls._prev_embed is not None:
            cls._services().register(EmbeddingService, cls._prev_embed, replace=True)
        else:
            cls._services().unregister(EmbeddingService)
        cls._DatabaseManager._instance = None
        cls._DatabaseManager._path_override = None
        import shutil
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_stored_embedding_count(self):
        with self._rag.db.connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE character_id=?", (self._cid,)
            ).fetchone()[0]
        self.assertEqual(n, _EXPECTED_STORED)

    def test_golden_ordering(self):
        for query, expected in _GOLDEN.items():
            with self.subTest(query=query):
                res = self._rag.search_relevant(query, limit=5, threshold=0.0)
                got = [(r["source"], r["id"]) for r in res]
                self.assertEqual(got, expected)

    def test_structural_invariants(self):
        for query in _GOLDEN:
            with self.subTest(query=query):
                res = self._rag.search_relevant(query, limit=5, threshold=0.0)
                # score монотонно невозрастает
                scores = [float(r["score"]) for r in res]
                self.assertEqual(scores, sorted(scores, reverse=True))
                for r in res:
                    keys = _MEMORY_KEYS if r["source"] == "memory" else _HISTORY_KEYS
                    self.assertTrue(
                        keys.issubset(r.keys()),
                        f"{r['source']} отдал не все ключи: {sorted(r.keys())}",
                    )
                    self.assertIsInstance(r["features"], dict)

    def test_determinism(self):
        query = "Что я рассказывал про горы и Альпы?"
        first = [(r["source"], r["id"]) for r in self._rag.search_relevant(query, limit=5, threshold=0.0)]
        second = [(r["source"], r["id"]) for r in self._rag.search_relevant(query, limit=5, threshold=0.0)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
