from __future__ import annotations

from dataclasses import dataclass
import html
import os
from pathlib import Path
import re

import qtawesome as qta
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.launcher_shell_theme import apply_launcher_shell_theme
from ui.settings.settings_access import get_setting
from utils import _
from localization.live import register_if_tr

_DEFAULT_DOC_LANGUAGE = "en"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HTML_HEADING_RE = re.compile(r"<h([1-6])([^>]*)>", re.IGNORECASE)

_WIKI_LINK_COLOR = "#cf7bd6"
_APP_LINK_COLOR = "#e0a85a"

_WIKI_DOC_CSS = """
    body { color: #e8e2f2; font-family: "Segoe UI", "Arial", sans-serif; }
    h1, h2, h3, h4, h5, h6 { color: #f3eef8; font-weight: 700; }
    h1 { font-size: 23px; margin-top: 4px; margin-bottom: 12px; }
    h2 { font-size: 19px; margin-top: 22px; margin-bottom: 8px; color: #e9c7da; }
    h3 { font-size: 16px; margin-top: 18px; margin-bottom: 6px; }
    h4, h5, h6 { font-size: 14px; margin-top: 14px; margin-bottom: 4px; color: #cbb9c8; }
    p { margin-top: 6px; margin-bottom: 10px; }
    a { color: #cf7bd6; text-decoration: underline; }
    ul, ol { margin-top: 4px; margin-bottom: 10px; }
    li { margin-top: 3px; margin-bottom: 3px; }
    code { font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
           background-color: rgba(255, 255, 255, 0.06); color: #f0d9e6; }
    pre { background-color: rgba(8, 8, 18, 0.85); color: #e6e0f0;
          font-family: "Consolas", "Cascadia Mono", "Courier New", monospace;
          padding: 10px; border-left: 2px solid rgba(183, 75, 125, 0.55); }
    blockquote { color: #bca9bb; border-left: 3px solid rgba(120, 116, 140, 0.55);
                 margin-left: 4px; padding-left: 12px; }
    table { border-color: rgba(60, 58, 78, 0.9); }
    th { background-color: rgba(255, 255, 255, 0.05); color: #f3eef8; padding: 4px 8px; }
    td { padding: 4px 8px; }
    hr { color: rgba(60, 58, 78, 0.9); }
"""

_SIDEBAR_CATEGORIES = [
    ("getting-started",   _("Быстрый старт", "Getting Started"),   "fa6s.rocket",      "getting-started.md"),
    ("home-launch",       _("Главная и запуск", "Home & Launch"),  "fa6s.house",        "home-news-updates-and-launch.md"),
    ("chat-characters",   _("Чат и персонажи", "Chat & Characters"), "fa6s.comment",     "chat-and-characters.md"),
    ("voice-mic",         _("Голос и микрофон", "Voice & Mic"),    "fa6s.microphone",   "voice-microphone-camera-and-screen.md"),
    ("memory-data",       _("Память и данные", "Memory & Data"),   "fa6s.database",     "memory-data-ai-hub-and-debugging.md"),
]

_HOME_CARDS_DATA = [
    {
        "icon": "fa6s.rocket",
        "title": _("Первый запуск", "First setup"),
        "body": _(
            "Установите NeuroMita и пройдите настройку приложения шаг за шагом.",
            "Install NeuroMita and complete the app setup step by step.",
        ),
        "link": "getting-started.md",
    },
    {
        "icon": "fa6s.bolt",
        "title": _("AI-провайдер", "AI provider"),
        "body": _(
            "Подключите Gemini, OpenRouter или локальную модель для генерации ответов.",
            "Connect Gemini, OpenRouter or a local model for response generation.",
        ),
        "app": "settings/api",
    },
    {
        "icon": "fa6s.users",
        "title": _("Персонажи", "Characters"),
        "body": _(
            "Выберите Миту, настройте её характер и промпты для диалога.",
            "Pick a Mita, configure her personality and dialogue prompts.",
        ),
        "app": "settings/characters",
    },
    {
        "icon": "fa6s.microphone",
        "title": _("Голос и микрофон", "Voice & Microphone"),
        "body": _(
            "Включите озвучку и настройте распознавание речи для живого разговора.",
            "Enable voice output and set up speech recognition for live conversation.",
        ),
        "app": "settings/voice",
    },
    {
        "icon": "fa6s.brain",
        "title": _("Память и RAG", "Memory & RAG"),
        "body": _(
            "Управляйте памятью персонажа, эмбеддингами и графом знаний.",
            "Manage character memory, embeddings and the knowledge graph.",
        ),
        "app": "settings/models?section=RAG",
    },
    {
        "icon": "fa6s.wrench",
        "title": _("Диагностика", "Troubleshooting"),
        "body": _(
            "Откройте логи, проверьте статус компонентов и найдите решение проблем.",
            "Open logs, check component status and find solutions to issues.",
        ),
        "app": "logs",
    },
]


@dataclass(slots=True)
class _WikiLocation:
    path: Path
    anchor: str = ""


def _runtime_base_dir() -> Path:
    base_dir = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    if base_dir:
        return Path(base_dir)
    return Path(__file__).resolve().parents[3]


_WIKI_ROOT = _runtime_base_dir() / "docs" / "wiki"


def _is_within(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _strip_heading_markup(text: str) -> str:
    cleaned = re.sub(r"`([^`]*)`", r"\1", text)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_~#]", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return " ".join(cleaned.split())


def _slugify_heading(text: str) -> str:
    lowered = _strip_heading_markup(text).strip().lower()
    lowered = re.sub(r"[^a-z0-9\s-]", "", lowered)
    lowered = re.sub(r"[\s_-]+", "-", lowered).strip("-")
    return lowered


def _collect_heading_ids(markdown_text: str) -> list[str]:
    ids: list[str] = []
    seen: dict[str, int] = {}
    in_fence = False

    for raw_line in markdown_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        match = _HEADING_RE.match(raw_line)
        if not match:
            continue

        base = _slugify_heading(match.group(2))
        if not base:
            continue

        count = seen.get(base, 0) + 1
        seen[base] = count
        ids.append(base if count == 1 else f"{base}-{count}")

    return ids


def _markdown_to_html(markdown_text: str) -> str:
    document = QTextDocument()
    document.setMarkdown(markdown_text)
    rendered_html = document.toHtml()

    heading_ids = iter(_collect_heading_ids(markdown_text))

    def _inject_anchor(match: re.Match[str]) -> str:
        try:
            anchor = next(heading_ids)
        except StopIteration:
            return match.group(0)
        level = match.group(1)
        attrs = match.group(2)
        safe_anchor = html.escape(anchor, quote=True)
        return f'<a name="{safe_anchor}"></a><h{level}{attrs}>'

    return _HTML_HEADING_RE.sub(_inject_anchor, rendered_html)


class WikiPage(QWidget):
    def __init__(self, parent, page_actions, settings):
        super().__init__(parent)
        self._page_actions = page_actions
        self._settings = settings
        self.setObjectName("WikiPage")

        self._history: list[_WikiLocation] = []
        self._history_index = -1
        self._current_location: _WikiLocation | None = None
        self._requested_language = self._get_requested_language()
        self._content_language = _DEFAULT_DOC_LANGUAGE
        self._sidebar_buttons: dict[str, QPushButton] = {}
        self._active_sidebar_id: str | None = None

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._build_ui()
        self.open_target("index.md", push_history=True)

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("LauncherShellRoot")
        apply_launcher_shell_theme(root)

        backdrop = QFrame(root)
        backdrop.setObjectName("LauncherShellBackdrop")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(backdrop)

        backdrop_layout = QVBoxLayout(backdrop)
        backdrop_layout.setContentsMargins(14, 12, 14, 12)
        backdrop_layout.setSpacing(0)

        backdrop_layout.addWidget(self._build_toolbar())

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 6, 0, 0)
        content_row.setSpacing(0)

        content_row.addWidget(self._build_sidebar(), 0)

        scroll = QScrollArea()
        scroll.setObjectName("LauncherShellScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("LauncherShellPage")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 0, 14, 14)
        content_layout.setSpacing(14)

        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._build_home_cards())
        self._content_stack.addWidget(self._build_article_card())
        self._content_stack.setCurrentIndex(0)
        content_layout.addWidget(self._content_stack, 1)

        scroll.setWidget(content)
        content_row.addWidget(scroll, 1)

        backdrop_layout.addLayout(content_row, 1)
        self._root_layout.addWidget(root)

    def _build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("LauncherShellSectionCard")

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(qta.icon("fa6s.book-open", color="#cf7bd6").pixmap(20, 20))
        layout.addWidget(icon_label)

        brand = QLabel(_("Wiki", "Wiki"))
        brand.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(brand)

        layout.addSpacing(8)

        self._home_button = self._create_toolbar_button(_("Главная", "Home"), self.open_home)
        self._back_button = self._create_toolbar_button("←", self.go_back)
        self._forward_button = self._create_toolbar_button("→", self.go_forward)
        self._refresh_button = self._create_toolbar_button("⟳", self.reload_current)

        layout.addWidget(self._home_button)
        layout.addWidget(self._back_button)
        layout.addWidget(self._forward_button)
        layout.addWidget(self._refresh_button)

        layout.addStretch(1)

        self._toolbar_title = QLabel("")
        self._toolbar_title.setObjectName("LauncherShellMeta")
        layout.addWidget(self._toolbar_title)

        return toolbar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("LauncherShellSidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(2)

        for cat_id, label, icon_name, _file in _SIDEBAR_CATEGORIES:
            btn = QPushButton()
            btn.setObjectName("LauncherShellNavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", False)
            btn.setIcon(qta.icon(icon_name, color="#cf7bd6"))
            btn.setText(str(label))
            register_if_tr(btn, str(label))

            btn.clicked.connect(lambda _checked=False, f=_file: self._on_sidebar_clicked(f))
            self._sidebar_buttons[cat_id] = btn
            layout.addWidget(btn)

        layout.addStretch(1)
        return sidebar

    def _build_home_cards(self) -> QWidget:
        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(16)

        header = QLabel(_(
            "Что вы хотите настроить?",
            "What would you like to configure?",
        ))
        header.setObjectName("LauncherShellSectionTitle")
        home_layout.addWidget(header)

        grid = QHBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        for index, card_data in enumerate(_HOME_CARDS_DATA):
            card = self._build_home_card(card_data)
            if index % 2 == 0:
                left_col.addWidget(card, 1)
            else:
                right_col.addWidget(card, 1)

        grid.addLayout(left_col, 1)
        grid.addLayout(right_col, 1)
        home_layout.addLayout(grid, 1)
        home_layout.addStretch(1)
        return home

    def _build_home_card(self, data) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(qta.icon(data["icon"], color="#cf7bd6").pixmap(22, 22))
        top.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        title = QLabel(str(data["title"]))
        title.setObjectName("LauncherShellSectionTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        layout.addLayout(top)

        body = QLabel(str(data["body"]))
        body.setObjectName("LauncherShellBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addStretch(1)

        card.mousePressEvent = lambda e, d=data: self._on_home_card_clicked(d)
        return card

    def _build_article_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(0)

        self._viewer = QTextBrowser()
        self._viewer.setOpenLinks(False)
        self._viewer.setOpenExternalLinks(False)
        self._viewer.setReadOnly(True)
        self._viewer.setMinimumHeight(400)
        self._viewer.anchorClicked.connect(self._on_anchor_clicked)
        self._viewer.document().setDefaultStyleSheet(_WIKI_DOC_CSS)
        self._viewer.setStyleSheet(
            """
            QTextBrowser {
                background: transparent;
                border: none;
                color: #e8e2f2;
                font-family: "Segoe UI", "Arial", sans-serif;
                font-size: 14px;
                padding: 4px 10px;
                selection-background-color: rgba(183, 75, 125, 0.32);
            }
            QScrollBar:vertical {
                width: 10px;
                background: transparent;
                margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(120, 116, 140, 0.30);
                border-radius: 5px;
                min-height: 28px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(150, 146, 170, 0.42);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
            }
            """
        )
        layout.addWidget(self._viewer, 1)
        return card

    def _create_toolbar_button(self, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        register_if_tr(button, label)
        button.setObjectName("LauncherShellGhostButton")
        button.clicked.connect(callback)
        return button

    # ── Link styling ─────────────────────────────────────────────────

    def _apply_link_styles(self) -> None:
        document = self._viewer.document()
        if document is None:
            return

        block = document.begin()
        while block.isValid():
            iterator = block.begin()

            while not iterator.atEnd():
                fragment = iterator.fragment()

                if fragment.isValid():
                    char_format = fragment.charFormat()
                    href = char_format.anchorHref()

                    if char_format.isAnchor() and href:
                        is_app_link = href.lower().startswith("app:")
                        color = _APP_LINK_COLOR if is_app_link else _WIKI_LINK_COLOR

                        modifier = QTextCharFormat()
                        modifier.setForeground(QBrush(QColor(color)))

                        if is_app_link:
                            modifier.setFontUnderline(False)
                            modifier.setFontWeight(QFont.Weight.DemiBold)
                        else:
                            modifier.setFontUnderline(True)
                            modifier.setFontWeight(QFont.Weight.Normal)

                        cursor = QTextCursor(document)
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(),
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        cursor.mergeCharFormat(modifier)

                iterator += 1

            block = block.next()

    # ── Content loading ──────────────────────────────────────────────

    def _set_browser_content(self, markdown_text: str, base_path: Path) -> None:
        html_text = _markdown_to_html(markdown_text)
        self._viewer.setHtml(html_text)
        self._viewer.document().setBaseUrl(QUrl.fromLocalFile(str(base_path)))
        QTimer.singleShot(0, self._apply_link_styles)

    def _extract_title(self, markdown_text: str, path: Path) -> str:
        for line in markdown_text.splitlines():
            match = _HEADING_RE.match(line)
            if match:
                return _strip_heading_markup(match.group(2))
        return path.stem.replace("-", " ").title()

    # ── Navigation ───────────────────────────────────────────────────

    def _push_history(self, location: _WikiLocation) -> None:
        if self._history_index >= 0 and self._history[self._history_index] == location:
            return
        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        self._history.append(location)
        self._history_index = len(self._history) - 1

    def _update_nav_buttons(self) -> None:
        self._back_button.setEnabled(self._history_index > 0)
        self._forward_button.setEnabled(self._history_index < len(self._history) - 1)
        self._home_button.setEnabled(
            self._current_location is None
            or self._relative_doc_path(self._current_location.path) != "index.md"
        )

    def _show_article(self) -> None:
        self._content_stack.setCurrentIndex(1)

    def _show_home(self) -> None:
        self._content_stack.setCurrentIndex(0)

    def _update_sidebar_active(self, doc_path: str | None) -> None:
        active_id: str | None = None
        if doc_path:
            for cat_id, _label, _icon, file_name in _SIDEBAR_CATEGORIES:
                if doc_path == file_name:
                    active_id = cat_id
                    break

        if self._active_sidebar_id == active_id:
            return

        self._active_sidebar_id = active_id

        for key, btn in self._sidebar_buttons.items():
            is_active = key == active_id
            btn.blockSignals(True)
            btn.setChecked(is_active)
            btn.setProperty("active", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.blockSignals(False)

    def _update_toolbar_title(self, title: str) -> None:
        self._toolbar_title.setText(title)

    # ── Page actions ─────────────────────────────────────────────────

    def _show_error(self, message: str) -> None:
        self._show_article()
        self._update_toolbar_title(_("Статья не найдена", "Article not found"))
        self._viewer.setHtml(f"<p>{html.escape(message)}</p>")
        self._current_location = None
        self._update_nav_buttons()
        self._update_sidebar_active(None)

    def _open_location(self, location: _WikiLocation, *, push_history: bool) -> None:
        try:
            markdown_text = location.path.read_text(encoding="utf-8")
        except Exception as exc:
            self._show_error(
                _(
                    "Не удалось открыть wiki-страницу: {err}",
                    "Failed to open the wiki page: {err}",
                ).format(err=exc)
            )
            return

        self._current_location = location
        doc_path = self._relative_doc_path(location.path)
        is_index = (doc_path == "index.md")

        if is_index:
            self._show_home()
            self._update_toolbar_title(_("Wiki", "Wiki"))
            self._update_sidebar_active(None)
        else:
            self._show_article()
            title = self._extract_title(markdown_text, location.path)
            self._update_toolbar_title(title)
            self._set_browser_content(markdown_text, location.path)
            self._update_sidebar_active(doc_path)

        if push_history:
            self._push_history(location)
        self._update_nav_buttons()

        if location.anchor and not is_index:
            QTimer.singleShot(50, lambda anchor=location.anchor: self._viewer.scrollToAnchor(anchor))
        elif not is_index:
            self._viewer.verticalScrollBar().setValue(0)

    def open_target(self, target: str = "index.md", *, anchor: str = "", push_history: bool = True) -> None:
        path = self._resolve_start_path(target)
        if path is None:
            self._show_error(
                _(
                    "Wiki-страница не найдена: {target}",
                    "Wiki page not found: {target}",
                ).format(target=target)
            )
            return
        self._open_location(_WikiLocation(path=path, anchor=anchor), push_history=push_history)

    def open_home(self) -> None:
        self.open_target("index.md", push_history=True)

    def reload_current(self) -> None:
        if self._current_location is None:
            self.open_home()
            return
        current_relative = self._relative_doc_path(self._current_location.path)
        self.open_target(current_relative, anchor=self._current_location.anchor, push_history=False)

    def go_back(self) -> None:
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._open_location(self._history[self._history_index], push_history=False)

    def go_forward(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._open_location(self._history[self._history_index], push_history=False)

    def _on_sidebar_clicked(self, file_name: str) -> None:
        self.open_target(file_name, push_history=True)

    def _on_home_card_clicked(self, data) -> None:
        if "link" in data:
            self.open_target(data["link"], push_history=True)
        elif "app" in data:
            app_link = data["app"]
            if "?" in app_link:
                body, query = app_link.split("?", 1)
                from urllib.parse import unquote
                section = None
                for kv in query.split("&"):
                    if kv.lower().startswith("section="):
                        section = unquote(kv.split("=", 1)[1]).strip() or None
                parts = body.split("/")
                category = parts[1] if len(parts) > 1 else None
                if category:
                    self._page_actions.show_settings_category(category, force=True, subsection=section)
                else:
                    self._page_actions.switch_page(body)
            elif "/" in app_link:
                parts = app_link.split("/", 1)
                page = parts[0]
                category = parts[1] if len(parts) > 1 else None
                if page == "settings" and category:
                    self._page_actions.show_settings_category(category, force=True)
                else:
                    self._page_actions.switch_page(page)
            else:
                self._page_actions.switch_page(app_link)

    def _handle_app_link(self, url: QUrl) -> bool:
        text = url.toString()
        if not text.lower().startswith("app:"):
            return False

        body = text[4:].lstrip("/")
        query = ""
        if "?" in body:
            body, query = body.split("?", 1)
        if "#" in body:
            body = body.split("#", 1)[0]

        parts = [p for p in body.split("/") if p]
        if not parts:
            return True

        section = None
        if query:
            from urllib.parse import unquote
            for kv in query.split("&"):
                if kv.lower().startswith("section="):
                    section = unquote(kv.split("=", 1)[1]).strip() or None

        page_key = parts[0].lower()
        if page_key == "settings":
            category = parts[1].lower() if len(parts) > 1 else None
            if category:
                self._page_actions.show_settings_category(category, force=True, subsection=section)
            else:
                self._page_actions.switch_page("settings")
            return True

        self._page_actions.switch_page(page_key)
        return True

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if self._handle_app_link(url):
            return

        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return

        if not url.path() and url.fragment():
            if self._current_location is not None:
                self._current_location = _WikiLocation(self._current_location.path, url.fragment())
            self._viewer.scrollToAnchor(url.fragment())
            return

        target_path = self._resolve_clicked_path(url)
        if target_path is None:
            return

        try:
            content_root = self._locale_root(self._content_language).resolve()
            relative_target = target_path.resolve().relative_to(content_root).as_posix()
        except ValueError:
            relative_target = target_path.name
        self.open_target(relative_target, anchor=url.fragment(), push_history=True)

    # ── Path / locale helpers ────────────────────────────────────────

    def _get_requested_language(self) -> str:
        try:
            return str(
                get_setting(self._settings, "LANGUAGE", _DEFAULT_DOC_LANGUAGE)
                or _DEFAULT_DOC_LANGUAGE
            ).strip().lower()
        except Exception:
            return _DEFAULT_DOC_LANGUAGE

    def _locale_root(self, code: str) -> Path:
        return _WIKI_ROOT / code

    def _resolve_start_path(self, target: str) -> Path | None:
        normalized = str(target or "index.md").replace("\\", "/").lstrip("/")
        relative_path = Path(normalized)
        if not relative_path.suffix:
            relative_path = relative_path.with_suffix(".md")

        requested_root = self._locale_root(self._requested_language)
        fallback_root = self._locale_root(_DEFAULT_DOC_LANGUAGE)

        requested_path = (requested_root / relative_path).resolve()
        if requested_root.exists() and requested_path.exists() and _is_within(_WIKI_ROOT, requested_path):
            self._content_language = self._requested_language
            return requested_path

        fallback_path = (fallback_root / relative_path).resolve()
        if fallback_path.exists() and _is_within(_WIKI_ROOT, fallback_path):
            self._content_language = _DEFAULT_DOC_LANGUAGE
            return fallback_path

        return None

    def _relative_doc_path(self, path: Path) -> str:
        try:
            content_root = self._locale_root(self._content_language).resolve()
            return path.resolve().relative_to(content_root).as_posix()
        except ValueError:
            return path.name

    def _resolve_clicked_path(self, url: QUrl) -> Path | None:
        if url.isRelative() and self._current_location is not None:
            candidate = (self._current_location.path.parent / url.path()).resolve()
        elif url.isLocalFile():
            candidate = Path(url.toLocalFile()).resolve()
        else:
            candidate = Path(url.path()).resolve()

        if candidate.suffix.lower() != ".md":
            return None
        if not candidate.exists() or not _is_within(_WIKI_ROOT, candidate):
            return None
        return candidate

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_activated(self) -> None:
        requested_language = self._get_requested_language()
        if requested_language == self._requested_language:
            return

        self._requested_language = requested_language
        if self._current_location is None:
            self.open_home()
            return

        self.open_target(
            self._relative_doc_path(self._current_location.path),
            anchor=self._current_location.anchor,
            push_history=False,
        )

    def on_deactivated(self) -> None:
        pass


def build_wiki_page(parent, page_actions, settings) -> QWidget:
    return WikiPage(parent, page_actions, settings)
