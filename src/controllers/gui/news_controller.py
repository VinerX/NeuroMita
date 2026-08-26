from __future__ import annotations
from core.error_utils import format_exception

import re
import threading
from controllers.gui.async_runner import run_async
from typing import Any, Callable

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from main_logger import logger
from core.networking import shared_http_client_registry
from utils.release_assets import raw_release_has_launcher_assets
from ui.widgets.launcher_dashboard_helpers import DashboardAction, NewsItem
from utils import _


NEWS_REPO = "Atm4x/NeuroMita"
_HTTP_CLIENT = shared_http_client_registry().acquire("news")


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^>]+)>")
_FENCE_RE = re.compile(r"^```")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_ORDERED_RE = re.compile(r"^\s*(\d+)\.\s+")
_MD_DECORATION_RE = re.compile(r"[*_~`>#]")


class NewsReleasesStore:
    """Кэш ленты релизов. Владелец — presentation-хаб (`presentation.news`);
    раньше это состояние жило атрибутами на главном окне."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.releases: list[dict[str, Any]] | None = None
        self.cards: list[dict[str, Any]] | None = None
        self.waiters: list[Callable[[list[dict[str, Any]]], None]] = []
        self.inflight = False

    def invalidate(self) -> None:
        self.releases = None
        self.cards = None


def load_news_releases_async(
    store: NewsReleasesStore,
    target,
    on_ready: Callable[[list[dict[str, Any]]], None],
) -> None:
    """Неблокирующая загрузка ленты релизов с GitHub.

    `on_ready(releases)` вызывается ВСЕГДА:
      - сразу и синхронно, если данные уже в кэше;
      - иначе из фонового потока, когда сеть ответит (или таймаут/ошибка → []).
    Вызывающий сам обязан перепрыгнуть в GUI-поток внутри `on_ready` (через
    сигнал / QTimer / собственный диспетч), т.к. колбэк может прийти из воркера.

    Параллельные запросы коалесцируются: пока один поток грузит, остальные
    подписчики просто ждут его результат — повторного обращения к сети нет.
    Это и есть фикс зависания GUI: раньше `get_news_releases` дёргал
    Синхронный сетевой запрос прямо в GUI-потоке (кнопка «Обновить», старт
    главной страницы) и при недоступном GitHub морозил окно на ~10 секунд.
    """
    if store.releases is not None:
        on_ready(store.releases)
        return

    start_worker = False
    with store.lock:
        # Кэш мог наполниться, пока ждали лок — проверяем ещё раз под локом.
        if store.releases is not None:
            on_ready(store.releases)
            return
        store.waiters.append(on_ready)
        if not store.inflight:
            store.inflight = True
            start_worker = True

    if not start_worker:
        return

    def worker():
        releases = get_news_releases(store)
        with store.lock:
            pending = list(store.waiters)
            store.waiters.clear()
            store.inflight = False
        for callback in pending:
            try:
                callback(releases)
            except Exception:
                logger.exception("[news] on_ready callback failed")

    run_async(target, worker, name="news-fetch")


def get_news_releases(store: NewsReleasesStore) -> list[dict[str, Any]]:
    cached = store.releases
    if cached is not None:
        return cached

    try:
        response = _HTTP_CLIENT.get(
            f"https://api.github.com/repos/{NEWS_REPO}/releases",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code != 200:
            logger.info(f"[news] Failed to fetch releases: HTTP {response.status_code}")
            store.releases = []
            store.cards = []
            return []

        raw_data = response.json() or []
        data = [item for item in raw_data if raw_release_has_launcher_assets(item)]
        store.releases = data
        store.cards = _prepare_release_cards(data)
        return data
    except Exception as exc:
        logger.info(f"[news] Failed to fetch releases: {format_exception(exc)}")
        store.releases = []
        store.cards = []
        return []


def get_news_content(store: NewsReleasesStore) -> str:
    releases = get_news_releases(store)
    if not releases:
        return _("Не удалось загрузить новости", "Failed to load news")

    chunks: list[str] = []
    for release in releases:
        chunks.append(f"# {release.get('name') or release.get('tag_name', '')}")
        body = str(release.get("body") or "").strip()
        if body:
            chunks.append(body)
    return "\n".join(chunks)


def _iter_clean_release_lines(body: str):
    for raw_line in str(body or "").splitlines():
        line = _clean_release_line(raw_line)
        if line:
            yield line


def _build_release_preview(body: str, *, limit: int = 280) -> tuple[str, bool]:
    preferred: list[str] = []
    fallback: list[str] = []
    meaningful_count = 0

    for line in _iter_clean_release_lines(body):
        meaningful_count += 1
        lower = line.lower()
        if lower.startswith("установка:") or lower.startswith("installation:"):
            if len(fallback) < 3:
                fallback.append(line)
            continue
        if lower.startswith("изменения") or lower.startswith("changes"):
            continue
        if len(preferred) < 3:
            preferred.append(line)
        if len(preferred) >= 3 and meaningful_count >= 4:
            break

    candidate_lines = preferred or fallback
    if not candidate_lines:
        return _("Без описания.", "No description."), False

    candidate = " ".join(candidate_lines).strip()
    truncated_by_limit = len(candidate) > limit
    has_details = meaningful_count > len(candidate_lines) or truncated_by_limit
    summary = candidate[:limit].rstrip()
    if truncated_by_limit:
        word_boundary = summary.rfind(" ")
        if word_boundary > limit // 2:
            summary = summary[:word_boundary].rstrip()
    if has_details:
        summary = f"{summary} …"
    return summary, has_details


def _prepare_release_cards(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repo_url = f"https://github.com/{NEWS_REPO}/releases"
    prepared: list[dict[str, Any]] = []
    for release in releases:
        tag_name = str(release.get("tag_name") or "")
        name = str(release.get("name") or "").strip() or tag_name or _("Релиз", "Release")
        body = str(release.get("body") or "").strip()
        summary, has_details = _build_release_preview(body, limit=280)
        full_text = normalize_release_body(body)
        prepared.append(
            {
                "name": name,
                "tag_name": tag_name,
                "summary": summary,
                "full_text": full_text if has_details else "",
                "published": str(release.get("published_at") or "")[:10],
                "tag": "PRE-RELEASE" if release.get("prerelease") else "RELEASE",
                "url": str(release.get("html_url") or repo_url),
            }
        )
    return prepared


def _get_prepared_release_cards(store: NewsReleasesStore) -> list[dict[str, Any]]:
    cached = store.cards
    if cached is not None:
        return cached
    releases = get_news_releases(store)
    prepared = _prepare_release_cards(releases)
    store.cards = prepared
    return prepared


def _clean_release_line(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line:
        return ""
    if _FENCE_RE.match(line):
        return ""
    line = _HEADING_RE.sub("", line)
    line = _BULLET_RE.sub("- ", line)
    line = _ORDERED_RE.sub(r"\1. ", line)
    line = _LINK_RE.sub(r"\1", line)
    line = _AUTOLINK_RE.sub(r"\1", line)
    line = _MD_DECORATION_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def normalize_release_body(body: str) -> str:
    lines: list[str] = []
    last_blank = False
    for raw_line in str(body or "").splitlines():
        if not raw_line.strip():
            if lines and not last_blank:
                lines.append("")
                last_blank = True
            continue
        line = _clean_release_line(raw_line)
        if not line:
            continue
        lines.append(line)
        last_blank = False
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def build_release_summary(body: str, *, limit: int = 280) -> str:
    normalized = normalize_release_body(body)
    if not normalized:
        return _("Без описания.", "No description.")

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    preferred: list[str] = []
    fallback: list[str] = []
    for line in lines:
        lower = line.lower()
        if lower.startswith("установка:") or lower.startswith("installation:"):
            fallback.append(line)
            continue
        if lower.startswith("изменения") or lower.startswith("changes"):
            continue
        preferred.append(line)

    candidate_lines = preferred or fallback or lines
    text = " ".join(candidate_lines[:3]).strip()
    return text[:limit]


def parse_news_items(raw_text: str) -> list[NewsItem]:
    if not raw_text:
        return [
            NewsItem(
                _("Новости недоступны", "News unavailable"),
                _(
                    "Не удалось загрузить удалённую ленту, поэтому страница показывает локальный shell-state.",
                    "Remote feed is unavailable, so the page falls back to local shell state.",
                ),
                tag="OFFLINE",
            )
        ]

    items: list[NewsItem] = []
    current_title = ""
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_title, current_lines
        if not current_title and not current_lines:
            return

        summary = " ".join(line.strip("-* ").strip() for line in current_lines if line.strip())
        if not summary:
            summary = _(
                "Подробности внутри полной ленты новостей.",
                "Details are available in the full news feed.",
            )
        items.append(
            NewsItem(
                current_title or _("Обновление", "Update"),
                summary[:260],
                tag="NEWS",
            )
        )
        current_title = ""
        current_lines = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            flush_current()
            current_title = line.lstrip("#").strip()
            continue
        if len(current_lines) < 3:
            current_lines.append(line)

    flush_current()

    if not items:
        fallback_lines = [line.strip() for line in raw_text.splitlines() if line.strip()][:4]
        items = [
            NewsItem(
                _("Сводка", "Summary"),
                " ".join(fallback_lines)[:260] if fallback_lines else _("Новости пока пусты.", "News feed is currently empty."),
                tag="NEWS",
            )
        ]

    return items[:6]


def build_release_news_items(store: NewsReleasesStore, *, limit: int | None = 8) -> list[NewsItem]:
    prepared_cards = _get_prepared_release_cards(store)
    if not prepared_cards:
        return [
            NewsItem(
                _("Релизы недоступны", "Releases unavailable"),
                _(
                    "Не удалось получить ленту релизов с GitHub. Проверьте подключение к сети.",
                    "Failed to fetch releases from GitHub. Check your network connection.",
                ),
                tag="OFFLINE",
            )
        ]

    selected = prepared_cards if limit is None else prepared_cards[:limit]
    items: list[NewsItem] = []
    for release in selected:
        tag_name = str(release.get("tag_name") or "")
        name = str(release.get("name") or "").strip() or tag_name or _("Релиз", "Release")
        summary = str(release.get("summary") or "").strip() or build_release_summary("")
        published = str(release.get("published") or "")[:10]
        tag = str(release.get("tag") or "RELEASE")
        url = str(release.get("url") or f"https://github.com/{NEWS_REPO}/releases")
        full_text = str(release.get("full_text") or "").strip()
        items.append(
            NewsItem(
                name,
                summary,
                tag=tag,
                item_id=tag_name or name,
                timestamp=published,
                full_text=full_text,
                action=DashboardAction(
                    _("Открыть релиз", "Open release"),
                    callback=lambda _checked=False, target_url=url: QDesktopServices.openUrl(QUrl(target_url)),
                    icon_name="fa6s.up-right-from-square",
                    accent=False,
                ),
            )
        )
    return items
