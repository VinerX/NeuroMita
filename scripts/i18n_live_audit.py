"""Аудит «нелайв» мест локализации на персистентных поверхностях UI.

Находит вызовы локализации `_()`/`getTranslationVariant()`, переданные ПРЯМО
аргументом в конструктор виджета (QLabel/QPushButton/…) или в текст-сеттер
(setText/setToolTip/addTab/…). Такие места НЕ обновляются вживую: у уже
мигрированных через `tr_set`/`register_if_tr` голые строки, а не `_()`.

`_()`, переданный в инструментированный билдер (`_make_strip`, `create_setting_widget`,
`DashboardAction`, …), считается ЖИВЫМ и не флагуется — он не является прямым
аргументом виджета/сеттера.

Сканирует только персистентные папки (pages/widgets/settings/chat + main_window),
пропуская транзиентные диалоги (создаются заново при открытии → язык подхватывают).

Запуск:  python scripts/i18n_live_audit.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "ui"

TR_FUNCS = {"_", "getTranslationVariant"}
WIDGET_CTORS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QToolButton",
    "QGroupBox", "QCommandLinkButton", "QAction",
}
TEXT_SETTERS = {
    "setText", "setToolTip", "setTitle", "setWindowTitle", "setPlaceholderText",
    "setStatusTip", "addTab", "addItem", "insertItem", "setTabText",
}

# Персистентные поверхности (живут всё время) — их и проверяем.
INCLUDE_DIRS = ("pages", "widgets", "settings", "chat")
INCLUDE_FILES = ("windows/main_window.py", "windows/app_window_base.py")
# Транзиентные — открываются по требованию, язык подхватывают при переоткрытии.
EXCLUDE_PARTS = ("dialogs", "__pycache__")


def _is_tr_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
    return name in TR_FUNCS


def _func_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def scan(path: Path) -> list[tuple[int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    src = src.lstrip("﻿")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _func_name(node)
        if name not in WIDGET_CTORS and name not in TEXT_SETTERS:
            continue
        # есть ли среди аргументов прямой вызов _()/getTranslationVariant()?
        if any(_is_tr_call(a) for a in node.args):
            ln = node.lineno
            text = lines[ln - 1].strip() if 0 <= ln - 1 < len(lines) else ""
            hits.append((ln, text))
    return hits


def _included(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if rel in INCLUDE_FILES:
        return True
    top = rel.split("/", 1)[0]
    return top in INCLUDE_DIRS


def main() -> int:
    total = 0
    files = 0
    for path in sorted(ROOT.rglob("*.py")):
        if not _included(path):
            continue
        hits = scan(path)
        if not hits:
            continue
        files += 1
        total += len(hits)
        print(f"\n{path.relative_to(ROOT.parent.parent).as_posix()}  ({len(hits)})")
        for ln, text in hits:
            print(f"  {ln}: {text[:110]}")
    print(f"\n=== ИТОГО: {total} нелайв-кандидатов в {files} файлах ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
