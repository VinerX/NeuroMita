from __future__ import annotations

from dataclasses import dataclass
from managers.settings_manager import SettingsManager


def _b(v, default=False) -> bool:
    try:
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)
    except Exception:
        return bool(default)


def _i(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


@dataclass
class RAGConfig:
    limit: int = 5
    threshold: float = 0.3

    # weights
    K1: float = 1.0
    K2: float = 0.3
    K3: float = 0.5
    K4: float = 0.5
    K5: float = 0.6
    K6: float = 0.3

    decay_rate: float = 0.05
    noise_max: float = 0.02

    # query build
    tail_messages: int = 2

    # enabled scopes
    search_memory: bool = True
    search_history: bool = True

    # keyword
    kw_enabled: bool = True
    kw_max_terms: int = 8
    kw_min_score: float = 0.34
    kw_sql_limit: int = 250
    kw_min_len: int = 3
    lemmatization: bool = True

    # fts
    use_fts: bool = True
    fts_top_k_hist: int = 50
    fts_top_k_mem: int = 50
    fts_max_terms: int = 10
    fts_min_len: int = 3

    memory_mode: str = "all"  # forgotten|active|all

    # logging
    detailed_logs: bool = True
    log_top_n: int = 10
    log_bottom_n: int = 5
    log_show_all: bool = False

    # --- NEW: combine / recall controls ---
    # union|vector_only|intersect|two_stage
    combine_mode: str = "union"

    # vector candidate cap used by some combiners (vector_only/two_stage)
    vector_top_k: int = 0  # 0 = no cap

    # intersect settings
    intersect_min_methods: int = 2
    intersect_require_vector: bool = True
    intersect_fallback_union: bool = True

    # two-stage fallback
    two_stage_fallback_union: bool = True

    @classmethod
    def from_settings(cls, *, limit: int, threshold: float) -> "RAGConfig":
        cfg = cls()
        cfg.limit = _i(limit, 5)
        cfg.threshold = _f(threshold, 0.4)

        cfg.K1 = _f(SettingsManager.get("RAG_WEIGHT_SIMILARITY", 1.0), 1.0)
        cfg.K2 = _f(SettingsManager.get("RAG_WEIGHT_TIME", 0.3), 0.3)
        cfg.K3 = _f(SettingsManager.get("RAG_WEIGHT_PRIORITY", 0.5), 0.5)
        cfg.K4 = _f(SettingsManager.get("RAG_WEIGHT_ENTITY", 0.5), 0.5)
        cfg.K5 = _f(SettingsManager.get("RAG_WEIGHT_KEYWORDS", 0.6), 0.6)
        cfg.K6 = _f(SettingsManager.get("RAG_WEIGHT_LEXICAL", 0.3), 0.3)

        cfg.decay_rate = _f(SettingsManager.get("RAG_TIME_DECAY_RATE", 0.05), 0.05)
        cfg.noise_max = _f(SettingsManager.get("RAG_NOISE_MAX", 0.02), 0.02)

        cfg.tail_messages = _i(SettingsManager.get("RAG_QUERY_TAIL_MESSAGES", 2), 2)

        cfg.search_memory = _b(SettingsManager.get("RAG_SEARCH_MEMORY", True), True)
        cfg.search_history = _b(SettingsManager.get("RAG_SEARCH_HISTORY", True), True)

        cfg.kw_enabled = _b(SettingsManager.get("RAG_KEYWORD_SEARCH", True), True)
        cfg.kw_max_terms = _i(SettingsManager.get("RAG_KEYWORDS_MAX_TERMS", 8), 8)
        cfg.kw_min_score = _f(SettingsManager.get("RAG_KEYWORD_MIN_SCORE", 0.34), 0.34)
        cfg.kw_sql_limit = _i(SettingsManager.get("RAG_KEYWORD_SQL_LIMIT", 250), 250)
        cfg.kw_min_len = _i(SettingsManager.get("RAG_KEYWORDS_MIN_LEN", 3), 3)
        cfg.lemmatization = _b(SettingsManager.get("RAG_LEMMATIZATION", True), True)

        cfg.use_fts = _b(SettingsManager.get("RAG_USE_FTS", True), True)
        cfg.fts_top_k_hist = _i(SettingsManager.get("RAG_FTS_TOP_K_HISTORY", 50), 50)
        cfg.fts_top_k_mem = _i(SettingsManager.get("RAG_FTS_TOP_K_MEMORIES", 50), 50)
        cfg.fts_max_terms = _i(SettingsManager.get("RAG_FTS_MAX_TERMS", 10), 10)
        cfg.fts_min_len = _i(SettingsManager.get("RAG_FTS_MIN_LEN", 3), 3)

        cfg.memory_mode = str(SettingsManager.get("RAG_MEMORY_MODE", "all") or "all").strip().lower()

        cfg.detailed_logs = _b(SettingsManager.get("RAG_DETAILED_LOGS", True), True)
        cfg.log_top_n = _i(SettingsManager.get("RAG_LOG_LIST_TOP_N", 10), 10)
        cfg.log_bottom_n = _i(SettingsManager.get("RAG_LOG_LIST_BOTTOM_N", 5), 5)
        cfg.log_show_all = _b(SettingsManager.get("RAG_LOG_LIST_SHOW_ALL", False), False)

        # --- NEW settings (safe defaults) ---
        cfg.combine_mode = str(SettingsManager.get("RAG_COMBINE_MODE", "union") or "union").strip().lower()
        cfg.vector_top_k = _i(SettingsManager.get("RAG_VECTOR_TOP_K", 0), 0)

        cfg.intersect_min_methods = _i(SettingsManager.get("RAG_INTERSECT_MIN_METHODS", 2), 2)
        cfg.intersect_require_vector = _b(SettingsManager.get("RAG_INTERSECT_REQUIRE_VECTOR", True), True)
        cfg.intersect_fallback_union = _b(SettingsManager.get("RAG_INTERSECT_FALLBACK_UNION", True), True)

        cfg.two_stage_fallback_union = _b(SettingsManager.get("RAG_TWO_STAGE_FALLBACK_UNION", True), True)

        cfg._validate()
        return cfg

    def _validate(self) -> None:
        """Clamp values to sane ranges to prevent misconfiguration."""
        self.limit = max(1, self.limit)
        self.threshold = max(0.0, min(1.0, self.threshold))
        self.decay_rate = max(0.0, min(1.0, self.decay_rate))
        self.noise_max = max(0.0, min(1.0, self.noise_max))
        self.tail_messages = max(0, self.tail_messages)
        self.kw_max_terms = max(1, self.kw_max_terms)
        self.kw_min_score = max(0.0, min(1.0, self.kw_min_score))
        self.kw_sql_limit = max(1, self.kw_sql_limit)
        self.kw_min_len = max(1, self.kw_min_len)
        self.fts_top_k_hist = max(1, self.fts_top_k_hist)
        self.fts_top_k_mem = max(1, self.fts_top_k_mem)
        self.fts_max_terms = max(1, self.fts_max_terms)
        self.fts_min_len = max(1, self.fts_min_len)
        if self.memory_mode not in ("forgotten", "active", "all"):
            self.memory_mode = "forgotten"
        _VALID_MODES = ("union", "vector_only", "intersect", "intersect2", "intersect_n", "two_stage")
        if self.combine_mode not in _VALID_MODES:
            self.combine_mode = "union"
        self.vector_top_k = max(0, self.vector_top_k)
        self.intersect_min_methods = max(1, self.intersect_min_methods)


# ── Default values for all SettingsManager RAG keys ──────────────────────
# Used by the "Reset RAG defaults" button in the UI.
RAG_DEFAULTS: dict[str, object] = {
    "RAG_WEIGHT_SIMILARITY": 1.0,
    "RAG_WEIGHT_TIME": 0.3,
    "RAG_WEIGHT_PRIORITY": 0.5,
    "RAG_WEIGHT_ENTITY": 0.5,
    "RAG_WEIGHT_KEYWORDS": 0.6,
    "RAG_WEIGHT_LEXICAL": 0.3,
    "RAG_TIME_DECAY_RATE": 0.05,
    "RAG_NOISE_MAX": 0.02,
    "RAG_MAX_RESULTS": 10,
    "RAG_SIM_THRESHOLD": 0.30,
    "RAG_QUERY_TAIL_MESSAGES": 2,
    "RAG_SEARCH_MEMORY": True,
    "RAG_SEARCH_HISTORY": True,
    "RAG_KEYWORD_SEARCH": True,
    "RAG_LEMMATIZATION": True,
    "RAG_KEYWORDS_MAX_TERMS": 8,
    "RAG_KEYWORDS_MIN_LEN": 3,
    "RAG_KEYWORD_MIN_SCORE": 0.34,
    "RAG_KEYWORD_SQL_LIMIT": 250,
    "RAG_USE_FTS": True,
    "RAG_FTS_TOP_K_HISTORY": 50,
    "RAG_FTS_TOP_K_MEMORIES": 50,
    "RAG_FTS_MAX_TERMS": 10,
    "RAG_FTS_MIN_LEN": 3,
    "RAG_MEMORY_MODE": "all",
    "RAG_COMBINE_MODE": "union",
    "RAG_VECTOR_TOP_K": 0,
    "RAG_INTERSECT_MIN_METHODS": 2,
    "RAG_INTERSECT_REQUIRE_VECTOR": True,
    "RAG_INTERSECT_FALLBACK_UNION": True,
    "RAG_TWO_STAGE_FALLBACK_UNION": True,
    "RAG_DETAILED_LOGS": True,
    "RAG_LOG_LIST_TOP_N": 10,
    "RAG_LOG_LIST_BOTTOM_N": 5,
    "RAG_LOG_LIST_SHOW_ALL": False,
}