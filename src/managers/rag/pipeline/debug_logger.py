from __future__ import annotations

import json
from typing import Any, Dict, List
from managers.rag.rag_utils import rag_clean_text
from main_logger import logger
from .types import QueryState, Candidate
from .config import RAGConfig
from managers.settings_manager import SettingsManager


class RagDebugLogger:
    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    def log(self, qs: QueryState, buckets: Dict[str, List[Candidate]], cands: List[Candidate]) -> None:
        if not self.cfg.detailed_logs:
            return

        try:
            logger.info("[RAG] ==================== SEARCH CONFIG ====================")
            items = [
                ("character_id", self.rag.character_id),
                ("query.clean", rag_clean_text(qs.user_query)),
                ("query.expanded.clip", (rag_clean_text(qs.expanded_query_text)[:240] + "…")
                 if len(rag_clean_text(qs.expanded_query_text)) > 240 else rag_clean_text(qs.expanded_query_text)),
                ("query.tail_messages", int(self.cfg.tail_messages)),
                ("query.embed_mode", str(SettingsManager.get("RAG_QUERY_EMBED_MODE", "concat") or "concat")),
                ("query.vec_ready", bool(qs.query_vec is not None)),
                ("memory.mode", self.cfg.memory_mode),
                ("flags.search_memory", bool(self.cfg.search_memory)),
                ("flags.search_history", bool(self.cfg.search_history)),
                ("flags.keyword_search", bool(self.cfg.kw_enabled)),
                ("flags.fts", bool(self.cfg.use_fts)),
                ("kw.keywords", qs.keywords),
                ("weights", {
                    "K1(sim)": self.cfg.K1, "K2(time)": self.cfg.K2, "K3(prio)": self.cfg.K3,
                    "K4(entity)": self.cfg.K4, "K5(kw)": self.cfg.K5, "K6(lex)": self.cfg.K6,
                }),
                ("threshold", float(self.cfg.threshold)),
                ("limit", int(self.cfg.limit)),
                ("reranker", (
                    f"linear + cross-encoder [{self.cfg.cross_encoder_model}] top{self.cfg.cross_encoder_top_k}"
                    if self.cfg.cross_encoder_enabled and self.cfg.cross_encoder_model
                    else "linear"
                )),
            ]
            max_k = max((len(k) for k, _ in items), default=0)
            for k, v in items:
                vv = v
                try:
                    if isinstance(v, dict):
                        vv = json.dumps(v, ensure_ascii=False)
                    elif isinstance(v, list):
                        vv = json.dumps(v, ensure_ascii=False)
                except Exception:
                    vv = v
                logger.info(f"[RAG][CFG] {k:<{max_k}} : {vv}")
            logger.info("[RAG] =======================================================")
        except Exception:
            pass

        # buckets stats
        try:
            parts = []
            total_raw = 0
            for name, lst in (buckets or {}).items():
                n = len(lst or [])
                total_raw += n
                parts.append(f"{name}={n}")
            logger.info(f"[RAG][STAT] candidates: raw={total_raw} | merged={len(cands)} | " + ", ".join(parts))
        except Exception:
            pass

        # candidate list (top/bottom)
        try:
            total = len(cands)
            if total <= 0:
                logger.info("[RAG] (no candidates)")
                return

            log_top = max(0, int(self.cfg.log_top_n))
            log_bottom = max(0, int(self.cfg.log_bottom_n))
            show_all = bool(self.cfg.log_show_all)

            idxs: list[int] = []
            if show_all:
                idxs = list(range(total))
            else:
                log_top = min(log_top, total)
                log_bottom = min(log_bottom, max(0, total - log_top))
                idxs = list(range(log_top))
                if log_bottom > 0:
                    idxs.extend(list(range(total - log_bottom, total)))

            def _clip(s: Any, n: int = 220) -> str:
                t = str(s or "").replace("\n", " ").replace("\r", " ").strip()
                t = rag_clean_text(t)
                return (t[:n] + "…") if len(t) > n else t

            logger.info("[RAG] -------------------- CANDIDATES -----------------------")
            last = -999999
            for i in idxs:
                if (not show_all) and last >= 0 and i - last > 1:
                    logger.info(f"[RAG] ... ({i - last - 1} hidden) ...")
                last = i

                c = cands[i]
                f = c.features or {}
                dbg = c.debug or {}

                meta = c.meta or {}
                if c.source == "memory":
                    meta_txt = f"type={meta.get('type')} prio={meta.get('priority')} date={meta.get('date_created')}"
                else:
                    parts = meta.get("participants") or []
                    meta_txt = f"role={meta.get('role')} date={meta.get('date')} sp={meta.get('speaker')} tg={meta.get('target')} parts={len(parts)}"

                ce_score = dbg.get("cross_encoder")
                ce_str = f" ce={float(ce_score):.3f}" if ce_score is not None else ""
                logger.info(
                    f"[RAG][{i+1:03d}/{total:03d}] {c.source}:{c.id} score={float(c.score):.4f} "
                    f"(sim={float(f.get('sim',0.0)):.3f} time={float(f.get('time',0.0)):.3f} "
                    f"prio={float(f.get('prio',0.0)):.3f} ent={float(f.get('entity',0.0)):.3f} "
                    f"kw={float(f.get('kw',0.0)):.3f} lex={float(f.get('lex',0.0)):.3f}"
                    f"{ce_str}) "
                    f"| {meta_txt} | \"{_clip(c.content)}\""
                )

            logger.info("[RAG] =======================================================")
        except Exception:
            pass