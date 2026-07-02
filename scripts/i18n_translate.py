"""Методика пакетного перевода UI-локалей агентами/нейронкой.

Перевод одного языка делается в три шага:

  1. ``split``   — нарезает английские значения из ``en.json`` на N батч-файлов
                   ``i18n_batches/<lang>_in_<n>.json`` (``{ru_key: en_value}``).
  2. (вне скрипта) каждый батч переводит агент/нейронка, СОХРАНЯЯ ключи и
                   плейсхолдеры, и пишет ``i18n_batches/<lang>_out_<n>.json``
                   (``{ru_key: translation}``). Правила — в ``i18n_batches/RULES.md``,
                   глоссарий — в ``i18n_batches/glossary_<lang>.md``.
  3. ``merge``   — валидирует плейсхолдеры/пробелы и сливает ``*_out_*.json`` в
                   ``localization/locales/<lang>.json``.

Дополнительно:
  * ``validate <lang>`` — проверить готовый ``<lang>.json`` против ``en.json``
    (плейсхолдеры, пустые/совпадающие с английским значения).
  * ``--only-missing`` у ``split`` — выгружать только непереведённые строки
    (нет в ``<lang>.json`` или значение == английскому), удобно для дозаливки.

Запуск (любой python)::

    python scripts/i18n_translate.py split de --batches 5
    python scripts/i18n_translate.py merge de
    python scripts/i18n_translate.py validate de
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = PROJECT_DIR / "src" / "localization" / "locales"
BATCH_DIR = PROJECT_DIR / "scripts" / "i18n_batches"

# Плейсхолдеры, которые обязаны сохраниться в переводе один-в-один.
_PH_BRACE = re.compile(r"\{[^}]*\}")
_PH_PCT = re.compile(r"%[sd]")
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002190-\U000021FF\U00002B00-\U00002BFF]"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) or {}


def _dump(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _signature(s: str) -> tuple:
    """Набор «инвариантов» строки, которые перевод обязан сохранить."""
    return (
        sorted(_PH_BRACE.findall(s)),
        sorted(_PH_PCT.findall(s)),
        len(_EMOJI.findall(s)),
        s[:1] == " ",   # ведущий пробел
        s[-1:] == " ",  # хвостовой пробел
    )


def cmd_split(args) -> int:
    en = _load(LOCALES_DIR / "en.json")
    target = args.lang.lower()
    if args.only_missing:
        existing = {}
        p = LOCALES_DIR / f"{target}.json"
        if p.is_file():
            existing = _load(p)
        items = sorted(
            (ru, en_val) for ru, en_val in en.items()
            if not existing.get(ru) or existing.get(ru) == en_val
        )
    else:
        items = sorted(en.items())

    if not items:
        print("Нечего выгружать (всё переведено?).")
        return 0

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    n = max(1, args.batches)
    size = math.ceil(len(items) / n)
    written = 0
    for i in range(n):
        chunk = dict(items[i * size:(i + 1) * size])
        if not chunk:
            continue
        _dump(BATCH_DIR / f"{target}_in_{i + 1}.json", chunk)
        written += 1
        print(f"  {target}_in_{i + 1}.json: {len(chunk)} строк")
    print(f"Готово: {written} батч(ей), всего {len(items)} строк → {BATCH_DIR}")
    print(f"Дальше переведи *_out_*.json (см. RULES.md), потом: merge {target}")
    return 0


def cmd_merge(args) -> int:
    en = _load(LOCALES_DIR / "en.json")
    target = args.lang.lower()
    out_files = sorted(BATCH_DIR.glob(f"{target}_out_*.json"))
    if not out_files:
        print(f"Не найдено {target}_out_*.json в {BATCH_DIR}", file=sys.stderr)
        return 1

    merged: dict[str, str] = {}
    problems: list[str] = []
    for f in out_files:
        data = _load(f)
        for k, v in data.items():
            if k in en and _signature(en[k]) != _signature(v):
                problems.append(f"{f.name}: плейсхолдер/пробел не совпал у {k!r} -> {v!r}")
            merged[k] = v

    if problems:
        print(f"⚠ Проблемы валидации ({len(problems)}) — слияние ОТМЕНЕНО:")
        for p in problems[:50]:
            print("  " + p)
        return 2

    dest = LOCALES_DIR / f"{target}.json"
    existing = _load(dest) if dest.is_file() else {}
    existing.update(merged)
    _dump(dest, existing)
    print(f"Слито {len(merged)} строк → {dest} (итого ключей: {len(existing)})")
    return 0


def cmd_validate(args) -> int:
    en = _load(LOCALES_DIR / "en.json")
    target = args.lang.lower()
    dest = LOCALES_DIR / f"{target}.json"
    if not dest.is_file():
        print(f"Нет файла {dest}", file=sys.stderr)
        return 1
    data = _load(dest)
    ph_bad = [k for k in data if k in en and _signature(en[k]) != _signature(data[k])]
    empty = [k for k in en if not data.get(k)]
    same_as_en = [k for k in data if k in en and data[k] == en[k] and en[k] != k]
    print(f"=== validate {target} ===")
    print(f"ключей: {len(data)} / {len(en)}")
    print(f"плейсхолдер/пробел рассинхрон: {len(ph_bad)}")
    print(f"пустых/недостающих: {len(empty)}")
    print(f"совпадает с английским (возможно не переведено): {len(same_as_en)}")
    for k in ph_bad[:30]:
        print(f"  PH  {k!r} -> {data[k]!r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("split", help="нарезать en.json на батчи для перевода")
    sp.add_argument("lang", help="код языка, напр. de/zh/uk/el")
    sp.add_argument("--batches", type=int, default=5)
    sp.add_argument("--only-missing", action="store_true", help="только непереведённые строки")
    sp.set_defaults(func=cmd_split)

    mp = sub.add_parser("merge", help="слить *_out_*.json в <lang>.json с валидацией")
    mp.add_argument("lang")
    mp.set_defaults(func=cmd_merge)

    vp = sub.add_parser("validate", help="проверить готовый <lang>.json")
    vp.add_argument("lang")
    vp.set_defaults(func=cmd_validate)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
