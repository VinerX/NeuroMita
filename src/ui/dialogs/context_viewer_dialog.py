# src/ui/dialogs/context_viewer_dialog.py
"""Диалог просмотра контекста последнего запроса к нейронной сети."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils import getTranslationVariant as _

_ROLE_ICONS = {
    "system": "⚙",
    "user": "👤",
    "assistant": "🤖",
    "tool": "🔧",
}
_ROLE_COLORS = {
    "system": "#60A5FA",
    "user": "#F4D35E",
    "assistant": "#A78BFA",
    "tool": "#34D399",
}

_HTML_BG = "#1E1E2E"
_TEXT    = "#EAEAEA"
_MUTED   = "#9CA3AF"
_BORDER  = "#3A3A4A"
_DIALOG_STYLE = """
QDialog { background-color: #1A1A24; color: #EAEAEA; }
QTreeWidget {
    background-color: #1E1E2E;
    color: #EAEAEA;
    border: 1px solid #3A3A4A;
    border-radius: 4px;
    font-size: 12px;
}
QTreeWidget::item { padding: 3px 4px; }
QTreeWidget::item:selected { background-color: #383A59; }
QTreeWidget::branch { background-color: #1E1E2E; }
QTextBrowser {
    background-color: #1E1E2E;
    color: #EAEAEA;
    border: 1px solid #3A3A4A;
    border-radius: 4px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    padding: 6px;
}
QPushButton {
    background-color: #2A2A3A;
    color: #EAEAEA;
    border: 1px solid #3A3A4A;
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}
QPushButton:hover { background-color: #383A59; }
QPushButton#CloseBtn { background-color: #3A2A2A; border-color: #5A3A3A; }
QPushButton#CloseBtn:hover { background-color: #5A3A3A; }
QPushButton#NavBtn {
    min-width: 28px;
    max-width: 28px;
    padding: 4px 6px;
    font-size: 13px;
}
QFrame#HeaderFrame {
    background-color: #232333;
    border-radius: 6px;
    border: 1px solid #3A3A4A;
}
QLabel#HeaderLabel { color: #EAEAEA; font-size: 11px; }
QSplitter::handle { background-color: #3A3A4A; width: 2px; }
QLineEdit#SearchInput {
    background-color: #252535;
    color: #EAEAEA;
    border: 1px solid #3A3A4A;
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 12px;
    min-width: 180px;
}
QLineEdit#SearchInput:focus { border-color: #6366F1; }
QLabel#SearchCounter { color: #9CA3AF; font-size: 11px; min-width: 44px; }
QCheckBox { color: #9CA3AF; font-size: 11px; }
QCheckBox::indicator { width: 14px; height: 14px; }
"""

# ── Syntax highlight colours ──────────────────────────────────────────────────
_SH_BRACKET  = "#F97316"   # { } [ ]
_SH_STRING   = "#86EFAC"   # "quoted"
_SH_NUMBER   = "#93C5FD"   # 42 / 3.14
_SH_COLON    = "#F4D35E"   # :


class ContextViewerDialog(QDialog):
    """Большой диалог для просмотра контекста запроса к нейросети.

    Принимает dict с полями:
      - messages: list[dict]  (обязательно)
      - model, provider_name, protocol_id, dialect_id, timestamp  (опционально)
      - character_name  (опционально)
      - extra: dict  (параметры генерации)
      - response: str  (если есть — из finetune JSONL)
    """

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._data = data
        self._messages: List[Dict] = data.get("messages") or []
        self._highlight_enabled = True

        self.setWindowTitle(_("Просмотр контекста запроса", "Request Context Viewer"))
        self.setMinimumSize(900, 600)
        self.resize(1150, 720)
        self.setModal(True)
        self.setStyleSheet(_DIALOG_STYLE)

        self._items: list[tuple[QTreeWidgetItem, str, Any]] = []
        self._build_ui()
        self._populate_tree()

        # Ctrl+F → фокус на поиск
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)

        # Автовыбор первого узла
        first = self._tree.topLevelItem(0)
        if first:
            self._tree.setCurrentItem(first)

    # ─────────────────────────────────── UI build ────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(320)
        self._tree.currentItemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._tree)

        # Правая панель: поиск + viewer
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        right_layout.addWidget(self._build_search_bar())

        self._viewer = QTextBrowser()
        self._viewer.setOpenLinks(False)
        right_layout.addWidget(self._viewer)

        splitter.addWidget(right_panel)
        splitter.setSizes([230, 900])
        root.addWidget(splitter, stretch=1)

        # Кнопки внизу
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        copy_json_btn = QPushButton(_("Копировать JSON", "Copy JSON"))
        copy_json_btn.setObjectName("SecondaryBtn")
        copy_json_btn.setToolTip(_("Скопировать весь контекст в буфер обмена", "Copy full context to clipboard"))
        copy_json_btn.clicked.connect(self._copy_json)
        btn_row.addWidget(copy_json_btn)

        copy_msgs_btn = QPushButton(_("Копировать сообщения", "Copy messages"))
        copy_msgs_btn.setObjectName("SecondaryBtn")
        copy_msgs_btn.setToolTip(_("Скопировать только список messages", "Copy messages list only"))
        copy_msgs_btn.clicked.connect(self._copy_messages)
        btn_row.addWidget(copy_msgs_btn)

        close_btn = QPushButton(_("Закрыть", "Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("HeaderFrame")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(20)

        def kv(label: str, value: str) -> QLabel:
            lbl = QLabel(f"<b style='color:{_MUTED}'>{label}:</b>&nbsp;{value or '—'}")
            lbl.setObjectName("HeaderLabel")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            return lbl

        char_name = str(self._data.get("character_name") or "")
        if char_name:
            char_lbl = QLabel(f"<span style='color:#A78BFA;font-size:14px;font-weight:bold'>{self._esc(char_name)}</span>")
            char_lbl.setObjectName("HeaderLabel")
            char_lbl.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(char_lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedHeight(18)
            sep.setStyleSheet("background: #3A3A4A; border: none; width: 1px;")
            lay.addWidget(sep)

        lay.addWidget(kv(_("Модель", "Model"), str(self._data.get("model") or "")))
        lay.addWidget(kv(_("Провайдер", "Provider"), str(self._data.get("provider_name") or "")))
        proto = f"{self._data.get('protocol_id') or ''} / {self._data.get('dialect_id') or ''}"
        lay.addWidget(kv(_("Протокол", "Protocol"), proto))
        ts = str(self._data.get("timestamp") or "")
        lay.addWidget(kv(_("Время", "Time"), ts[:19].replace("T", " ") if ts else ""))
        msgs_count = len(self._messages)
        lay.addWidget(kv(_("Сообщений", "Messages"), str(msgs_count)))
        lay.addStretch()
        return frame

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("SearchInput")
        self._search_input.setPlaceholderText(_("Поиск... (Ctrl+F)", "Search... (Ctrl+F)"))
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.returnPressed.connect(self._search_next)
        lay.addWidget(self._search_input)

        self._search_counter = QLabel("")
        self._search_counter.setObjectName("SearchCounter")
        lay.addWidget(self._search_counter)

        prev_btn = QPushButton("▲")
        prev_btn.setObjectName("NavBtn")
        prev_btn.setToolTip(_("Предыдущее совпадение", "Previous match"))
        prev_btn.clicked.connect(self._search_prev)
        lay.addWidget(prev_btn)

        next_btn = QPushButton("▼")
        next_btn.setObjectName("NavBtn")
        next_btn.setToolTip(_("Следующее совпадение", "Next match"))
        next_btn.clicked.connect(self._search_next)
        lay.addWidget(next_btn)

        self._highlight_cb = QCheckBox(_("Подсветка", "Highlight"))
        self._highlight_cb.setChecked(True)
        self._highlight_cb.stateChanged.connect(self._on_highlight_toggled)
        lay.addWidget(self._highlight_cb)

        lay.addStretch()
        return bar

    # ─────────────────────────────────── Search ──────────────────────────────────

    def _focus_search(self):
        self._search_input.setFocus()
        self._search_input.selectAll()

    def _on_search_changed(self, text: str):
        cursor = self._viewer.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self._viewer.setTextCursor(cursor)

        if text:
            total = self._viewer.toPlainText().lower().count(text.lower())
            self._search_counter.setText(f"/{total}" if total else _("нет", "none"))
            self._search_next()
        else:
            self._search_counter.setText("")

    def _search_next(self):
        text = self._search_input.text()
        if not text:
            return
        found = self._viewer.find(text)
        if not found:
            cursor = self._viewer.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self._viewer.setTextCursor(cursor)
            self._viewer.find(text)
        self._update_search_counter(text)

    def _search_prev(self):
        from PyQt6.QtGui import QTextDocument
        text = self._search_input.text()
        if not text:
            return
        found = self._viewer.find(text, QTextDocument.FindFlag.FindBackward)
        if not found:
            cursor = self._viewer.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._viewer.setTextCursor(cursor)
            self._viewer.find(text, QTextDocument.FindFlag.FindBackward)
        self._update_search_counter(text)

    def _update_search_counter(self, text: str):
        total = self._viewer.toPlainText().lower().count(text.lower())
        self._search_counter.setText(f"/{total}" if total else _("нет", "none"))

    def _on_highlight_toggled(self):
        self._highlight_enabled = self._highlight_cb.isChecked()
        # Перерендерить текущий элемент
        current = self._tree.currentItem()
        if current:
            self._on_item_changed(current, None)

    # ─────────────────────────────────── Tree ────────────────────────────────────

    def _populate_tree(self):
        self._tree.clear()
        self._items.clear()

        params_item = QTreeWidgetItem(self._tree, [_("⚙ Параметры", "⚙ Parameters")])
        params_item.setExpanded(False)
        self._items.append((params_item, "params", self._data.get("extra") or {}))

        if self._data.get("response"):
            resp_item = QTreeWidgetItem(self._tree, [_("💬 Ответ модели", "💬 Model response")])
            self._items.append((resp_item, "response", self._data["response"]))

        msgs_item = QTreeWidgetItem(
            self._tree,
            [_("Сообщения", "Messages") + f" ({len(self._messages)})"]
        )
        msgs_item.setExpanded(True)
        self._items.append((msgs_item, "overview", None))

        role_counters: Dict[str, int] = {}
        for msg in self._messages:
            role = msg.get("role") or "unknown"
            role_counters[role] = role_counters.get(role, 0) + 1
            icon = _ROLE_ICONS.get(role, "•")
            label = f"{icon} {role} #{role_counters[role]}"
            child = QTreeWidgetItem(msgs_item, [label])
            self._items.append((child, "message", msg))

    # ─────────────────────────────────── Rendering ───────────────────────────────

    def _on_item_changed(self, current: QTreeWidgetItem, _prev):
        if current is None:
            return
        self._search_counter.setText("")
        for item, kind, payload in self._items:
            if item is current:
                self._render(kind, payload)
                search_text = self._search_input.text()
                if search_text:
                    QTimer.singleShot(50, lambda: self._on_search_changed(search_text))
                return

    def _render(self, kind: str, payload: Any):
        if kind == "params":
            d: dict = payload or {}
            if not d:
                html = f"<p style='color:{_MUTED}'><i>{_('Нет параметров', 'No parameters')}</i></p>"
            else:
                rows = "".join(
                    f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{self._esc(k)}</b></td>"
                    f"<td style='color:{_TEXT}'>{self._colorize(str(v))}</td></tr>"
                    for k, v in d.items()
                )
                html = f"<table style='border-spacing:4px'>{rows}</table>"
            self._viewer.setHtml(self._wrap(html))

        elif kind == "response":
            text = str(payload or "")
            _asst_color = _ROLE_COLORS["assistant"]
            html = (
                f"<p><b style='color:{_asst_color}'>{_('Ответ модели', 'Model response')}</b></p>"
                f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{self._colorize(text)}</div>"
            )
            self._viewer.setHtml(self._wrap(html))

        elif kind == "overview":
            lines = [f"<p><b style='color:{_TEXT}'>{_('Всего сообщений', 'Total messages')}:</b> {len(self._messages)}</p><hr style='border-color:{_BORDER}'>"]
            for i, msg in enumerate(self._messages):
                role = msg.get("role") or "?"
                color = _ROLE_COLORS.get(role, _TEXT)
                content = msg.get("content") or ""
                preview = self._get_preview(content, 160)
                lines.append(
                    f"<p><b style='color:{color}'>{i + 1}. {self._esc(role)}</b>"
                    f"&nbsp;<span style='color:{_MUTED}'>{self._esc(preview)}</span></p>"
                )
            self._viewer.setHtml(self._wrap("".join(lines)))

        elif kind == "message":
            msg: dict = payload or {}
            role = msg.get("role") or "unknown"
            color = _ROLE_COLORS.get(role, _TEXT)
            content = msg.get("content") or ""

            if isinstance(content, list):
                rendered_content = self._render_content_blocks(content)
            else:
                body = self._colorize(str(content))
                rendered_content = (
                    f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{body}</div>"
                )

            html = (
                f"<p><b style='color:{color};font-size:13px'>"
                f"{_ROLE_ICONS.get(role, '')} {self._esc(role.upper())}"
                f"</b></p>"
                f"{rendered_content}"
            )

            extras = {k: v for k, v in msg.items() if k not in ("role", "content")}
            if extras:
                extras_body = self._colorize(json.dumps(extras, ensure_ascii=False, indent=2))
                html += (
                    f"<hr style='border-color:{_BORDER}'>"
                    f"<p style='color:{_MUTED}'><b>{_('Доп. поля', 'Extra fields')}:</b></p>"
                    f"<div style='color:{_MUTED};font-family:Consolas,monospace'>{extras_body}</div>"
                )
            self._viewer.setHtml(self._wrap(html))

    def _render_content_blocks(self, blocks: list) -> str:
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                parts.append(f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{self._colorize(str(block))}</div>")
                continue
            btype = block.get("type", "")
            if btype == "text":
                body = self._colorize(block.get('text') or '')
                parts.append(
                    f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{body}</div>"
                )
            elif btype in ("image_url", "image"):
                parts.append(f"<p style='color:{_MUTED}'><i>[{_('изображение', 'image')}]</i></p>")
            else:
                body = self._colorize(json.dumps(block, ensure_ascii=False))
                parts.append(f"<div style='color:{_MUTED};font-family:Consolas,monospace'>{body}</div>")
        return "".join(parts)

    # ─────────────────────────────────── Helpers ─────────────────────────────────

    def _colorize(self, text: str) -> str:
        """Экранирует HTML, нормализует пробелы для inline-рендера и применяет подсветку."""
        normalized = self._normalize_newlines(text)
        if not self._highlight_enabled:
            # Без подсветки: просто esc + замена пробелов/переносов
            return self._to_inline_html(self._esc(normalized))
        return self._to_inline_html(self._highlight(self._esc(normalized)))

    @staticmethod
    def _to_inline_html(escaped: str) -> str:
        """Конвертирует plain-текст (уже escaped) в inline-HTML для <div>.
        Заменяет \n → <br> и пробелы → &nbsp; чтобы Qt не схлопывал пробелы."""
        # Сначала пробелы (не трогая уже добавленные теги)
        # Заменяем каждый пробел на &nbsp; только в текстовых «кусках» между тегами
        result = []
        # Разбиваем по тегам, чтобы не трогать атрибуты span
        tag_re = re.compile(r'(<[^>]+>)')
        for part in tag_re.split(escaped):
            if part.startswith('<'):
                result.append(part)
            else:
                result.append(part.replace(' ', '&nbsp;').replace('\n', '<br>'))
        return ''.join(result)

    @staticmethod
    def _normalize_newlines(text: str) -> str:
        """Убирает тройные+ переносы строк (оставляет макс. два подряд)."""
        return re.sub(r'\n{3,}', '\n\n', text)

    @staticmethod
    def _wrap(body: str) -> str:
        return (
            f"<html><body style='background:{_HTML_BG};color:{_TEXT};"
            f"font-family:\"Segoe UI\",Arial,sans-serif;margin:0;padding:0'>"
            f"{body}</body></html>"
        )

    @staticmethod
    def _esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _highlight(escaped: str) -> str:
        """Подсветка синтаксиса — один проход, паттерны не пересекаются."""
        _combined = re.compile(
            r'("(?:[^"\\]|\\.)*")'   # group 1 — строка в кавычках
            r'|([{}\[\],])'           # group 2 — скобка / запятая
            r'|(:)(?=[ \t])'          # group 3 — двоеточие перед пробелом
            r'|(?<![a-zA-Z#;&])(\b\d+\.?\d*\b)'  # group 4 — число
        )

        def _replace(m: re.Match) -> str:
            if m.group(1):
                return f'<span style="color:{_SH_STRING}">{m.group(1)}</span>'
            if m.group(2):
                return f'<span style="color:{_SH_BRACKET}">{m.group(2)}</span>'
            if m.group(3):
                return f'<span style="color:{_SH_COLON}">:</span>'
            if m.group(4):
                return f'<span style="color:{_SH_NUMBER}">{m.group(4)}</span>'
            return m.group(0)

        return _combined.sub(_replace, escaped)

    @staticmethod
    def _get_preview(content: Any, max_len: int) -> str:
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            text = " ".join(texts)
        else:
            text = str(content or "")
        text = text.replace("\n", " ")
        return (text[:max_len] + "…") if len(text) > max_len else text

    def _copy_json(self):
        QApplication.clipboard().setText(
            json.dumps(self._data, ensure_ascii=False, indent=2)
        )

    def _copy_messages(self):
        QApplication.clipboard().setText(
            json.dumps(self._messages, ensure_ascii=False, indent=2)
        )
