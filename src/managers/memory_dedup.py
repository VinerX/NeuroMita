"""
MemoryDeduplicator — векторная дедупликация воспоминаний.

Алгоритм:
1. Загружаем все активные воспоминания + их эмбеддинги из таблицы embeddings.
2. Строим матрицу косинусного сходства (numpy, O(N²) векторизованно).
3. Для каждой пары с similarity > threshold(age): добавляем в DedupPlan.
4. Canonical (target) = выше приоритет > новее > длиннее контент.
5. Разрешаем цепочки A→B→C в A→C.

Порог с учётом возраста:
  < 7 дней  → base + 0.03  (строже, свежие дубли очевидны)
  7–30 дней → base          (MEMORY_DEDUP_THRESHOLD, default 0.94)
  > 30 дней → base - 0.04  (мягче, старые могут быть связаны)

Настройки:
  MEMORY_DEDUP_THRESHOLD   float  default 0.94
  MEMORY_DEDUP_AGE_DECAY   bool   default True
"""

import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from managers.database_manager import DatabaseManager
from managers.settings_manager import SettingsManager


@dataclass
class DedupPair:
    source_id: int
    target_id: int
    similarity: float
    source_content: str
    target_content: str


@dataclass
class DedupPlan:
    pairs: List[DedupPair] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.pairs)


class MemoryDeduplicator:
    """Find and merge near-duplicate memories using vector similarity."""

    _BASE_THRESHOLD = 0.94
    _PRIO_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}

    def __init__(self, character_id: str):
        self.character_id = character_id
        self.db = DatabaseManager()

    # ------------------------------------------------------------------
    # Threshold helpers
    # ------------------------------------------------------------------

    def _get_base_threshold(self) -> float:
        try:
            return float(SettingsManager.get("MEMORY_DEDUP_THRESHOLD", self._BASE_THRESHOLD))
        except Exception:
            return self._BASE_THRESHOLD

    def _age_decay_enabled(self) -> bool:
        try:
            val = SettingsManager.get("MEMORY_DEDUP_AGE_DECAY", True)
            return str(val).lower() not in ("false", "0")
        except Exception:
            return True

    def _threshold(self, age_days: float) -> float:
        base = self._get_base_threshold()
        if not self._age_decay_enabled():
            return base
        if age_days < 7:
            return min(0.99, base + 0.03)
        if age_days < 30:
            return base
        return max(0.80, base - 0.04)

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_age(date_created: Optional[str]) -> float:
        """Return age in days; 999 if unparseable."""
        if not date_created:
            return 999.0
        raw = str(date_created).strip()
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y_%H.%M", "%d.%m.%Y %H:%M"):
            try:
                dt = datetime.datetime.strptime(raw, fmt)
                return (datetime.datetime.now() - dt).total_seconds() / 86400.0
            except Exception:
                continue
        return 999.0

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def analyze(self) -> DedupPlan:
        """
        Dry-run: find near-duplicate active memories via cosine similarity.
        Requires numpy. Returns DedupPlan (may be empty).
        """
        try:
            import numpy as np
        except ImportError:
            logging.warning("[MemoryDeduplicator] numpy not available — cannot analyze.")
            return DedupPlan()

        rows = self._load_memories_with_embeddings()
        if len(rows) < 2:
            return DedupPlan()

        # Unpack rows
        eids, contents, priorities, ages, vecs = [], [], [], [], []
        for eid, content, priority, date_created, emb_blob in rows:
            try:
                vec = np.frombuffer(emb_blob, dtype=np.float32).copy()
            except Exception:
                continue
            if vec.size == 0:
                continue
            eids.append(int(eid))
            contents.append(str(content or ""))
            priorities.append(str(priority or "Normal").strip().lower())
            ages.append(self._parse_age(date_created))
            vecs.append(vec)

        if len(vecs) < 2:
            return DedupPlan()

        # Cosine similarity matrix
        matrix = np.array(vecs, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-8, norms)
        norm_matrix = matrix / norms
        sim_matrix = np.dot(norm_matrix, norm_matrix.T)  # (N, N)

        # Build pairs
        plan = DedupPlan()
        merged_into: Dict[int, int] = {}  # source_eid → canonical_eid

        N = len(eids)
        for i in range(N):
            for j in range(i + 1, N):
                sim = float(sim_matrix[i, j])
                # Use age of the newer memory for threshold
                age = min(ages[i], ages[j])
                if sim < self._threshold(age):
                    continue

                # Choose canonical: higher priority > newer (lower age) > longer content
                rank_i = self._PRIO_RANK.get(priorities[i], 1)
                rank_j = self._PRIO_RANK.get(priorities[j], 1)

                if rank_i > rank_j:
                    src_idx, tgt_idx = j, i
                elif rank_j > rank_i:
                    src_idx, tgt_idx = i, j
                elif ages[i] > ages[j]:  # i is older → i is source
                    src_idx, tgt_idx = i, j
                elif ages[j] > ages[i]:
                    src_idx, tgt_idx = j, i
                elif len(contents[i]) >= len(contents[j]):
                    src_idx, tgt_idx = j, i
                else:
                    src_idx, tgt_idx = i, j

                source_eid = eids[src_idx]
                target_eid = eids[tgt_idx]

                # Resolve chain: if target itself is being merged somewhere, follow
                canonical = merged_into.get(target_eid, target_eid)
                if source_eid == canonical:
                    continue  # would create a loop

                merged_into[source_eid] = canonical

                plan.pairs.append(DedupPair(
                    source_id=source_eid,
                    target_id=canonical,
                    similarity=sim,
                    source_content=contents[src_idx],
                    target_content=contents[tgt_idx],
                ))

        return plan

    def apply(self, plan: DedupPlan, memory_manager) -> dict:
        """Execute plan: merge each source into target using memory_manager.merge_memories()."""
        merged = 0
        failed = 0
        for pair in plan.pairs:
            ok = memory_manager.merge_memories(pair.source_id, pair.target_id, new_content=None)
            if ok:
                merged += 1
            else:
                failed += 1
        logging.info(f"[MemoryDeduplicator] apply: merged={merged}, failed={failed}")
        return {"merged": merged, "failed": failed}

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _load_memories_with_embeddings(self) -> list:
        """
        Return list of (eternal_id, content, priority, date_created, embedding_blob).
        Only active (is_deleted=0, is_forgotten=0) memories with an embedding.
        """
        with self.db.connection() as conn:
            cur = conn.cursor()

            # Try joining with the embeddings table (preferred — model-aware)
            try:
                cur.execute(
                    """
                    SELECT m.eternal_id, m.content, m.priority, m.date_created,
                           e.embedding
                    FROM memories m
                    JOIN embeddings e
                         ON e.source_table = 'memories'
                        AND e.source_id    = m.eternal_id
                        AND e.character_id = m.character_id
                    WHERE m.character_id = ?
                      AND m.is_deleted   = 0
                      AND (m.is_forgotten = 0 OR m.is_forgotten IS NULL)
                      AND e.embedding IS NOT NULL
                    ORDER BY m.eternal_id
                    """,
                    (self.character_id,),
                )
                rows = cur.fetchall() or []
                if rows:
                    return rows
            except Exception as e:
                logging.debug(f"[MemoryDeduplicator] embeddings JOIN failed, fallback: {e}")

            # Fallback: legacy BLOB column on memories table
            try:
                cur.execute(
                    """
                    SELECT eternal_id, content, priority, date_created, embedding
                    FROM memories
                    WHERE character_id = ?
                      AND is_deleted   = 0
                      AND (is_forgotten = 0 OR is_forgotten IS NULL)
                      AND embedding IS NOT NULL
                    ORDER BY eternal_id
                    """,
                    (self.character_id,),
                )
                return cur.fetchall() or []
            except Exception as e:
                logging.warning(f"[MemoryDeduplicator] fallback embedding query failed: {e}")
                return []
