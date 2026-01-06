from __future__ import annotations

import re
from typing import Iterable, Tuple, List

# Мини-стоплист (ru+en). Можно расширять.
_STOPWORDS = {
    # EN
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "so",
    "to", "of", "in", "on", "at", "for", "from", "with", "without", "into", "over", "under",
    "is", "are", "was", "were", "be", "been", "being",
    "i", "me", "my", "mine", "you", "your", "yours", "he", "him", "his", "she", "her", "hers",
    "it", "its", "we", "us", "our", "they", "them", "their",
    "this", "that", "these", "those", "here", "there",
    "what", "which", "who", "whom", "why", "how",
    "not", "no", "yes",
    # RU
    "и", "или", "но", "а", "что", "чтобы", "это", "как", "так", "вот",
    "я", "мы", "ты", "вы", "он", "она", "оно", "они",
    "меня", "мне", "мной", "тебя", "тебе", "тобой", "нас", "нам", "нами", "вас", "вам", "вами",
    "его", "её", "ее", "их",
    "мой", "моя", "моё", "мое", "мои", "твой", "твоя", "твое", "твоё", "твои", "ваш", "ваша", "ваше", "ваши",
    "этот", "эта", "эти", "то", "та", "те",
    "здесь", "там", "тут",
    "да", "нет",
    "не", "ни",
    "у", "в", "на", "по", "к", "ко", "из", "за", "для", "с", "со", "о", "об", "от", "до", "при",
}

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+")


def extract_keywords(text: str, *, max_terms: int = 8, min_len: int = 3) -> List[str]:
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
    out: List[str] = []
    seen = set()

    for t in tokens:
        tt = t.strip().lower()
        if not tt:
            continue
        if tt in _STOPWORDS:
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
