from __future__ import annotations

from dataclasses import dataclass
import html
import os
from pathlib import Path
import re
import sys

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QTextDocument
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ui.widgets.launcher_dashboard_helpers import create_shell_page_container
from ui.widgets.launcher_dashboard_helpers import _create_hero_card
from ui.settings.settings_access import get_setting
from utils import _
from localization.live import register_if_tr

_DEFAULT_DOC_LANGUAGE = "en"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HTML_HEADING_RE = re.compile(r"<h([1-6])([^>]*)>", re.IGNORECASE)
# Ссылки на интерфейс приложения (схема app:) красим отдельным цветом и
# помечаем стрелкой ↗ — чтобы новичок видел: это не текстовая статья, а
# кнопка, открывающая нужный экран/настройку прямо в приложении.
_APP_LINK_RE = re.compile(r'(<a\b[^>]*\bhref="app:[^"]*"[^>]*)>', re.IGNORECASE)
_APP_LINK_STYLE = "color: #e0a85a; text-decoration: none; font-weight: 600;"


def _style_app_links(html_text: str) -> str:
    def _inject(match: re.Match[str]) -> str:
        head = match.group(1)
        if "style=" in head.lower():
            return f"{head}>"
        return f'{head} style="{_APP_LINK_STYLE}">'

    return _APP_LINK_RE.sub(_inject, html_text)

# Документ-стиль для QTextBrowser (QTextDocument поддерживает подмножество CSS2.1).
# Тёплый акцент только на заголовках и ссылках; тело — спокойный светло-серый,
# код и цитаты — в нейтральной гамме эталона, без розовых обводок.
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

    rendered_html = _HTML_HEADING_RE.sub(_inject_anchor, rendered_html)
    return _style_app_links(rendered_html)


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

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._build_ui()
        self.open_target("index.md", push_history=True)

    def _build_ui(self) -> None:
        root, content_layout = create_shell_page_container()
        root.setParent(self)

        content_layout.addWidget(self._build_hero())
        content_layout.addWidget(self._build_viewer_card(), 1)

        self._root_layout.addWidget(root)

    def _build_hero(self) -> QFrame:
        hero = _create_hero_card(
            "WIKI",
            _("База знаний NeuroMita", "NeuroMita knowledge base"),
            _(
                "Полная пользовательская документация внутри приложения. Быстрый старт остаётся коротким onboarding, а здесь живёт полная справка.",
                "Full user-facing documentation inside the app. Quick Start stays a short onboarding flow, while this page is the durable reference.",
            ),
            actions=[],
        )

        layout = hero.layout()
        if layout is not None:
            actions_row = QHBoxLayout()
            actions_row.setContentsMargins(0, 0, 0, 0)
            actions_row.setSpacing(10)

            self._home_button = self._create_toolbar_button(_("Главная статья", "Home article"), self.open_home)
            self._back_button = self._create_toolbar_button(_("Назад", "Back"), self.go_back, accent=False)
            self._forward_button = self._create_toolbar_button(_("Вперёд", "Forward"), self.go_forward, accent=False)
            self._refresh_button = self._create_toolbar_button(_("Обновить", "Refresh"), self.reload_current, accent=False)

            actions_row.addWidget(self._home_button)
            actions_row.addWidget(self._back_button)
            actions_row.addWidget(self._forward_button)
            actions_row.addWidget(self._refresh_button)
            actions_row.addStretch(1)
            layout.addLayout(actions_row)

        return hero

    def _build_viewer_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        self._doc_title = QLabel("")
        self._doc_title.setObjectName("LauncherShellSectionTitle")
        self._doc_title.setWordWrap(True)
        top_row.addWidget(self._doc_title, 1)

        self._doc_language = QLabel("")
        self._doc_language.setObjectName("LauncherShellMeta")
        top_row.addWidget(self._doc_language, 0)
        layout.addLayout(top_row)

        self._doc_path = QLabel("")
        self._doc_path.setObjectName("LauncherShellMeta")
        self._doc_path.setWordWrap(True)
        layout.addWidget(self._doc_path)

        self._viewer = QTextBrowser()
        self._viewer.setOpenLinks(False)
        self._viewer.setOpenExternalLinks(False)
        self._viewer.setReadOnly(True)
        self._viewer.setMinimumHeight(560)
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

    def _create_toolbar_button(self, label: str, callback, *, accent: bool = True) -> QPushButton:
        button = QPushButton(label)
        register_if_tr(button, label)
        button.setObjectName("LauncherShellActionButton" if accent else "LauncherShellGhostButton")
        button.clicked.connect(callback)
        return button

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

    def _set_browser_content(self, markdown_text: str, base_path: Path) -> None:
        html_text = _markdown_to_html(markdown_text)
        self._viewer.setHtml(html_text)
        self._viewer.document().setBaseUrl(QUrl.fromLocalFile(str(base_path)))

    def _extract_title(self, markdown_text: str, path: Path) -> str:
        for line in markdown_text.splitlines():
            match = _HEADING_RE.match(line)
            if match:
                return _strip_heading_markup(match.group(2))
        return path.stem.replace("-", " ").title()

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
        self._home_button.setEnabled(self._current_location is None or self._relative_doc_path(self._current_location.path) != "index.md")

    def _show_error(self, message: str) -> None:
        self._doc_title.setText(_("Статья не найдена", "Article not found"))
        self._doc_language.setText("")
        self._doc_path.setText(message)
        self._viewer.setHtml(f"<p>{html.escape(message)}</p>")
        self._current_location = None
        self._update_nav_buttons()

    def _open_location(self, location: _WikiLocation, *, push_history: bool) -> None:
        try:
            markdown_text = location.path.read_text(encoding="utf-8")
        except Exception as exc:
            self._show_error(_("Не удалось открыть wiki-страницу: {err}", "Failed to open the wiki page: {err}").format(err=exc))
            return

        self._current_location = location
        self._set_browser_content(markdown_text, location.path)
        self._doc_title.setText(self._extract_title(markdown_text, location.path))

        requested = self._requested_language.upper()
        content = self._content_language.upper()
        if requested == content:
            self._doc_language.setText(_("Язык: {lang}", "Language: {lang}").format(lang=content))
        else:
            self._doc_language.setText(
                _("Язык: {content} (fallback вместо {requested})", "Language: {content} (fallback instead of {requested})").format(
                    content=content,
                    requested=requested,
                )
            )
        self._doc_path.setText(self._relative_doc_path(location.path))

        if push_history:
            self._push_history(location)
        self._update_nav_buttons()

        if location.anchor:
            QTimer.singleShot(0, lambda anchor=location.anchor: self._viewer.scrollToAnchor(anchor))
        else:
            self._viewer.verticalScrollBar().setValue(0)

    def open_target(self, target: str = "index.md", *, anchor: str = "", push_history: bool = True) -> None:
        path = self._resolve_start_path(target)
        if path is None:
            self._show_error(_("Wiki-страница не найдена: {target}", "Wiki page not found: {target}").format(target=target))
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

    def _handle_app_link(self, url: QUrl) -> bool:
        """Ссылки вида app:<page>[/<settings-category>][?section=<heading>].

        Открывают нужный экран приложения прямо из вики:
          app:home, app:sandbox, app:logs, app:news, app:developer, app:wiki
          app:settings/api                      — раздел настроек «API»
          app:settings/models?section=RAG       — + разворачивает подсекцию «RAG»
        Возвращает True, если ссылка обработана (была app:-ссылкой).
        """
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
                self._page_actions.show_settings_category(
                    category,
                    force=True,
                    subsection=section,
                )
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
