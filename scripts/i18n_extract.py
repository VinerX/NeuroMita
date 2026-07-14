"""Экстрактор строк локализации из UI-кода.

Сканирует ``src/**`` (по умолчанию — весь код, т.к. UI-строки живут и вне
``src/ui``: в ``controllers``/``handlers`` через ``_()``), находит вызовы локализации
``_( "ru", "en" )`` / ``getTranslationVariant(...)`` / алиасов с КОНСТАНТНЫМИ
строками и формирует JSON-каталоги:

  * ``src/localization/locales/en.json``        — ``{ ru: en }`` из 2-го аргумента;
  * ``src/localization/locales/_template.json`` — ``{ ru: "" }`` для всех ru-ключей
    (шаблон: копируешь в ``<lang>.json`` и переводишь).

f-строки и любые неконстантные аргументы пропускаются (их перевести статически
нельзя) — в конце печатается отчёт покрытия.

Запуск (любой python)::

    python scripts/i18n_extract.py
    python scripts/i18n_extract.py --src src --out src/localization/locales
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Имена функций локализации с сигнатурой (ru, en) — включая алиасы `import ... as _`.
TR_FUNCS = {"_", "getTranslationVariant", "t", "_g"}
# Функции с сигнатурой (lang, ru, en) — ключ/инлайн сдвинуты на один аргумент.
TR_FUNCS_LANG_FIRST = {"translate_for_language"}
# Live-локализация виджетов: первый аргумент — сам виджет, затем (ru, en).
TR_FUNCS_WIDGET_FIRST = {"tr_set": (1, 2), "tr_tab_text": (2, 3)}


def _const_str(node: ast.expr | None) -> str | None:
    """Возвращает строковое значение, если узел — строковый литерал, иначе None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _source_pairs(tree: ast.AST) -> list[tuple[str, str]]:
    """Extract static ``*_SOURCES`` maps used by long-lived localized views.

    Such maps keep translation source pairs unevaluated until render time, so
    the regular ``_(ru, en)`` call scanner cannot see their literal values.
    """
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not any(name.endswith("_SOURCES") for name in names):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for item in value.values:
            if not isinstance(item, (ast.Tuple, ast.List)) or len(item.elts) < 2:
                continue
            ru = _const_str(item.elts[0])
            en = _const_str(item.elts[1])
            if ru is not None:
                pairs.append((ru, en or ""))
    return pairs


def scan_file(path: Path) -> tuple[list[tuple[str, str]], int, int, str | None]:
    """Разбирает один файл.

    Возвращает ``(пары (ru, en), всего_вызовов, динамических_пропущено, ошибка)``.
    ``ошибка`` — ``None`` при успехе, иначе короткая строка с причиной, чтобы
    вызывающий мог ГРОМКО отчитаться (а не молча потерять весь файл).

    Читаем через ``utf-8-sig``: это снимает BOM (``U+FEFF``), из-за которого
    ``ast.parse`` иначе падает ``SyntaxError`` — именно так десятки файлов с BOM
    годами выпадали из экстракта и «утекали» английским в другие языки.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError) as exc:
        return [], 0, 0, f"decode: {exc}"
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [], 0, 0, f"parse: {exc.msg} (строка {exc.lineno})"

    pairs: list[tuple[str, str]] = []
    total = 0
    dynamic = 0

    pairs.extend(_source_pairs(tree))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # имя функции: и f(...), и obj.method(...)
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            name = None
        lang_first = name in TR_FUNCS_LANG_FIRST
        widget_first = TR_FUNCS_WIDGET_FIRST.get(name)
        if name not in TR_FUNCS and not lang_first and widget_first is None:
            continue
        # Сдвиг аргументов для (lang, ru, en) против (ru, en).
        if widget_first is not None:
            ru_idx, en_idx = widget_first
        else:
            ru_idx, en_idx = (1, 2) if lang_first else (0, 1)
        if len(node.args) <= ru_idx:
            continue
        ru = _const_str(node.args[ru_idx])
        if ru is None:
            # Ключевой аргумент не строковый литерал (f-строка/переменная) — пропускаем.
            dynamic += 1
            total += 1
            continue
        total += 1
        en = _const_str(node.args[en_idx]) if len(node.args) > en_idx else None
        pairs.append((ru, en or ""))

    return pairs, total, dynamic, None


def _iter_py(src_dir: Path):
    """Все .py под src_dir, кроме кэша и вложенных worktree (`.claude`)."""
    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts or ".claude" in path.parts:
            continue
        yield path


def _scan_tree(src_dir: Path):
    """Просканировать дерево. Возвращает ``(all_keys, en_seed, stats, failures)``.

    ``failures`` — список ``(rel_path, reason)`` файлов, которые НЕ распарсились
    (BOM/синтаксис/кодировка). Раньше они молча терялись — теперь их видно.
    """
    all_keys: set[str] = set()
    en_seed: dict[str, str] = {}
    files_scanned = total_calls = dynamic_calls = 0
    failures: list[tuple[str, str]] = []

    for path in _iter_py(src_dir):
        pairs, total, dynamic, err = scan_file(path)
        files_scanned += 1
        if err is not None:
            try:
                rel = path.relative_to(src_dir.parent).as_posix()
            except ValueError:
                rel = path.as_posix()
            failures.append((rel, err))
            continue
        total_calls += total
        dynamic_calls += dynamic
        for ru, en in pairs:
            all_keys.add(ru)
            if en and ru not in en_seed:
                en_seed[ru] = en

    stats = {
        "files": files_scanned,
        "calls": total_calls,
        "dynamic": dynamic_calls,
    }
    return all_keys, en_seed, stats, failures


def _print_failures(failures: list[tuple[str, str]]) -> None:
    if not failures:
        return
    print(f"\n!!! НЕ РАСПАРСИЛИСЬ (строки локализации потеряны): {len(failures)}")
    for rel, reason in failures:
        print(f"    {rel}  —  {reason}")
    print("    Скорее всего UTF-8 BOM. Пересохрани файл как UTF-8 без BOM "
          "(или экстрактор их пропустит, а переводы утекут английским).")


def main() -> int:
    # Вывод содержит кириллицу/символы валют (₽): консоль Windows по умолчанию
    # cp1251 и падает UnicodeEncodeError. Переводим stdout на UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    project_dir = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Извлечь строки локализации из UI-кода.")
    ap.add_argument("--src", default=str(project_dir / "src"),
                    help="папка для сканирования (default: src — весь код, "
                         "т.к. UI-строки живут и вне src/ui: controllers/handlers)")
    ap.add_argument("--out", default=str(project_dir / "src" / "localization" / "locales"),
                    help="папка для JSON-каталогов")
    ap.add_argument("--sync", action="store_true",
                    help="отчёт по каждому <lang>.json: осиротевшие ключи "
                         "(исходник изменился/удалён) и недостающие/пустые переводы")
    ap.add_argument("--prune", action="store_true",
                    help="вместе с --sync: реально удалить осиротевшие ключи из <lang>.json")
    ap.add_argument("--check", action="store_true",
                    help="ТОЛЬКО проверка (файлы не пишутся): сканит ВЕСЬ src, "
                         "репортит парс-фейлы + недостающие/англ-заглушки по языкам, "
                         "возвращает ненулевой код при проблемах (для CI/pre-commit)")
    args = ap.parse_args()

    out_dir = Path(args.out)

    if args.check:
        return _check(project_dir / "src", out_dir)

    src_dir = Path(args.src)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not src_dir.is_dir():
        print(f"Папка не найдена: {src_dir}", file=sys.stderr)
        return 1

    all_keys, en_seed, stats, failures = _scan_tree(src_dir)
    files_scanned = stats["files"]
    total_calls = stats["calls"]
    dynamic_calls = stats["dynamic"]

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
    _print_failures(failures)

    if args.sync:
        _sync_languages(out_dir, all_keys, prune=args.prune)
    return 0


# Кириллица в ключе → это RU-строка, которую переводчик обязан был локализовать.
_CYRILLIC = re.compile("[А-Яа-яЁё]")


def _check(src_dir: Path, out_dir: Path) -> int:
    """Read-only валидатор для CI: сканит ВЕСЬ src, ничего не пишет.

    Падает (код 1), если:
      * есть файлы, которые не распарсились (BOM/синтаксис) — их строки утекут;
      * в каком-то <lang>.json есть недостающие ключи или англ-заглушки
        (value идентичен английскому инлайну при кириллическом ключе).
    """
    all_keys, en_seed, stats, failures = _scan_tree(src_dir)

    print("=== i18n check (весь src, read-only) ===")
    print(f"Файлов: {stats['files']}   ключей: {len(all_keys)}   "
          f"с англ-инлайном: {len(en_seed)}")
    _print_failures(failures)

    problems = len(failures)

    print("\n=== Покрытие по языкам ===")
    for path in sorted(out_dir.glob("*.json")):
        name = path.name
        if name.startswith("_") or name == "en.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            print(f"  {name}: не удалось прочитать — пропуск")
            problems += 1
            continue
        missing = sorted(k for k in all_keys if not data.get(k))
        # «Англ-заглушка»: перевод есть, но он дословно равен английскому инлайну,
        # а ключ — кириллица. Значит забыли перевести (оставили английскую рыбу).
        leftover = sorted(
            k for k in all_keys
            if data.get(k) and en_seed.get(k)
            and data[k] == en_seed[k] and _CYRILLIC.search(k)
        )
        problems += len(missing) + len(leftover)
        print(f"  {name}: недостающих {len(missing)}, англ-заглушек {len(leftover)}")
        for k in leftover[:8]:
            print(f"      англ-заглушка: {k!r} = {data[k]!r}")

    if problems:
        print(f"\nПРОВАЛ: проблем {problems}. "
              f"Прогони `python scripts/i18n_extract.py` и допереведи каталоги.")
        return 1
    print("\nОК: локализация полная, парс-фейлов нет.")
    return 0


def _sync_languages(out_dir: Path, all_keys: set[str], *, prune: bool) -> None:
    """Отчёт по существующим <lang>.json относительно актуального набора ключей.

    Осиротевшие = ключи в файле, которых больше нет в коде (исходная русская
    строка изменилась/удалена) → перевод протух. Недостающие = ключи из кода,
    которых нет в файле или их значение пустое. С --prune осиротевшие удаляются.
    """
    print("\n=== i18n sync ===")
    for path in sorted(out_dir.glob("*.json")):
        name = path.name
        if name.startswith("_") or name == "en.json":
            continue  # _template/_*.json и en.json генерируются автоматически
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            print(f"  {name}: не удалось прочитать — пропуск")
            continue
        # «_name» и прочие служебные ключи (с префиксом _) не считаем сиротами.
        content_keys = {k for k in data if not k.startswith("_")}
        orphaned = sorted(content_keys - all_keys)
        missing = sorted(k for k in all_keys if not data.get(k))
        print(f"  {name}: переведено {len(content_keys)}/{len(all_keys)}, "
              f"осиротевших {len(orphaned)}, недостающих {len(missing)}")
        if orphaned and prune:
            for k in orphaned:
                data.pop(k, None)
            path.write_text(
                json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"    └─ удалено осиротевших: {len(orphaned)}")


if __name__ == "__main__":
    raise SystemExit(main())
