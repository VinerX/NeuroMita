from __future__ import annotations
from core.error_utils import format_exception

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from services.update_contour import target_for_contour
from ui.mvvm import immutable_payload
from ui.pages.news_presentation import (
    ActivateNewsPage,
    NewsPageState,
    NewsPageUpdated,
    RefreshNewsPage,
)


class NewsPageViewModel(IntentViewModel[NewsPageState]):
    def __init__(self, *, host: Any, news, settings, parent=None) -> None:
        target = target_for_contour(settings.get("UPDATE_CONTOUR", "release"))
        news.set_repository(target.repo)
        super().__init__(NewsPageState(repository=target.repo), parent)
        self._host = host
        self._news = news
        self._settings = settings

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ActivateNewsPage):
            if not self.state.items and not self.state.loading:
                self.refresh(force=False)
            return
        if isinstance(intent, RefreshNewsPage):
            self.refresh(force=bool(intent.force))

    def refresh(self, *, force: bool) -> None:
        target = target_for_contour(self._settings.get("UPDATE_CONTOUR", "release"))
        repository_changed = self._news.set_repository(target.repo)
        if self.state.repository != target.repo:
            self.update_state(repository=target.repo)
        if force and not repository_changed:
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
            lambda error: self.update_state(loading=False, error=format_exception(error)),
        )
