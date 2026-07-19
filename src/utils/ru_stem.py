"""
Лёгкий стеммер русского языка (компактная реализация алгоритма Snowball Russian).

Чистый Python, без ML-зависимостей — работает и в боевом ``libs/python`` без torch.
Используется там, где RAG деградирует в FTS/keyword-режим и нужен хоть какой-то
морфологический recall («играли» → «игра» → находит «играть»), а также для
лексического дедупа памяти.

Публичные функции:
- ``ru_stem(word)`` — стеммировать одно слово (кириллица; латиница/цифры возвращаются как есть).
- ``stem_text(text)`` — стеммировать все словоформы в строке, сохраняя разделители.
"""

import re

__all__ = ["ru_stem", "stem_text"]

_VOWELS = "аеиоуыэюяё"

# Окончания по группам Snowball Russian (в порядке проверки — длинные раньше).
_PERFECTIVE_GERUND_1 = ("вшись", "вши", "в")          # после а/я
_PERFECTIVE_GERUND_2 = ("ившись", "ывшись", "ивши", "ывши", "ив", "ыв")
_ADJECTIVE = (
    "ими", "ыми", "его", "его", "ому", "ему", "ыми", "ой", "ей", "ый", "ий",
    "ая", "яя", "ую", "юю", "ое", "ее", "ым", "им", "ом", "ем", "их", "ых",
    "ую", "юю", "ое", "ее", "ого",
)
_PARTICIPLE_1 = ("ем", "нн", "вш", "ющ", "щ")           # после а/я
_PARTICIPLE_2 = ("ивш", "ывш", "ующ")
_REFLEXIVE = ("ся", "сь")
_VERB_1 = (
    "ла", "на", "ете", "йте", "ли", "й", "л", "ем", "н", "ло", "но", "ет",
    "ют", "ны", "ть", "ешь", "нно",
)
_VERB_2 = (
    "ила", "ыла", "ена", "ейте", "уйте", "ите", "или", "ыли", "ей", "уй",
    "ил", "ыл", "им", "ым", "ен", "ило", "ыло", "ено", "ят", "ует", "уют",
    "ит", "ыт", "ены", "ить", "ыть", "ишь", "ую", "ю",
)
_NOUN = (
    "а", "ев", "ов", "ие", "ье", "е", "иями", "ями", "ами", "еи", "ии", "и",
    "ией", "ей", "ой", "ий", "й", "иям", "ям", "ием", "ем", "ам", "ом", "о",
    "у", "ах", "иях", "ях", "ы", "ь", "ию", "ью", "ю", "ия", "ья", "я",
)
_DERIVATIONAL = ("ост", "ость")
_SUPERLATIVE = ("ейш", "ейше")


def _rv_region(word: str) -> int:
    """RV: область после первой гласной."""
    for i, ch in enumerate(word):
        if ch in _VOWELS:
            return i + 1
    return len(word)


def _try_replace(word: str, rv: int, endings, must_precede_ayo=False) -> tuple:
    """Пытаемся снять одно из окончаний в области RV. Возвращает (word, changed)."""
    region = word[rv:]
    for end in sorted(endings, key=len, reverse=True):
        if region.endswith(end):
            base_len = len(word) - len(end)
            if must_precede_ayo:
                # группа 1 требует, чтобы перед окончанием стояла а или я
                if base_len - 1 < rv:
                    continue
                if word[base_len - 1] not in ("а", "я"):
                    continue
            return word[:base_len], True
    return word, False


def ru_stem(word: str) -> str:
    """Стеммировать одно русское слово. Не-кириллица возвращается как есть (lower)."""
    w = str(word or "").lower().replace("ё", "е")
    if len(w) < 3 or not re.match(r"^[а-я]+$", w):
        return w

    rv = _rv_region(w)

    # Step 1: perfective gerund
    w2, changed = _try_replace(w, rv, _PERFECTIVE_GERUND_2)
    if not changed:
        w2, changed = _try_replace(w, rv, _PERFECTIVE_GERUND_1, must_precede_ayo=True)
    if changed:
        w = w2
    else:
        # reflexive
        w, _ = _try_replace(w, rv, _REFLEXIVE)
        # adjectival / participle / verb / noun (первое сработавшее)
        w3, ch = _try_replace(w, rv, _PARTICIPLE_2)
        if not ch:
            w3, ch = _try_replace(w, rv, _PARTICIPLE_1, must_precede_ayo=True)
        if ch:
            w = w3
            w, _ = _try_replace(w, rv, _ADJECTIVE)
        else:
            w3, ch = _try_replace(w, rv, _ADJECTIVE)
            if ch:
                w = w3
            else:
                w3, ch = _try_replace(w, rv, _VERB_2)
                if not ch:
                    w3, ch = _try_replace(w, rv, _VERB_1, must_precede_ayo=True)
                if ch:
                    w = w3
                else:
                    w, _ = _try_replace(w, rv, _NOUN)

    # Step 2: удаляем «и» на конце RV
    if w[rv:].endswith("и"):
        w = w[:-1]

    # Step 3: derivational (ость/ост)
    w, _ = _try_replace(w, rv, _DERIVATIONAL)

    # Step 4: превосходная степень + двойное «н» + мягкий знак
    if w[rv:].endswith("нн"):
        w = w[:-1]
    else:
        w2, ch = _try_replace(w, rv, _SUPERLATIVE)
        if ch:
            w = w2
            if w[rv:].endswith("нн"):
                w = w[:-1]
    if w[rv:].endswith("ь"):
        w = w[:-1]

    return w


_WORD_RE = re.compile(r"[а-яёА-ЯЁ]+|[a-zA-Z0-9]+|[^а-яёА-ЯЁa-zA-Z0-9]+")


def stem_text(text: str) -> str:
    """Стеммировать русские словоформы в строке, сохранив пробелы/пунктуацию/латиницу."""
    out = []
    for tok in _WORD_RE.findall(str(text or "")):
        if re.match(r"^[а-яёА-ЯЁ]+$", tok):
            out.append(ru_stem(tok))
        else:
            out.append(tok.lower() if tok.isalnum() else tok)
    return "".join(out)
