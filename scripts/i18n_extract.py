"""Экстрактор строк локализации из UI-кода.

Сканирует ``src/ui/**`` (по умолчанию), находит вызовы локализации
``_( "ru", "en" )`` / ``getTranslationVariant(...)`` / алиасов с КОНСТАНТНЫМИ
строками и формирует JSON-каталоги:

  * ``src/localization/locales/en.json``        — ``{ ru: en }`` из 2-го аргумента;
  * ``src/localization/locales/_template.json`` — ``{ ru: "" }`` для всех ru-ключей
    (шаблон: копируешь в ``<lang>.json`` и переводишь).

f-строки и любые неконстантные аргументы пропускаются (их перевести статически
нельзя) — в конце печатается отчёт покрытия.

Запуск (любой python)::

    python scripts/i18n_extract.py
    python scripts/i18n_extract.py --src src/ui --out src/localization/locales
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

# Имена функций локализации (включая алиасы из `import ... as _`)
TR_FUNCS = {"_", "getTranslationVariant", "t", "_g"}


def _const_str(node: ast.expr | None) -> str | None:
    """Возвращает строковое значение, если узел — строковый литерал, иначе None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_file(path: Path) -> tuple[list[tuple[str, str]], int, int]:
    """Разбирает один файл.

    Возвращает (пары (ru, en), всего_вызовов_локализации, динамических_пропущено).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return [], 0, 0

    pairs: list[tuple[str, str]] = []
    total = 0
    dynamic = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if name not in TR_FUNCS:
            continue
        if not node.args:
            continue
        ru = _const_str(node.args[0])
        if ru is None:
            # Первый аргумент не строковый литерал (f-строка/переменная) — пропускаем.
            dynamic += 1
            total += 1
            continue
        total += 1
        en = _const_str(node.args[1]) if len(node.args) > 1 else None
        pairs.append((ru, en or ""))

    return pairs, total, dynamic


def main() -> int:
    project_dir = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Извлечь строки локализации из UI-кода.")
    ap.add_argument("--src", default=str(project_dir / "src" / "ui"),
                    help="папка для сканирования (default: src/ui)")
    ap.add_argument("--out", default=str(project_dir / "src" / "localization" / "locales"),
                    help="папка для JSON-каталогов")
    args = ap.parse_args()

    src_dir = Path(args.src)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not src_dir.is_dir():
        print(f"Папка не найдена: {src_dir}", file=sys.stderr)
        return 1

    all_keys: set[str] = set()
    en_seed: dict[str, str] = {}
    files_scanned = 0
    total_calls = 0
    dynamic_calls = 0

    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        pairs, total, dynamic = scan_file(path)
        files_scanned += 1
        total_calls += total
        dynamic_calls += dynamic
        for ru, en in pairs:
            all_keys.add(ru)
            if en and ru not in en_seed:
                en_seed[ru] = en

    # en.json: сохраняем ручные правки, добавляем новые ключи из инлайна.
    en_path = out_dir / "en.json"
    existing_en: dict[str, str] = {}
    if en_path.is_file():
        try:
            existing_en = json.loads(en_path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing_en = {}
    merged_en = dict(en_seed)
    merged_en.update(existing_en)  # ручные правки в файле приоритетнее инлайна

    en_path.write_text(
        json.dumps(dict(sorted(merged_en.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # _template.json: все ru-ключи -> "" (шаблон для новых языков).
    template = {k: "" for k in sorted(all_keys)}
    (out_dir / "_template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    static_keys = len(all_keys)
    print("=== i18n extract ===")
    print(f"Файлов просканировано: {files_scanned}")
    print(f"Вызовов локализации:   {total_calls}")
    print(f"  статических ключей:  {static_keys} (уникальных ru)")
    print(f"  с английским инлайн: {len(en_seed)}")
    print(f"  динамических (skip): {dynamic_calls}")
    cov = (100.0 * (total_calls - dynamic_calls) / total_calls) if total_calls else 0.0
    print(f"Покрытие статикой:     {cov:.1f}%")
    print(f"Записано: {en_path}")
    print(f"Записано: {out_dir / '_template.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
