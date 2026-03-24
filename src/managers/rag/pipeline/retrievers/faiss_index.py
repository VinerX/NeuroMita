"""In-memory vector index for fast similarity search.

Two backends, selected automatically:
  * FAISS  (faiss-cpu / faiss-gpu) — true ANN, best for N > 50k
  * NumPy  (always available)      — batched matrix multiply, exact, fast for N < 50k

Both expose the same public API:
    from .faiss_index import HAS_FAISS, faiss_retrieve, invalidate

faiss_retrieve() returns [] if the cache is empty or the DB has no embeddings,
allowing transparent fallback to the old blob-scan path in VectorRetriever.

Cache invalidation:
  Count-based: a cheap COUNT(*) query detects new embeddings → auto-rebuild.
  Explicit:    call invalidate() after bulk re-indexing (optional, belt-and-suspenders).
"""
from __future__ import annotations

import numpy as np
from typing import Optional

try:
    import faiss as _faiss
    HAS_FAISS = True
except ImportError:
    _faiss = None  # type: ignore
    HAS_FAISS = False


# ── helpers ──────────────────────────────────────────────────────────────────

def _blob_to_vec(blob) -> Optional[np.ndarray]:
    if not blob:
        return None
    try:
        arr = np.frombuffer(blob, dtype=np.float32).copy()
        return arr if arr.size > 0 else None
    except Exception:
        return None


def _l2_normalize(v: np.ndarray) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return None
    return (v / n).astype(np.float32)


# ── backend index classes ─────────────────────────────────────────────────────

class _NumpyIndex:
    """Exact cosine search via vectorised matrix multiply.  O(N), zero deps."""

    __slots__ = ("_matrix", "_ids")

    def __init__(self) -> None:
        self._matrix: Optional[np.ndarray] = None  # (N, dim) float32
        self._ids: list[int] = []

    def build(self, source_ids: list[int], vecs: list[np.ndarray]) -> None:
        self._ids = source_ids
        self._matrix = np.stack(vecs, axis=0).astype(np.float32)

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._matrix is None or len(self._ids) == 0:
            return []
        sims = self._matrix @ query_vec.astype(np.float32)     # (N,)
        k = min(k, len(self._ids))
        top_idx = np.argpartition(sims, -k)[-k:]               # unordered top-k
        top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]     # sort desc
        return [(self._ids[i], float(sims[i])) for i in top_idx]

    @property
    def size(self) -> int:
        return len(self._ids)


class _FaissIndex:
    """Exact cosine search via FAISS IndexFlatIP.  Same speed as NumPy for
    small N; significantly faster at N > 50k thanks to BLAS optimisations."""

    __slots__ = ("_index", "_ids")

    def __init__(self, dim: int) -> None:
        self._index = _faiss.IndexFlatIP(dim)
        self._ids: list[int] = []

    def build(self, source_ids: list[int], vecs: list[np.ndarray]) -> None:
        self._ids = source_ids
        matrix = np.stack(vecs, axis=0).astype(np.float32)
        self._index.add(matrix)

    def search(self, query_vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._index.ntotal == 0:
            return []
        k = min(k, self._index.ntotal)
        q = query_vec.reshape(1, -1).astype(np.float32)
        D, I = self._index.search(q, k)
        return [
            (self._ids[idx], float(dist))
            for dist, idx in zip(D[0], I[0])
            if 0 <= idx < len(self._ids)
        ]

    @property
    def size(self) -> int:
        return len(self._ids)


# ── cache ─────────────────────────────────────────────────────────────────────

class _VectorCache:
    """Global cache: one index per (char_id, model_name, source_table).

    Rebuilt lazily when the COUNT(*) of embeddings rows changes (new docs indexed).
    """

    def __init__(self) -> None:
        self._indexes: dict[tuple, _NumpyIndex | _FaissIndex] = {}
        self._counts: dict[tuple, int] = {}

    def get(
        self,
        conn,
        character_id: str,
        model_name: str,
        source_table: str,
        dim: int,
    ) -> Optional[_NumpyIndex | _FaissIndex]:
        key = (character_id, model_name, source_table)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM embeddings "
                "WHERE character_id=? AND model_name=? AND source_table=?",
                (character_id, model_name, source_table),
            )
            db_count: int = cur.fetchone()[0]
        except Exception:
            return None

        if key in self._indexes and self._counts.get(key) == db_count:
            return self._indexes[key]      # cache hit

        index = self._build(conn, character_id, model_name, source_table)
        if index is not None:
            self._indexes[key] = index
            self._counts[key] = db_count
        return index

    def invalidate(self, character_id: str, model_name: str, source_table: str) -> None:
        key = (character_id, model_name, source_table)
        self._indexes.pop(key, None)
        self._counts.pop(key, None)

    def _build(
        self,
        conn,
        character_id: str,
        model_name: str,
        source_table: str,
    ) -> Optional[_NumpyIndex | _FaissIndex]:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT source_id, embedding FROM embeddings "
                "WHERE character_id=? AND model_name=? AND source_table=?",
                (character_id, model_name, source_table),
            )
            rows = cur.fetchall()
        except Exception:
            return None

        if not rows:
            return None

        source_ids: list[int] = []
        vecs: list[np.ndarray] = []
        for source_id, blob in rows:
            v = _blob_to_vec(blob)
            if v is None or np.isnan(v).any() or np.isinf(v).any():
                continue
            v = _l2_normalize(v)
            if v is None:
                continue
            source_ids.append(int(source_id))
            vecs.append(v)

        if not source_ids:
            return None

        actual_dim = vecs[0].shape[0]
        if HAS_FAISS:
            index: _NumpyIndex | _FaissIndex = _FaissIndex(actual_dim)
        else:
            index = _NumpyIndex()
        index.build(source_ids, vecs)
        return index


# ── module-level singleton + public API ──────────────────────────────────────

_cache = _VectorCache()


def faiss_retrieve(
    conn,
    character_id: str,
    model_name: str,
    source_table: str,
    query_vec: np.ndarray,
    k: int = 500,
) -> list[tuple[int, float]]:
    """Return top-k (source_id, cosine_sim) pairs, sorted by sim descending.

    Uses FAISS backend if available, otherwise numpy matmul.
    Returns [] if the index is empty; caller falls back to blob-scan path.
    """
    dim = query_vec.shape[0]
    index = _cache.get(conn, character_id, model_name, source_table, dim)
    if index is None or index.size == 0:
        return []
    return index.search(query_vec, k)


def invalidate(character_id: str, model_name: str, source_table: str) -> None:
    """Force index rebuild on next query (e.g. after bulk re-indexing)."""
    _cache.invalidate(character_id, model_name, source_table)
