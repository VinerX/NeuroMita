from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.pages.news_support import (
    NEWS_REPO,
    build_release_news_items,
    get_news_content,
    get_news_releases,
    invalidate_news_releases,
)
from ui.widgets.launcher_dashboard_helpers import DashboardAction, create_news_page
from utils import _


class NewsPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("NewsPage")

        self._page_widget = None
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._sync_host_exports()
        self.refresh_content()

    def _sync_host_exports(self):
        self.gui.news_page = self

    def _build_page_widget(self) -> QWidget:
        repo_url = f"https://github.com/{NEWS_REPO}/releases"
        return create_news_page(
            title=_("Релизы NeuroMita", "NeuroMita releases"),
            subtitle=_(
                "Лента публичных релизов с GitHub ({repo}): changelog, бета-сборки и ссылки на полные заметки.",
                "GitHub release feed ({repo}): changelog, beta builds and links to full notes.",
            ).format(repo=NEWS_REPO),
            items=build_release_news_items(self.gui),
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

    def refresh_content(self):
        invalidate_news_releases(self.gui)
        new_widget = self._build_page_widget()

        if self._page_widget is not None:
            self._root_layout.removeWidget(self._page_widget)
            self._page_widget.deleteLater()

        self._page_widget = new_widget
        self._root_layout.addWidget(new_widget)

        home_page = getattr(self.gui, "home_page", None)
        if home_page is not None and hasattr(home_page, "refresh_news_content"):
            home_page.refresh_news_content()

    def on_activated(self):
        pass

    def get_news_releases(self):
        return get_news_releases(self.gui)

    def get_news_content(self) -> str:
        return get_news_content(self.gui)


def build_news_page(window) -> QWidget:
    return NewsPage(window)
