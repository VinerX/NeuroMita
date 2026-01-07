from __future__ import annotations

import re
from typing import Iterable, Tuple, List

from managers.rag.stopwords.stopwords import STOPWORDS

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+")

def extract_keywords(text: str, *, max_terms: int = 8, min_len: int = 3, from_end: bool = False) -> List[str]:
    """
    Достаёт ключевые слова из строки:
    - lower
    - убираем стоп-слова
    - убираем слишком короткие (если нет цифр)
    - сохраняем порядок + dedup
    """
    if not isinstance(text, str):
        return []
    raw = text.strip().lower()
    if not raw:
        return []

    tokens = _TOKEN_RE.findall(raw)
    if from_end:
        tokens = list(reversed(tokens))

    out: List[str] = []
    seen = set()

    for t in tokens:
        tt = t.strip().lower()
        if not tt:
            continue
        if tt in STOPWORDS:
            continue
        if len(tt) < int(min_len):
            if not any(ch.isdigit() for ch in tt):
                continue
        if tt.isdigit():
            continue
        if tt in seen:
            continue
        out.append(tt)
        seen.add(tt)
        if len(out) >= int(max_terms):
            break

    if from_end:
        out = list(reversed(out))

    return out


def keyword_score(keywords: Iterable[str], text: str) -> Tuple[float, int]:
    """
    Возвращает (score 0..1, matches_count).
    Score = доля уникальных keywords, найденных в тексте.
    """
    kws = [str(k).strip().lower() for k in (keywords or []) if str(k).strip()]
    if not kws:
        return 0.0, 0
    if not isinstance(text, str) or not text.strip():
        return 0.0, 0

    hay = text.lower()
    matches = 0

    for kw in kws:
        pat = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
        if re.search(pat, hay, flags=re.IGNORECASE):
            matches += 1

    score = float(matches) / float(max(1, len(kws)))
    return score, matches
