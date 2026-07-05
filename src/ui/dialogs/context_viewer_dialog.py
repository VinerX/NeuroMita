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
    QTabWidget,
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

# ── Section markers (тегирование блоков внутри промпта) ───────────────────────
# Категория → (иконка, цвет). Определяется по ключевым словам в имени тега/заголовка.
_SECTION_STYLE = {
    "memory":      ("🧠", "#34D399"),  # <relevant_memories>
    "history":     ("🕰", "#60A5FA"),  # <past_context> / history
    "entity":      ("🕸", "#A78BFA"),  # <entity_knowledge> / graph
    "summary":     ("📜", "#F4D35E"),  # [HISTORY SUMMARY]
    "state":       ("🕐", "#22D3EE"),  # [Current State]
    "behavior":    ("📊", "#F472B6"),  # состояние поведения
    "participant": ("👥", "#FBBF24"),  # участники диалога
    "game":        ("🎮", "#4ADE80"),  # состояние мини-игры
    "default":     ("🏷", "#9CA3AF"),  # прочие теги/заголовки
}
# Заголовок-строка целиком: <tag> / </tag> либо [Header].
_RE_TAG_RAW = re.compile(r"^<(/?)([A-Za-z_][\w]*)>$")
_RE_HDR_RAW = re.compile(r"^\[([A-Za-z][A-Za-z0-9 _/\-]{1,48})\]$")
_RE_TAG_ESC = re.compile(r"^&lt;(/?)([A-Za-z_][\w]*)&gt;$")
_RE_HDR_ESC = re.compile(r"^\[([A-Za-z][A-Za-z0-9 _/\-]{1,48})\]$")


class ContextViewerDialog(QDialog):
    """Большой диалог для просмотра контекста запроса к нейросети.

    Принимает dict с полями:
      - messages: list[dict]  (обязательно)
      - model, provider_name, protocol_id, dialect_id, timestamp  (опционально)
      - character_name  (опционально)
      - extra: dict  (параметры генерации)
      - response: str  (если есть — из finetune JSONL)
    """

    def __init__(self, data: Dict[str, Any], parent=None, initial_tab: str = "request"):
        super().__init__(parent)
        self._data = data
        self._messages: List[Dict] = data.get("messages") or []
        self._initial_tab = str(initial_tab or "request").lower()
        self._highlight_enabled = True

        self.setWindowTitle(_("Просмотр контекста запроса и ответа", "Request / Response Context Viewer"))
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
        self._tabs.setCurrentIndex(1 if self._initial_tab == "response" else 0)

    # ─────────────────────────────────── UI build ────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_request_tab(), _("Запрос", "Request"))
        self._tabs.addTab(self._build_response_tab(), _("Ответ", "Response"))
        root.addWidget(self._tabs, stretch=1)

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

        copy_resp_btn = QPushButton(_("Копировать ответ", "Copy response"))
        copy_resp_btn.setObjectName("SecondaryBtn")
        copy_resp_btn.setToolTip(_("Скопировать ответ модели и usage", "Copy model response and usage"))
        copy_resp_btn.clicked.connect(self._copy_response)
        btn_row.addWidget(copy_resp_btn)

        close_btn = QPushButton(_("Закрыть", "Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _build_request_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(320)
        self._tree.currentItemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._tree)

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
        layout.addWidget(splitter)
        return tab

    def _build_response_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._response_viewer = QTextBrowser()
        self._response_viewer.setOpenLinks(False)
        layout.addWidget(self._response_viewer)
        return tab

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
            label = self._classify_message_label(msg, role, role_counters[role])
            child = QTreeWidgetItem(msgs_item, [label])
            child.setToolTip(0, f"{role} #{role_counters[role]}")
            self._items.append((child, "message", msg))

        self._render_response_tab()

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

        elif kind == "overview":
            lines = [f"<p><b style='color:{_TEXT}'>{_('Всего сообщений', 'Total messages')}:</b> {len(self._messages)}</p><hr style='border-color:{_BORDER}'>"]
            role_counters: Dict[str, int] = {}
            for i, msg in enumerate(self._messages):
                role = msg.get("role") or "?"
                role_counters[role] = role_counters.get(role, 0) + 1
                color = _ROLE_COLORS.get(role, _TEXT)
                content = msg.get("content") or ""
                preview = self._get_preview(content, 160)
                tag = self._classify_message_label(msg, role, role_counters[role])
                lines.append(
                    f"<p><b style='color:{color}'>{i + 1}. {self._esc(tag)}</b>"
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
                rendered_content = self._render_prompt_body(str(content))

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

    def _render_response_tab(self):
        response_text = str(self._data.get("response") or "")
        response_raw = str(self._data.get("response_raw") or "")
        usage = self._data.get("usage") or {}
        finish_reason = str(self._data.get("finish_reason") or "")
        response_model = str(self._data.get("response_model") or self._data.get("model") or "")
        response_provider = str(self._data.get("response_provider_name") or self._data.get("provider_name") or "")
        response_ts = str(self._data.get("response_timestamp") or "")

        sections: list[str] = []
        meta_rows = []
        if response_model:
            meta_rows.append(
                f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{_('Model', 'Model')}</b></td>"
                f"<td style='color:{_TEXT}'>{self._colorize(response_model)}</td></tr>"
            )
        if response_provider:
            meta_rows.append(
                f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{_('Provider', 'Provider')}</b></td>"
                f"<td style='color:{_TEXT}'>{self._colorize(response_provider)}</td></tr>"
            )
        if finish_reason:
            meta_rows.append(
                f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{_('Finish reason', 'Finish reason')}</b></td>"
                f"<td style='color:{_TEXT}'>{self._colorize(finish_reason)}</td></tr>"
            )
        if response_ts:
            meta_rows.append(
                f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{_('Response time', 'Response time')}</b></td>"
                f"<td style='color:{_TEXT}'>{self._colorize(response_ts[:19].replace('T', ' '))}</td></tr>"
            )
        if meta_rows:
            sections.append(f"<table style='border-spacing:4px'>{''.join(meta_rows)}</table>")

        if usage:
            usage_rows = self._build_usage_rows(usage)
            if usage_rows:
                sections.append(
                    f"<hr style='border-color:{_BORDER}'>"
                    f"<p><b style='color:{_MUTED}'>{_('Usage summary', 'Usage summary')}</b></p>"
                    f"<table style='border-spacing:4px'>{''.join(usage_rows)}</table>"
                )
            usage_body = self._colorize(json.dumps(usage, ensure_ascii=False, indent=2))
            sections.append(
                f"<p><b style='color:{_MUTED}'>{_('Raw usage', 'Raw usage')}</b></p>"
                f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{usage_body}</div>"
            )

        if response_text:
            sections.append(
                f"<hr style='border-color:{_BORDER}'>"
                f"<p><b style='color:{_ROLE_COLORS['assistant']}'>{_('Model response', 'Model response')}</b></p>"
                f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{self._colorize(response_text)}</div>"
            )
        else:
            sections.append(
                f"<p style='color:{_MUTED}'><i>{_('No response data saved', 'No response data saved')}</i></p>"
            )

        if response_raw and response_raw != response_text:
            sections.append(
                f"<hr style='border-color:{_BORDER}'>"
                f"<p><b style='color:{_MUTED}'>{_('Raw response', 'Raw response')}</b></p>"
                f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{self._colorize(response_raw)}</div>"
            )

        self._response_viewer.setHtml(self._wrap("".join(sections)))

    def _build_usage_rows(self, usage: dict) -> list[str]:
        def _to_int(key: str) -> int | None:
            try:
                value = usage.get(key)
                if value in (None, ""):
                    return None
                return int(value)
            except Exception:
                return None

        def _to_float(key: str) -> float | None:
            try:
                value = usage.get(key)
                if value in (None, ""):
                    return None
                return float(value)
            except Exception:
                return None

        def _row(label: str, value: str) -> str:
            return (
                f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{label}</b></td>"
                f"<td style='color:{_TEXT}'>{value}</td></tr>"
            )

        rows: list[str] = []

        prompt_tokens = _to_int("prompt_tokens")
        completion_tokens = _to_int("completion_tokens")
        total_tokens = _to_int("total_tokens")
        reasoning_tokens = _to_int("reasoning_tokens")
        cached_prompt_tokens = _to_int("cached_prompt_tokens")
        cache_write_tokens = _to_int("cache_write_tokens")

        if prompt_tokens is not None:
            rows.append(_row(_("Prompt tokens", "Prompt tokens"), self._fmt_int(prompt_tokens)))
        if completion_tokens is not None:
            rows.append(_row(_("Completion tokens", "Completion tokens"), self._fmt_int(completion_tokens)))
        if total_tokens is not None:
            rows.append(_row(_("Total tokens", "Total tokens"), self._fmt_int(total_tokens)))
        if reasoning_tokens:
            rows.append(_row(_("Reasoning tokens", "Reasoning tokens"), self._fmt_int(reasoning_tokens)))
        if cached_prompt_tokens is not None:
            cached_text = self._fmt_int(cached_prompt_tokens)
            if prompt_tokens and prompt_tokens > 0:
                cached_pct = (cached_prompt_tokens / prompt_tokens) * 100.0
                cached_text += f" <span style='color:{_MUTED}'>({cached_pct:.1f}%)</span>"
            rows.append(_row(_("Cached prompt tokens", "Cached prompt tokens"), cached_text))
        if cache_write_tokens is not None:
            rows.append(_row(_("Cache write tokens", "Cache write tokens"), self._fmt_int(cache_write_tokens)))

        cost = _to_float("cost")
        if cost is not None:
            currency = str(usage.get("cost_currency") or "USD")
            cost_text = self._fmt_cost(cost, currency)
            cost_source = str(usage.get("cost_source") or "")
            if cost_source:
                cost_text += f" <span style='color:{_MUTED}'>({self._esc(cost_source)})</span>"
            rows.append(_row(_("Cost", "Cost"), cost_text))

        return rows

    def _render_content_blocks(self, blocks: list) -> str:
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                parts.append(f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{self._colorize(str(block))}</div>")
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(self._render_prompt_body(block.get('text') or ''))
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
    def _fmt_int(value: int) -> str:
        """Token counts: compact to thousands (e.g. 47.3k) once large, exact below."""
        try:
            n = int(value)
        except Exception:
            return str(value)
        if abs(n) >= 10000:
            return f"{n / 1000:.1f}k"
        return f"{n:,}".replace(",", " ")

    @staticmethod
    def _fmt_cost(value: float, currency: str = "USD") -> str:
        try:
            amount = float(value)
        except Exception:
            return str(value)

        if abs(amount) >= 1:
            text = f"{amount:.4f}"
        elif abs(amount) >= 0.01:
            text = f"{amount:.5f}"
        else:
            text = f"{amount:.7f}"
        text = text.rstrip("0").rstrip(".")
        return f"{currency} {text}"

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

    # ── Section markers (тегирование блоков промпта) ──────────────────────────

    @staticmethod
    def _content_plain(content: Any) -> str:
        """Плоский текст с сохранением переносов (для поиска строк-заголовков)."""
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return str(content or "")

    def _marker_meta(self, name: str) -> tuple[str, str, str]:
        """По имени тега/заголовка → (иконка, цвет, человекочитаемый ярлык)."""
        key = name.lower().replace("_", " ")
        if "memor" in key:
            cat = "memory"
        elif "summary" in key:
            cat = "summary"
        elif "entity" in key or "graph" in key or "knowledge" in key:
            cat = "entity"
        elif "behavior" in key or "behaviour" in key:
            cat = "behavior"
        elif "participant" in key:
            cat = "participant"
        elif "game" in key:
            cat = "game"
        elif "state" in key:
            cat = "state"
        elif "past" in key or "context" in key or "history" in key:
            cat = "history"
        else:
            cat = "default"
        icon, color = _SECTION_STYLE[cat]
        label = name.replace("_", " ").strip()
        label = label.title() if label.isupper() else (label[:1].upper() + label[1:])
        return icon, color, label

    def _classify_message_label(self, msg: dict, role: str, ordinal: int) -> str:
        """Ярлык узла дерева: осмысленный для system-сообщений, обычный для остальных."""
        icon = _ROLE_ICONS.get(role, "•")
        if role != "system":
            return f"{icon} {role} #{ordinal}"

        text = self._content_plain(msg.get("content"))
        first = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
        m = _RE_TAG_RAW.match(first) or _RE_HDR_RAW.match(first)
        if m:
            name = m.group(2) if m.re is _RE_TAG_RAW else m.group(1)
            s_icon, _c, s_label = self._marker_meta(name)
            return f"{s_icon} {s_label}"
        # крупный блок без явного заголовка — основной системный промпт
        if len(text) > 400:
            return "📖 " + _("Системный промпт", "System prompt")
        return f"{icon} system #{ordinal}"

    def _banner_html(self, name: str, closing: bool) -> str:
        icon, color, label = self._marker_meta(name)
        if closing:
            return f"<span style='color:#5A5A6A;font-size:10px'>◂ {self._esc(label)}</span>"
        return (
            f"<span style='background:#232333;color:{color};"
            f"border-left:3px solid {color};padding:2px 10px;font-weight:bold'>"
            f"{icon} {self._esc(label)}</span>"
        )

    def _render_prompt_body(self, text: str) -> str:
        """Рендер тела сообщения с подсветкой и «баннерами» секций.

        Строки-заголовки (<tag>, </tag>, [Header]) заменяются на цветные плашки;
        остальной текст проходит обычную подсветку синтаксиса.
        """
        normalized = self._normalize_newlines(text)
        escaped = self._esc(normalized)

        banners: Dict[str, str] = {}
        out_lines: list[str] = []
        for ln in escaped.split("\n"):
            s = ln.strip()
            m = _RE_TAG_ESC.match(s)
            if m:
                meta = (m.group(2), bool(m.group(1)))
            else:
                m = _RE_HDR_ESC.match(s)
                meta = (m.group(1), False) if m else None
            if meta is not None:
                # плейсхолдер из PUA-символов: не трогается подсветкой и inline-конвертером
                token = "" + chr(0xE100 + len(banners)) + ""
                banners[token] = self._banner_html(meta[0], meta[1])
                out_lines.append(token)
            else:
                out_lines.append(ln)

        body = "\n".join(out_lines)
        if self._highlight_enabled:
            body = self._highlight(body)
        body = self._to_inline_html(body)
        for token, html in banners.items():
            body = body.replace(token, html)
        return f"<div style='color:{_TEXT};font-family:Consolas,monospace'>{body}</div>"

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

    def _copy_response(self):
        payload = {
            "response": self._data.get("response"),
            "response_raw": self._data.get("response_raw"),
            "response_model": self._data.get("response_model") or self._data.get("model"),
            "response_provider_name": self._data.get("response_provider_name") or self._data.get("provider_name"),
            "finish_reason": self._data.get("finish_reason"),
            "usage": self._data.get("usage"),
        }
        QApplication.clipboard().setText(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
