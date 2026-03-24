import re
from functools import lru_cache
from typing import Iterable, Tuple, List, Set, Any, Optional
import numpy as np

from utils.throttled_progress_logger import ThrottledProgressLogger
from main_logger import logger
from managers.rag.stopwords.stopwords import STOPWORDS

# --- Text Cleaning ---

def rag_clean_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""

    t = text

    # 1) убрать memory-команды целиком (обычно с закрывающим </memory>)
    t = re.sub(r"<[+\-#]memory>.*?</memory>", " ", t, flags=re.S | re.I)

    # 2) убрать pose/числовые векторы (часто повторяющиеся)
    t = re.sub(r"<p>\s*[-0-9\.,\s]+\s*</p>", " ", t, flags=re.I)

    # 3) убрать сами теги, но оставить внутренний текст
    t = re.sub(r"</?[^>]+>", " ", t)

    # 4) схлопнуть пробелы
    t = re.sub(r"\s+", " ", t).strip()
    return t


def make_reindex_progress_logger(rag_manager, op: str, total: int, extra_meta: str = "") -> ThrottledProgressLogger:
    log_every = rag_manager._get_int_setting("RAG_REINDEX_LOG_EVERY", 50)
    log_interval = rag_manager._get_float_setting("RAG_REINDEX_LOG_INTERVAL_SEC", 5.0)
    if log_every <= 0:
        log_every = 50
    if log_interval <= 0:
        log_interval = 5.0

    meta = f"character_id={rag_manager.character_id}"
    if extra_meta:
        meta = f"{meta} | {extra_meta}"

    return ThrottledProgressLogger(
        info=logger.info,
        op=f"[RAG] {op}",
        total=int(total),
        meta=meta,
        log_every=int(log_every),
        log_interval_sec=float(log_interval),
    )

# --- Keyword Search Logic (from rag_keyword_search.py) ---

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
CYR_RE = re.compile(r"[А-Яа-яЁё]")


@lru_cache(maxsize=1)
def _get_morph():
    import pymorphy2  # type: ignore
    return pymorphy2.MorphAnalyzer()


@lru_cache(maxsize=50_000)
def _normalize_token(token: str) -> str:
    t = (token or "").strip().lower()
    if not t:
        return ""
    if not CYR_RE.search(t):
        return t
    try:
        morph = _get_morph()
        parses = morph.parse(t)
        if not parses:
            return t
        return parses[0].normal_form
    except Exception:
        return t


def extract_keywords(
    text: str,
    *,
    max_terms: int = 8,
    min_len: int = 3,
    from_end: bool = False,
    lemmatize: bool = False,
) -> List[str]:
    if not isinstance(text, str):
        return []

    raw = text.strip().lower()
    if not raw:
        return []

    tokens = TOKEN_RE.findall(raw)
    if from_end:
        tokens = list(reversed(tokens))

    out: List[str] = []
    seen: Set[str] = set()

    for t in tokens:
        tt = t.strip().lower()
        if not tt:
            continue
        if tt in STOPWORDS:
            continue
        if len(tt) < int(min_len) and not any(ch.isdigit() for ch in tt):
            continue
        if tt.isdigit():
            continue
        kw = _normalize_token(tt) if lemmatize else tt
        if not kw:
            continue
        if kw in STOPWORDS:
            continue
        if kw in seen:
            continue
        out.append(kw)
        seen.add(kw)
        if len(out) >= int(max_terms):
            break

    if from_end:
        out = list(reversed(out))
    return out


def _normalized_text_vocab(text: str, *, min_len: int = 3, lemmatize: bool = False) -> Set[str]:
    if not isinstance(text, str):
        return set()
    raw = text.strip().lower()
    if not raw:
        return set()
    vocab: Set[str] = set()
    for t in TOKEN_RE.findall(raw):
        tt = t.strip().lower()
        if not tt:
            continue
        if tt.isdigit():
            continue
        if len(tt) < int(min_len) and not any(ch.isdigit() for ch in tt):
            continue
        vocab.add(_normalize_token(tt) if lemmatize else tt)
    vocab.discard("")
    return vocab


def keyword_score(
    keywords: Iterable[str],
    text: str,
    *,
    lemmatize: bool = False,
    min_len: int = 3,
) -> Tuple[float, int]:
    if not isinstance(text, str) or not text.strip():
        return 0.0, 0
    uniq_kws: List[str] = []
    seen: Set[str] = set()
    for k in keywords or []:
        kw = str(k).strip().lower()
        if not kw:
            continue
        if kw in seen:
            continue
        seen.add(kw)
        uniq_kws.append(kw)
    if not uniq_kws:
        return 0.0, 0
    if lemmatize:
        norm_kws: List[str] = []
        seen_norm: Set[str] = set()
        for kw in uniq_kws:
            if kw.isdigit():
                continue
            if len(kw) < int(min_len) and not any(ch.isdigit() for ch in kw):
                continue
            nk = _normalize_token(kw)
            if not nk:
                continue
            if nk in STOPWORDS:
                continue
            if nk in seen_norm:
                continue
            seen_norm.add(nk)
            norm_kws.append(nk)
        if not norm_kws:
            return 0.0, 0
        vocab = _normalized_text_vocab(text, min_len=min_len, lemmatize=True)
        matches = sum(1 for kw in norm_kws if kw in vocab)
        score = float(matches) / float(max(1, len(norm_kws)))
        return score, matches
    hay = text.lower()
    matches = 0
    for kw in uniq_kws:
        pat = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
        if re.search(pat, hay, flags=re.IGNORECASE):
            matches += 1
    score = float(matches) / float(max(1, len(uniq_kws)))
    return score, matches

# --- FTS Helpers (moved from RAGManager) ---

def fts_morph_expand_token(token: str, *, max_forms: int = 20) -> List[str]:
    """Return all word forms for a Cyrillic token using pymorphy2.

    Returns the original token (in a list) for non-Cyrillic input or on error.
    Caps at *max_forms* entries to avoid excessively long FTS queries.
    """
    t = token.strip().lower()
    if not t or not CYR_RE.search(t):
        return [t] if t else []
    try:
        morph = _get_morph()
        parses = morph.parse(t)
        if not parses:
            return [t]
        forms: set[str] = {t}
        for form in parses[0].lexeme:
            w = form.word.strip().lower()
            if w:
                forms.add(w)
        result = sorted(forms)
        return result[:max_forms]
    except Exception:
        return [t]


def fts_build_match_query(
    text: str,
    *,
    max_terms: int,
    min_len: int,
    morph_expand: bool = False,
    prefix_match: bool = False,
) -> str:
    """Build an FTS5 MATCH query string.

    Parameters
    ----------
    text:          Source text to tokenize.
    max_terms:     Maximum number of *original* tokens to include (each may
                   expand to multiple forms when morph_expand is True).
    min_len:       Minimum token length to include.
    morph_expand:  If True, expand each Cyrillic token to all its word forms
                   (declensions / conjugations) using pymorphy2.  This greatly
                   improves Russian-language recall because FTS5 stores raw
                   text and does not perform morphological normalisation.
    prefix_match:  If True, append ``*`` wildcard to each term so that FTS5
                   treats it as a prefix query.  Applied to non-Cyrillic tokens
                   regardless of *morph_expand*, and to Cyrillic tokens when
                   *morph_expand* is False.
    """
    cleaned = rag_clean_text(str(text or ""))
    if not cleaned:
        return ""
    tokens = re.findall(r"[0-9A-Za-zА-Яа-я_]+", cleaned.lower())

    all_terms: List[str] = []   # final FTS terms joined by OR
    base_count = 0
    seen_base: Set[str] = set()

    for t in tokens:
        t = t.strip().strip('"').strip("'")
        if len(t) < int(min_len):
            continue
        if t in STOPWORDS:
            continue
        if t in seen_base:
            continue
        seen_base.add(t)

        is_cyr = bool(CYR_RE.search(t))

        if morph_expand and is_cyr:
            forms = fts_morph_expand_token(t)
            for f in forms:
                all_terms.append(f'"{f}"')
        elif prefix_match:
            all_terms.append(f'"{t}"*')
        else:
            all_terms.append(f'"{t}"')

        base_count += 1
        if base_count >= int(max_terms):
            break

    return " OR ".join(all_terms)


def normalize_bm25_to_01(ranks: List[float]) -> List[float]:
    rr: List[float] = []
    for x in ranks or []:
        try:
            v = float(x)
            if np.isnan(v) or np.isinf(v):
                v = 0.0
            rr.append(v)
        except Exception:
            rr.append(0.0)
    if not rr:
        return []
    mn = min(rr)
    mx = max(rr)
    if abs(mx - mn) < 1e-12:
        return [1.0 for _ in rr]
    out: List[float] = []
    for v in rr:
        s = 1.0 - ((v - mn) / (mx - mn))
        if s < 0.0: s = 0.0
        if s > 1.0: s = 1.0
        out.append(float(s))
    return out
