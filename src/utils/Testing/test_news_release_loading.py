from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtWidgets import QApplication, QLabel, QWidget

import ui.pages.news_page as news_page_module
from controllers.gui.news_controller import _build_release_preview, build_release_news_items


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_build_release_preview_keeps_summary_short():
    summary, has_details = _build_release_preview(
        """
        ## Changes
        - Fixed startup freeze
        - Added better loading state
        - Tweaked release card rendering
        Installation: unchanged
        """,
        limit=280,
    )

    assert "Fixed startup freeze" in summary
    assert "Added better loading state" in summary
    assert has_details is True


def test_build_release_news_items_uses_prepared_cache():
    gui = SimpleNamespace(
        _news_releases_cache=None,
        _news_release_cards_cache=[
            {
                "name": "v1.2.3",
                "tag_name": "v1.2.3",
                "summary": "Fast release summary",
                "published": "2026-07-04",
                "tag": "RELEASE",
                "url": "https://example.com/release",
            }
        ],
    )

    items = build_release_news_items(gui, limit=None)

    assert len(items) == 1
    assert items[0].title == "v1.2.3"
    assert items[0].summary == "Fast release summary"
    assert items[0].full_text == ""


def test_news_page_shows_loading_message_while_background_fetch_runs(monkeypatch):
    app = _app()
    host = QWidget()
    host._news_releases_cache = None
    host._news_release_cards_cache = None

    def _fake_async(gui, on_ready):
        return None

    monkeypatch.setattr(news_page_module, "load_news_releases_async", _fake_async)

    page = news_page_module.NewsPage(host)
    app.processEvents()

    texts = [label.text() for label in page.findChildren(QLabel)]
    assert any("Релизы ещё загружаются" in text for text in texts)
