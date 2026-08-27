from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ui.widgets.launcher_dashboard_helpers import DashboardAction, NewsItem, create_news_page
from ui.mvvm import mutable_payload
from ui.pages.news_presentation import (
    ActivateNewsPage,
    NewsPageState,
    NewsPageUpdated,
    RefreshNewsPage,
)
from utils import _


class NewsPage(QWidget):
    def __init__(self, parent, view_model, page_actions):
        super().__init__(parent)
        self._page_actions = page_actions
        self.setObjectName("NewsPage")

        self._page_widget = None
        self._pending_focus_release_id = ""
        self._state = NewsPageState()
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._view_model = view_model
        self._view_model.setParent(self)
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda *_: self._view_model.close())
        self._view_model.dispatch(ActivateNewsPage())

    def _build_page_widget(self, *, loading: bool = False) -> QWidget:
        repository = self._state.repository
        repo_url = f"https://github.com/{repository}/releases"
        if loading:
            items = [
                NewsItem(
                    _("Загрузка релизов…", "Loading releases…"),
                    _(
                        "Релизы ещё загружаются в фоне. Страница обновится автоматически.",
                        "Releases are still loading in the background. This page will refresh automatically.",
                    ),
                    tag="…",
                )
            ]
        else:
            # Кэш уже прогрет фоновой загрузкой — build не ходит в сеть.
            items = list(self._state.items)
        return create_news_page(
            title=_("Релизы NeuroMita", "NeuroMita releases"),
            subtitle=_(
                "Лента публичных релизов с GitHub ({repo}): changelog, бета-сборки и ссылки на полные заметки.",
                "GitHub release feed ({repo}): changelog, beta builds and links to full notes.",
            ).format(repo=repository),
            items=items,
            header_actions=[
                DashboardAction(_("Обновить", "Refresh"), callback=self.refresh_content, icon_name="fa6s.rotate-right"),
                DashboardAction(
                    _("Открыть на GitHub", "Open on GitHub"),
                    callback=lambda: QDesktopServices.openUrl(QUrl(repo_url)),
                    icon_name="fa6b.github",
                    accent=False,
                ),
            ],
        )

    def _set_page_widget(self, new_widget: QWidget):
        if self._page_widget is not None:
            self._root_layout.removeWidget(self._page_widget)
            self._page_widget.deleteLater()
        self._page_widget = new_widget
        self._root_layout.addWidget(new_widget)

    def refresh_content(self):
        self._view_model.dispatch(RefreshNewsPage(force=True))

    def render(self, state: NewsPageState) -> None:
        self._state = state
        self._set_page_widget(self._build_page_widget(loading=state.loading))

        if not state.loading and self._pending_focus_release_id:
            release_id = self._pending_focus_release_id
            self._pending_focus_release_id = ""
            QTimer.singleShot(0, lambda rid=release_id: self.focus_release(rid))

    def handle_effect(self, effect) -> None:
        if not isinstance(effect, NewsPageUpdated):
            return
        self._page_actions.refresh_home_news()

    def on_activated(self):
        self._view_model.dispatch(ActivateNewsPage())

    def focus_release(self, release_id: str) -> bool:
        target_id = str(release_id or "").strip()
        if not target_id:
            return False

        page_widget = self._page_widget
        if page_widget is None:
            self._pending_focus_release_id = target_id
            return False

        cards = page_widget.findChildren(QFrame, "LauncherShellNewsCard")
        target_card = next((card for card in cards if str(card.property("itemId") or "") == target_id), None)
        if target_card is None:
            self._pending_focus_release_id = target_id
            return False

        scroll = page_widget.findChild(QScrollArea)
        if scroll is not None:
            scroll.ensureWidgetVisible(target_card, 0, 24)

        target_card.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def get_news_releases(self):
        return list(mutable_payload(self._state.releases) or [])

    def get_news_content(self) -> str:
        return str(self._state.content or "")


def build_news_page(parent, view_model, page_actions) -> QWidget:
    return NewsPage(parent, view_model, page_actions)
