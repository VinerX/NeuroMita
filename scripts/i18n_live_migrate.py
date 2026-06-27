"""Однопроходный мигратор «прямых» вызовов локализации на live-обёртку tr_set.

Трогает ТОЛЬКО безопасные однострочные шаблоны, где ``_( ... )`` является
ЕДИНСТВЕННЫМ аргументом конструктора/сеттера и целиком помещается на строке:

  * ``x = QLabel(_(A, B))``      -> ``x = tr_set(QLabel(), A, B)``
    (QPushButton/QCheckBox/QRadioButton/QToolButton -> setText; QGroupBox -> setTitle)
  * ``obj.setText(_(A, B))``     -> ``tr_set(obj, A, B)``
  * ``obj.setToolTip(_(A, B))``  -> ``tr_set(obj, A, B, "setToolTip")``
    (а также setPlaceholderText / setWindowTitle / setTitle / setStatusTip)

Сопоставление по сбалансированным скобкам с учётом строковых литералов: если
после ``_( ... )`` идёт что-то кроме закрывающей скобки вызова (например
``+ " " + foo()`` — конкатенация), строка НЕ трогается и правится вручную.

При первом изменении в файл добавляется импорт ``from localization.live import
tr_set`` после строки ``from utils import ... _``.

Запуск (любой python)::

    python scripts/i18n_live_migrate.py src/ui/settings/data_settings.py [...]
    python scripts/i18n_live_migrate.py --dry src/ui/settings/*.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_CTOR_SETTER = {
    "QLabel": "setText",
    "QPushButton": "setText",
    "QCheckBox": "setText",
    "QRadioButton": "setText",
    "QToolButton": "setText",
    "QCommandLinkButton": "setText",
    "QGroupBox": "setTitle",
    "QAction": "setText",
}
# Сеттер-форму (`obj.setX(_())`) конвертируем ТОЛЬКО для заведомо статичных
# подписей. `setText`/`setTitle`/`setWindowTitle` намеренно исключены: они часто
# меняются по состоянию (кнопка «Скачать»/«Скачивание…»), и tr_set накапливал бы
# устаревшие регистрации. Конструкторы (QLabel(_()) и т.п.) безопасны — текст там
# ставится один раз при создании, поэтому для них setText остаётся (в _CTOR_SETTER).
_SETTERS = {"setToolTip", "setPlaceholderText", "setStatusTip"}

# Префиксы: либо `lhs = QWidget(` , либо `obj.setX(` — далее ожидаем `_(`.
_CTOR_PREFIX = re.compile(r'^(?P<indent>\s*)(?P<lhs>[\w\.\[\]"\']+\s*=\s*)(?P<widget>Q[A-Za-z]+)\(\s*')
_SETTER_PREFIX = re.compile(r'^(?P<indent>\s*)(?P<obj>[\w\.\[\]"\']+)\.(?P<setter>set[A-Za-z]+)\(\s*')


def _find_close(s: str, i: int) -> int:
    """Индекс ``)``, закрывающей ``(`` в позиции ``i`` (учёт строк/экранирования)."""
    depth = 0
    quote = None
    esc = False
    while i < len(s):
        c = s[i]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        else:
            if c in "\"'":
                quote = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _convert_line(line: str) -> str | None:
    body = line.rstrip("\n")
    for kind, rx in (("ctor", _CTOR_PREFIX), ("setter", _SETTER_PREFIX)):
        m = rx.match(body)
        if not m:
            continue
        p = m.end()
        if not body.startswith("_(", p):
            continue
        close = _find_close(body, p + 1)  # позиция `(` у `_(`
        if close < 0:
            continue
        rest = body[close + 1:].lstrip()
        # После `_( ... )` должна идти ровно закрывающая скобка вызова и всё.
        if not rest.startswith(")"):
            continue
        if rest[1:].strip() != "":
            continue
        inner = body[p + 2:close].strip()
        if kind == "ctor":
            widget = m.group("widget")
            setter = _CTOR_SETTER.get(widget)
            if setter is None:
                continue
            tail = f', "{setter}"' if setter != "setText" else ""
            return f'{m.group("indent")}{m.group("lhs")}tr_set({widget}(), {inner}{tail})\n'
        else:
            setter = m.group("setter")
            if setter not in _SETTERS:
                continue
            tail = f', "{setter}"' if setter != "setText" else ""
            return f'{m.group("indent")}tr_set({m.group("obj")}, {inner}{tail})\n'
    return None


def _ensure_import(lines: list[str]) -> None:
    if any("from localization.live import" in ln and "tr_set" in ln for ln in lines):
        return
    for i, ln in enumerate(lines):
        if re.match(r'^\s*from utils import .*\b_\b', ln) or ln.strip() == "from utils import _":
            lines.insert(i + 1, "from localization.live import tr_set\n")
            return


def migrate(path: Path, dry: bool) -> int:
    text = path.read_text(encoding="utf-8")
    bom = text.startswith("﻿")
    if bom:
        text = text[1:]
    lines = text.splitlines(keepends=True)
    changed = 0
    out: list[str] = []
    for ln in lines:
        new = _convert_line(ln)
        if new is not None and new != ln:
            changed += 1
            out.append(new)
        else:
            out.append(ln)
    if changed:
        _ensure_import(out)
        if not dry:
            result = ("﻿" if bom else "") + "".join(out)
            path.write_text(result, encoding="utf-8")
    print(f"{'[dry] ' if dry else ''}{path}: {changed} строк")
    return changed


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    if not args:
        print("Укажите файлы для миграции", file=sys.stderr)
        return 1
    total = 0
    for a in args:
        total += migrate(Path(a), dry)
    print(f"Итого изменено строк: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
