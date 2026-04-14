# src/ui/dialogs/context_viewer_dialog.py
"""Диалог просмотра контекста последнего запроса к нейронной сети."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
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
QFrame#HeaderFrame {
    background-color: #232333;
    border-radius: 6px;
    border: 1px solid #3A3A4A;
}
QLabel#HeaderLabel { color: #EAEAEA; font-size: 11px; }
QSplitter::handle { background-color: #3A3A4A; width: 2px; }
"""


class ContextViewerDialog(QDialog):
    """Большой диалог для просмотра контекста запроса к нейросети.

    Принимает dict с полями:
      - messages: list[dict]  (обязательно)
      - model, provider_name, protocol_id, dialect_id, timestamp  (опционально)
      - extra: dict  (параметры генерации)
      - response: str  (если есть — из finetune JSONL)
    """

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._data = data
        self._messages: List[Dict] = data.get("messages") or []

        self.setWindowTitle(_("Просмотр контекста запроса", "Request Context Viewer"))
        self.setMinimumSize(900, 600)
        self.resize(1150, 720)
        self.setModal(True)
        self.setStyleSheet(_DIALOG_STYLE)

        self._items: list[tuple[QTreeWidgetItem, str, Any]] = []
        self._build_ui()
        self._populate_tree()

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

        self._viewer = QTextBrowser()
        self._viewer.setOpenLinks(False)
        splitter.addWidget(self._viewer)

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
        lay.setSpacing(24)

        def kv(label: str, value: str) -> QLabel:
            lbl = QLabel(f"<b style='color:{_MUTED}'>{label}:</b>&nbsp;{value or '—'}")
            lbl.setObjectName("HeaderLabel")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            return lbl

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

    # ─────────────────────────────────── Tree ────────────────────────────────────

    def _populate_tree(self):
        self._tree.clear()
        self._items.clear()

        # Параметры
        params_item = QTreeWidgetItem(self._tree, [_("⚙ Параметры", "⚙ Parameters")])
        params_item.setExpanded(False)
        self._items.append((params_item, "params", self._data.get("extra") or {}))

        # Если есть response (из finetune JSONL)
        if self._data.get("response"):
            resp_item = QTreeWidgetItem(self._tree, [_("💬 Ответ модели", "💬 Model response")])
            self._items.append((resp_item, "response", self._data["response"]))

        # Сообщения
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
        for item, kind, payload in self._items:
            if item is current:
                self._render(kind, payload)
                return

    def _render(self, kind: str, payload: Any):
        if kind == "params":
            d: dict = payload or {}
            if not d:
                html = f"<p style='color:{_MUTED}'><i>{_('Нет параметров', 'No parameters')}</i></p>"
            else:
                rows = "".join(
                    f"<tr><td style='color:{_MUTED};padding-right:16px'><b>{self._esc(k)}</b></td>"
                    f"<td style='color:{_TEXT}'>{self._esc(str(v))}</td></tr>"
                    for k, v in d.items()
                )
                html = f"<table style='border-spacing:4px'>{rows}</table>"
            self._viewer.setHtml(self._wrap(html))

        elif kind == "response":
            text = str(payload or "")
            _asst_color = _ROLE_COLORS["assistant"]
            html = (
                f"<p><b style='color:{_asst_color}'>{_('Ответ модели', 'Model response')}</b></p>"
                f"<pre style='white-space:pre-wrap;color:{_TEXT}'>{self._esc(text)}</pre>"
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
                rendered_content = (
                    f"<pre style='white-space:pre-wrap;color:{_TEXT};"
                    f"font-family:Consolas,monospace'>{self._esc(str(content))}</pre>"
                )

            html = (
                f"<p><b style='color:{color};font-size:13px'>"
                f"{_ROLE_ICONS.get(role, '')} {self._esc(role.upper())}"
                f"</b></p>"
                f"{rendered_content}"
            )

            # Доп. поля (name, tool_call_id и т.п.)
            extras = {k: v for k, v in msg.items() if k not in ("role", "content")}
            if extras:
                html += (
                    f"<hr style='border-color:{_BORDER}'>"
                    f"<p style='color:{_MUTED}'><b>{_('Доп. поля', 'Extra fields')}:</b></p>"
                    f"<pre style='color:{_MUTED}'>{self._esc(json.dumps(extras, ensure_ascii=False, indent=2))}</pre>"
                )
            self._viewer.setHtml(self._wrap(html))

    def _render_content_blocks(self, blocks: list) -> str:
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                parts.append(f"<pre style='color:{_TEXT}'>{self._esc(str(block))}</pre>")
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(
                    f"<pre style='white-space:pre-wrap;color:{_TEXT};"
                    f"font-family:Consolas,monospace'>{self._esc(block.get('text') or '')}</pre>"
                )
            elif btype in ("image_url", "image"):
                parts.append(f"<p style='color:{_MUTED}'><i>[{_('изображение', 'image')}]</i></p>")
            else:
                parts.append(
                    f"<pre style='color:{_MUTED}'>{self._esc(json.dumps(block, ensure_ascii=False))}</pre>"
                )
        return "".join(parts)

    # ─────────────────────────────────── Helpers ─────────────────────────────────

    @staticmethod
    def _wrap(body: str) -> str:
        """Обворачивает HTML в базовый шаблон с цветами приложения."""
        return (
            f"<html><body style='background:{_HTML_BG};color:{_TEXT};"
            f"font-family:\"Segoe UI\",Arial,sans-serif;margin:0;padding:0'>"
            f"{body}</body></html>"
        )

    @staticmethod
    def _esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _get_preview(content: Any, max_len: int) -> str:
        if isinstance(content, list):
            # vision / tool content blocks
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
