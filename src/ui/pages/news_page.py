from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ui.pages.news_support import (
    NEWS_REPO,
    build_release_news_items,
    get_news_content,
    get_news_releases,
    invalidate_news_releases,
    load_news_releases_async,
)
from ui.widgets.launcher_dashboard_helpers import DashboardAction, NewsItem, create_news_page
from utils import _


class NewsPage(QWidget):
    # Сигнал перепрыгивает результат фоновой загрузки релизов в GUI-поток.
    _releases_ready = pyqtSignal(object)

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("NewsPage")

        self._page_widget = None
        self._pending_focus_release_id = ""
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._releases_ready.connect(self._on_releases_ready)
        self._sync_host_exports()
        self.refresh_content()

    def _sync_host_exports(self):
        self.gui.news_page = self

    def _build_page_widget(self, *, loading: bool = False) -> QWidget:
        repo_url = f"https://github.com/{NEWS_REPO}/releases"
        if loading:
            items = [
                NewsItem(
                    _("Загрузка релизов…", "Loading releases…"),
                    _(
                        "Получаем ленту релизов с GitHub…",
                        "Fetching the release feed from GitHub…",
                    ),
                    tag="…",
                )
            ]
        else:
            # Кэш уже прогрет фоновой загрузкой — build не ходит в сеть.
            items = build_release_news_items(self.gui)
        return create_news_page(
            title=_("Релизы NeuroMita", "NeuroMita releases"),
            subtitle=_(
                "Лента публичных релизов с GitHub ({repo}): changelog, бета-сборки и ссылки на полные заметки.",
                "GitHub release feed ({repo}): changelog, beta builds and links to full notes.",
            ).format(repo=NEWS_REPO),
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
        # Не блокируем GUI: показываем плейсхолдер «Загрузка…» и грузим ленту
        # в фоне. Готовый список придёт сигналом _releases_ready на GUI-поток.
        invalidate_news_releases(self.gui)
        self._set_page_widget(self._build_page_widget(loading=True))
        load_news_releases_async(self.gui, lambda releases: self._releases_ready.emit(releases))

    def _on_releases_ready(self, releases):
        self._set_page_widget(self._build_page_widget())

        if self._pending_focus_release_id:
            release_id = self._pending_focus_release_id
            self._pending_focus_release_id = ""
            QTimer.singleShot(0, lambda rid=release_id: self.focus_release(rid))

        home_page = getattr(self.gui, "home_page", None)
        if home_page is not None and hasattr(home_page, "refresh_news_content"):
            home_page.refresh_news_content()

    def on_activated(self):
        pass

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
        return get_news_releases(self.gui)

    def get_news_content(self) -> str:
        return get_news_content(self.gui)


def build_news_page(window) -> QWidget:
    return NewsPage(window)
