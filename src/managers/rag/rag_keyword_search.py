from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Tuple, List, Set

from managers.rag.stopwords.stopwords import STOPWORDS

# Токены: латиница/кириллица/цифры (без подчёркиваний и прочего)
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
CYR_RE = re.compile(r"[А-Яа-яЁё]")


@lru_cache(maxsize=1)
def _get_morph():
    """
    Lazy-init MorphAnalyzer, чтобы:
    - не платить цену инициализации при импорте модуля
    - позволить использовать модуль без pymorphy2, пока lemmatize=False
    """
    import pymorphy2  # type: ignore

    return pymorphy2.MorphAnalyzer()


@lru_cache(maxsize=50_000)
def _normalize_token(token: str) -> str:
    """
    Нормализует (лемматизирует) токен, но только если в нём есть кириллица.
    Для латиницы/цифр/смешанных артикулов — возвращаем как есть (lower уже сделан).
    """
    t = (token or "").strip().lower()
    if not t:
        return ""

    # pymorphy2 имеет смысл только для русского (кириллица)
    if not CYR_RE.search(t):
        return t

    try:
        morph = _get_morph()
        parses = morph.parse(t)
        if not parses:
            return t
        return parses[0].normal_form
    except Exception:
        # pymorphy2 может быть не установлен или упасть на странном токене
        return t


def extract_keywords(
    text: str,
    *,
    max_terms: int = 8,
    min_len: int = 3,
    from_end: bool = False,
    lemmatize: bool = False,
) -> List[str]:
    """
    Достаёт ключевые слова из строки:
    - lower
    - убираем стоп-слова
    - убираем слишком короткие (если нет цифр)
    - убираем чисто цифровые токены
    - сохраняем порядок + dedup
    - опционально: лемматизация (pymorphy2) для русских слов
    """
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

        # стоп-слова по "сырому" токену
        if tt in STOPWORDS:
            continue

        # слишком короткие (если не содержат цифр)
        if len(tt) < int(min_len) and not any(ch.isdigit() for ch in tt):
            continue

        # чистые цифры не берём
        if tt.isdigit():
            continue

        # нормализация (если включена)
        kw = _normalize_token(tt) if lemmatize else tt
        if not kw:
            continue

        # и по нормальной форме тоже фильтруем стоп-слова
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
    """
    Подготавливает множество токенов текста для быстрого membership-теста.
    При lemmatize=True множества строится по леммам (для кириллицы).
    """
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
    """
    Возвращает (score 0..1, matches_count).
    Score = доля уникальных keywords, найденных в тексте.

    - lemmatize=False (по умолчанию): ищем каждое keyword в тексте regex-ом по границам слова.
    - lemmatize=True: сравнение по леммам (для кириллицы):
        keywords -> нормализуем,
        text -> токенизируем + нормализуем,
        затем kw in vocab.
    """
    if not isinstance(text, str) or not text.strip():
        return 0.0, 0

    # чистим + dedup с сохранением порядка
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

    # Старое поведение: regex по границам "слова"
    hay = text.lower()
    matches = 0

    for kw in uniq_kws:
        pat = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
        if re.search(pat, hay, flags=re.IGNORECASE):
            matches += 1

    score = float(matches) / float(max(1, len(uniq_kws)))
    return score, matches