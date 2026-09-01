"""Конвертер многострочных текст-сеттеров `obj.setToolTip(_( ... ))` в tr_set.

Мигратор i18n_live_migrate.py работает построчно и многострочные `_( ... )`
пропускает. Этот скрипт через AST (с точными байтовыми офсетами — в строках
кириллица, поэтому col_offset байтовый) переписывает:

    obj.setToolTip(_(<многострочные ru, en>))
        ->  tr_set(obj, <ru, en>, "setToolTip")

Поддержанные сеттеры: setToolTip / setPlaceholderText / setStatusTip
(setText сознательно НЕ берём — он часто меняется по состоянию).

При изменении добавляет `from localization.live import tr_set` (если нет).

Запуск:  python scripts/i18n_live_tooltips.py [--dry] <файлы...>
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SETTERS = {"setToolTip", "setPlaceholderText", "setStatusTip"}
TR = {"_", "getTranslationVariant"}


def _line_byte_starts(src: str) -> list[int]:
    """Байтовый офсет начала каждой строки (1-based индексация снаружи)."""
    starts = [0]
    acc = 0
    for line in src.split("\n"):
        acc += len(line.encode("utf-8")) + 1  # +1 за '\n'
        starts.append(acc)
    return starts


def _abs(starts: list[int], lineno: int, col: int) -> int:
    return starts[lineno - 1] + col


def convert(path: Path, dry: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    bom = raw.startswith("﻿")
    src = raw[1:] if bom else raw
    try:
        tree = ast.parse(src)
    except SyntaxError:
        print(f"{path}: syntax error — пропуск")
        return 0

    starts = _line_byte_starts(src)
    src_b = src.encode("utf-8")

    edits: list[tuple[int, int, str]] = []  # (abs_start, abs_end, replacement)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in SETTERS):
            continue
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Call):
            continue
        inner = node.args[0]
        ifn = inner.func
        inm = ifn.id if isinstance(ifn, ast.Name) else (ifn.attr if isinstance(ifn, ast.Attribute) else None)
        if inm not in TR or not inner.args:
            continue

        setter = f.attr
        obj_b = src_b[_abs(starts, f.value.lineno, f.value.col_offset):
                      _abs(starts, f.value.end_lineno, f.value.end_col_offset)]
        a0, aN = inner.args[0], inner.args[-1]
        args_b = src_b[_abs(starts, a0.lineno, a0.col_offset):
                       _abs(starts, aN.end_lineno, aN.end_col_offset)]
        obj_s = obj_b.decode("utf-8")
        args_s = args_b.decode("utf-8")
        repl = f'tr_set({obj_s}, {args_s}, "{setter}")'

        edits.append((_abs(starts, node.lineno, node.col_offset),
                      _abs(starts, node.end_lineno, node.end_col_offset),
                      repl))

    if not edits:
        print(f"{path}: 0")
        return 0

    # Применяем с конца, чтобы не сбить офсеты.
    edits.sort(key=lambda e: e[0], reverse=True)
    out = src_b
    for s, e, repl in edits:
        out = out[:s] + repl.encode("utf-8") + out[e:]
    new_src = out.decode("utf-8")
    new_src = _ensure_import(new_src)

    if not dry:
        path.write_text(("﻿" if bom else "") + new_src, encoding="utf-8")
    print(f"{'[dry] ' if dry else ''}{path}: {len(edits)}")
    return len(edits)


def _ensure_import(src: str) -> str:
    if re.search(r"from localization\.live import [^\n]*\btr_set\b", src):
        return src
    lines = src.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\s*from utils import .*\b_\b", ln) or ln.strip() == "from utils import _":
            lines.insert(i + 1, "from localization.live import tr_set")
            return "\n".join(lines)
    return src


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    if not args:
        print("Укажите файлы", file=sys.stderr)
        return 1
    total = 0
    for a in args:
        total += convert(Path(a), dry)
    print(f"Итого: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
