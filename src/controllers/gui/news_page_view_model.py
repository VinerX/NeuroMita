from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import immutable_payload
from ui.pages.news_presentation import (
    ActivateNewsPage,
    NewsPageState,
    NewsPageUpdated,
    RefreshNewsPage,
)


class NewsPageViewModel(IntentViewModel[NewsPageState]):
    def __init__(self, *, host: Any, news, parent=None) -> None:
        super().__init__(NewsPageState(repository=str(news.repository)), parent)
        self._host = host
        self._news = news

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ActivateNewsPage):
            if not self.state.items and not self.state.loading:
                self.refresh(force=False)
            return
        if isinstance(intent, RefreshNewsPage):
            self.refresh(force=bool(intent.force))

    def refresh(self, *, force: bool) -> None:
        if force:
            self._news.invalidate()
        self.update_state(loading=True, error=None)

        def worker() -> dict[str, Any]:
            releases = list(self._news.get_releases() or [])
            return {
                "items": tuple(self._news.build_items()),
                "releases": releases,
                "content": str(self._news.get_content() or ""),
            }

        def applied(payload: dict[str, Any]) -> None:
            self.update_state(
                items=tuple(payload.get("items") or ()),
                releases=immutable_payload(payload.get("releases") or []),
                content=str(payload.get("content") or ""),
                loading=False,
                error=None,
                revision=self.state.revision + 1,
            )
            self.emit_effect(NewsPageUpdated())

        self.run_coalesced(
            "news-page-refresh",
            worker,
            applied,
            lambda error: self.update_state(loading=False, error=str(error)),
        )
