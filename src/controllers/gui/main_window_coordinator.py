from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from main_logger import logger
from ui.pages.main_page_registry import MAIN_PAGE_ORDER, get_main_page_factory
from ui.widgets.settings_panel import apply_section_visibility


class MainWindowCoordinator:
    """Owns page construction, navigation and shell-level presentation flow."""

    def __init__(self, view: Any, presentation: Any) -> None:
        self._view = view
        self._presentation = presentation
        self._closed = False

    def initialize(self) -> None:
        if self._closed:
            raise RuntimeError("Main window coordinator is already closed")
        view = self._view
        view.page_map = {}
        view._deferred_main_pages = {"sandbox", "news", "developer", "wiki", "logs"}
        view._page_building = set()
        view._page_placeholders = {}
        view._pending_page_actions = {}
        try:
            apply_section_visibility(view)
        except Exception as exc:
            logger.debug("Failed to apply settings section visibility: %s", exc)
        self.ensure_page("home", eager=True)
        self.switch_page("home", activate=False)
        view.apply_initial_geometry(1560, 920)
        try:
            prebuild_settings = bool(view.settings.get("PREBUILD_SETTINGS_PAGE_ON_STARTUP", False))
        except Exception:
            prebuild_settings = False
        if prebuild_settings:
            QTimer.singleShot(450, self.prebuild_settings_page)
        self.prefetch_release_feed()

    def prefetch_release_feed(self) -> None:
        try:
            self._presentation.news.load_async(
                self._view,
                lambda _releases: None,
            )
        except Exception as exc:
            logger.debug("Release feed prefetch failed: %s", exc)

    def prebuild_settings_page(self) -> None:
        try:
            if not getattr(self._view, "page_map", {}).get("settings"):
                self.ensure_page("settings")
        except Exception as exc:
            logger.debug("Settings page prebuild failed: %s", exc)

    def ensure_page(self, page_key: str, *, eager: bool = False):
        view = self._view
        page = getattr(view, "page_map", {}).get(page_key)
        if page is not None:
            return page
        factory = get_main_page_factory(page_key)
        if factory is None or not hasattr(view, "page_stack"):
            return None
        if not eager and page_key in getattr(view, "_deferred_main_pages", set()):
            page = self._create_placeholder(page_key)
            view.page_map[page_key] = page
            view._page_placeholders[page_key] = page
            view.page_stack.addWidget(page)
            self._schedule_build(page_key)
            return page
        page = factory(view)
        view.page_map[page_key] = page
        view.page_stack.addWidget(page)
        view._ensure_settings_animation()
        return page

    @staticmethod
    def _create_placeholder(page_key: str) -> QWidget:
        frame = QFrame()
        frame.setObjectName("MainPageDeferredPlaceholder")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)
        title = QLabel(f"Loading {page_key}...")
        title.setObjectName("Subtle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addStretch(1)
        return frame

    def _schedule_build(self, page_key: str) -> None:
        if self._closed:
            return
        view = self._view
        if page_key in view._page_building:
            return
        view._page_building.add(page_key)
        QTimer.singleShot(35, lambda key=page_key: self._build_page_now(key))

    def _build_page_now(self, page_key: str) -> None:
        if self._closed:
            return
        view = self._view
        factory = get_main_page_factory(page_key)
        placeholder = view._page_placeholders.get(page_key)
        if factory is None or placeholder is None or not hasattr(view, "page_stack"):
            view._page_building.discard(page_key)
            return
        was_current = (
            getattr(view, "current_main_page", None) == page_key
            and view.page_stack.currentWidget() is placeholder
        )
        try:
            page = factory(view)
        except Exception as exc:
            view._page_building.discard(page_key)
            label = placeholder.findChild(QLabel)
            if label is not None:
                label.setText(f"Failed to load {page_key}: {exc}")
            return
        index = view.page_stack.indexOf(placeholder)
        if index >= 0:
            view.page_stack.insertWidget(index, page)
            view.page_stack.removeWidget(placeholder)
            placeholder.deleteLater()
        else:
            view.page_stack.addWidget(page)
        view.page_map[page_key] = page
        view._page_placeholders.pop(page_key, None)
        view._page_building.discard(page_key)
        view._ensure_settings_animation()
        if was_current:
            view.page_stack.setCurrentWidget(page)
            if hasattr(page, "on_activated"):
                page.on_activated()
        for action in view._pending_page_actions.pop(page_key, []):
            action(page)

    def when_page_ready(self, page_key: str, action: Callable[[Any], None]) -> None:
        view = self._view
        page = getattr(view, "page_map", {}).get(page_key)
        if page is not None and view._page_placeholders.get(page_key) is not page:
            action(page)
            return
        view._pending_page_actions.setdefault(page_key, []).append(action)
        self.ensure_page(page_key)

    def show_settings_category(self, category, *, force: bool = False, subsection=None) -> None:
        page = self.ensure_page("settings")
        if page is not None:
            page.show_category(category, force=force, subsection=subsection)

    def switch_page(self, page_key: str, *, activate: bool = True) -> None:
        view = self._view
        if page_key not in MAIN_PAGE_ORDER or not hasattr(view, "page_stack"):
            return
        page = self.ensure_page(page_key)
        if page is None:
            return
        current_page = view.page_stack.currentWidget()
        if current_page is not None and current_page is not page and hasattr(current_page, "on_deactivated"):
            current_page.on_deactivated()
        view.page_stack.setCurrentWidget(page)
        view.current_main_page = page_key
        if hasattr(view, "shell_sidebar"):
            view.shell_sidebar.set_active_page(page_key)
        is_placeholder = view._page_placeholders.get(page_key) is page
        if activate and not is_placeholder and hasattr(page, "on_activated"):
            page.on_activated()

    def activate_current_page(self) -> bool:
        view = self._view
        page_key = getattr(view, "current_main_page", "")
        page = getattr(view, "page_map", {}).get(page_key)
        if page is None or view._page_placeholders.get(page_key) is page:
            return False
        if hasattr(page, "on_activated"):
            page.on_activated()
        return True

    def open_release_page(self, release_id: str = "") -> None:
        self.switch_page("news")
        self.when_page_ready(
            "news",
            lambda page: page.focus_release(release_id) if hasattr(page, "focus_release") else None,
        )

    def refresh_logs(self) -> None:
        page = getattr(self._view, "logs_page", None)
        if page is not None:
            page.refresh_logs()

    def refresh_news(self) -> None:
        page = getattr(self._view, "news_page", None)
        if page is not None:
            page.refresh_content()

    def news_content(self) -> str:
        return self._presentation.news.get_content()

    def news_releases(self):
        return self._presentation.news.get_releases()

    def refresh_home_primary_label(self) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.refresh_primary_label()

    def set_home_progress(self, text: str, value: int, maximum: int, *, busy: bool = False) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.set_progress(text, value, maximum, busy=busy)

    def hide_home_progress(self) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.hide_progress()

    def run_home_primary_action(self) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.run_primary_action()

    def run_home_install_unity(self) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.run_install_unity()

    def run_home_verify_action(self) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.run_verify_action()

    def show_home_extra_menu(self, anchor_widget) -> None:
        page = getattr(self._view, "home_page", None)
        if page is not None:
            page.show_extra_menu(anchor_widget)

    def find_unity_executable(self):
        configured = self._presentation.settings.get("UNITY_INSTALL_DIR") or None
        return self._presentation.home.find_unity_executable(configured)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        view = self._view
        page = None
        if hasattr(view, "page_stack"):
            page = view.page_stack.currentWidget()
        if page is not None and hasattr(page, "on_deactivated"):
            try:
                page.on_deactivated()
            except Exception as exc:
                logger.debug("Current page deactivation failed during shutdown: %s", exc)
        pending = getattr(view, "_pending_page_actions", None)
        if isinstance(pending, dict):
            pending.clear()
        building = getattr(view, "_page_building", None)
        if isinstance(building, set):
            building.clear()
