from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from main_logger import logger
from ui.widgets.launcher_dashboard_helpers import DashboardAction, NewsItem
from utils import _


NEWS_REPO = "Atm4x/NeuroMita"


def invalidate_news_releases(gui) -> None:
    gui._news_releases_cache = None


def get_news_releases(gui) -> list[dict[str, Any]]:
    cached = getattr(gui, "_news_releases_cache", None)
    if cached is not None:
        return cached

    try:
        import requests

        response = requests.get(
            f"https://api.github.com/repos/{NEWS_REPO}/releases",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        if response.status_code != 200:
            logger.info(f"Не удалось получить релизы: HTTP {response.status_code}")
            gui._news_releases_cache = []
            return []

        data = response.json() or []
        gui._news_releases_cache = data
        return data
    except Exception as exc:
        logger.info(f"Ошибка при получении релизов: {exc}")
        gui._news_releases_cache = []
        return []


def get_news_content(gui) -> str:
    releases = get_news_releases(gui)
    if not releases:
        return _("Не удалось загрузить новости", "Failed to load news")

    chunks: list[str] = []
    for release in releases:
        chunks.append(f"# {release.get('name') or release.get('tag_name', '')}")
        body = str(release.get("body") or "").strip()
        if body:
            chunks.append(body)
    return "\n".join(chunks)


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


def build_release_news_items(gui, *, limit: int | None = 8) -> list[NewsItem]:
    releases = get_news_releases(gui)
    repo_url = f"https://github.com/{NEWS_REPO}/releases"
    if not releases:
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

    selected = releases if limit is None else releases[:limit]
    items: list[NewsItem] = []
    for release in selected:
        tag_name = str(release.get("tag_name") or "")
        name = str(release.get("name") or "").strip() or tag_name or _("Релиз", "Release")
        body = str(release.get("body") or "").strip()
        summary_lines = [line.strip("-* ").strip() for line in body.splitlines() if line.strip()]
        summary = " ".join(summary_lines)[:280] if summary_lines else _("Без описания.", "No description.")
        published = str(release.get("published_at") or "")[:10]
        tag = "PRE-RELEASE" if release.get("prerelease") else "RELEASE"
        url = str(release.get("html_url") or repo_url)
        items.append(
            NewsItem(
                name,
                summary,
                tag=tag,
                timestamp=published,
                action=DashboardAction(
                    _("Открыть релиз", "Open release"),
                    callback=lambda _checked=False, target_url=url: QDesktopServices.openUrl(QUrl(target_url)),
                    icon_name="fa6s.up-right-from-square",
                    accent=False,
                ),
            )
        )
    return items
