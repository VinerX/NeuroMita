from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from controllers.gui.news_controller import (
    NewsReleasesStore,
    _build_release_preview,
    build_release_news_items,
)
from controllers.gui.news_page_view_model import NewsPageViewModel
from ui.pages.news_page import NewsPage


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
    store = NewsReleasesStore()
    store.cards = [
        {
            "name": "v1.2.3",
            "tag_name": "v1.2.3",
            "summary": "Fast release summary",
            "published": "2026-07-04",
            "tag": "RELEASE",
            "url": "https://example.com/release",
        }
    ]

    items = build_release_news_items(store, limit=None)

    assert len(items) == 1
    assert items[0].title == "v1.2.3"
    assert items[0].summary == "Fast release summary"
    assert items[0].full_text == ""


def test_news_page_shows_loading_message_while_background_fetch_runs(monkeypatch):
    app = _app()
    host = QWidget()

    stub_news = SimpleNamespace(repository="Atm4x/NeuroMita")
    view_model_box = {}

    def _make_view_model(_host, parent=None):
        view_model = NewsPageViewModel(host=_host, news=stub_news, parent=parent)
        # Фоновая загрузка «никогда не завершается» — страница обязана
        # показывать состояние загрузки, а не пустую ленту.
        monkeypatch.setattr(view_model, "run_coalesced", lambda *a, **k: True)
        view_model_box["vm"] = view_model
        return view_model

    view_model = _make_view_model(host)
    actions = SimpleNamespace(refresh_home_news=lambda: None)
    page = NewsPage(host, view_model, actions)
    app.processEvents()

    assert view_model_box["vm"].state.loading is True
    texts = [label.text() for label in page.findChildren(QLabel)]
    assert any("Релизы ещё загружаются" in text for text in texts)
