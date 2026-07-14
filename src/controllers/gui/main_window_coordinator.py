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
        page = self._create_page(page_key, factory)
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
            page = self._create_page(page_key, factory)
        except Exception as exc:
            logger.error(
                "Failed to build main page '%s': %s",
                page_key,
                exc,
                exc_info=True,
            )
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

    def _create_page(self, page_key: str, factory):
        view = self._view
        view_models = self._presentation.view_models
        if page_key == "home":
            page = factory(view, view_models.home(view), view._page_actions)
            view.home_page = page
            view.home_primary_button = page.primary_button
            return page
        if page_key == "news":
            page = factory(view, view_models.news_page(view), view._page_actions)
            view.news_page = page
            return page
        if page_key == "sandbox":
            from ui.widgets.chat_panel_presentation import ChatPanelActions

            chat_actions = ChatPanelActions(
                reload_history=view.load_chat_history,
                clear_chat=view.clear_chat_display,
                send_message=view.send_message,
                open_settings=lambda category: self.show_settings_category(
                    category,
                    force=True,
                ),
                show_image=view.show_chat_image,
                surface_ready=view.bind_chat_panel,
            )
            page = factory(
                view,
                view_models.sandbox(view),
                character_state_view_model=view_models.character_state(view),
                chat_panel_view_model=view_models.chat_panel(view),
                chat_panel_actions=chat_actions,
                page_actions=view._page_actions,
            )
            view.bind_sandbox_page(page)
            return page
        if page_key == "settings":
            page = factory(
                view,
                view_models.settings_page(view),
                view._page_actions,
                getattr(view, "settings_binding", None),
            )
            view.settings_page = page
            view.settings_buttons = page.settings_buttons
            view._category_modes = page.category_modes
            view.settings_containers = page.settings_containers
            view.settings_overview_container = page.settings_overview_container
            view.settings_overlay = page.settings_overlay
            view.current_settings_category = page.current_settings_category
            view.SETTINGS_PANEL_WIDTH = page.SETTINGS_PANEL_WIDTH
            view.SETTINGS_SIDEBAR_WIDTH = page.SETTINGS_SIDEBAR_WIDTH
            view.settings_resize_handle = page.settings_resize_handle
            return page
        if page_key == "developer":
            page = factory(
                view,
                view_models.finetune_data(view),
                view._page_actions,
                getattr(view, "settings_binding", None),
            )
            view.developer_page = page
            return page
        if page_key == "logs":
            page = factory(view, view_models.logs_page(view), view._page_actions)
            view.logs_page = page
            view.logs_window = page.logs_window
            return page
        if page_key == "wiki":
            page = factory(view, view._page_actions, getattr(view, "settings_binding", None))
            view.wiki_page = page
            return page
        return factory(view)

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

    def is_current(self, page_key: str) -> bool:
        return str(getattr(self._view, "current_main_page", "") or "") == str(
            page_key or ""
        )

    def show_guide(self) -> None:
        callback = getattr(self._view, "_show_guide", None)
        if callable(callback):
            callback()

    def view_last_context(self) -> None:
        callback = getattr(self._view, "_on_debug_view_last_context", None)
        if callable(callback):
            callback()

    def refresh_status(self) -> None:
        callback = getattr(self._view, "update_status_colors", None)
        if callable(callback):
            callback()

    def open_release_page(self, release_id: str = "") -> None:
        self.switch_page("news")
        self.when_page_ready(
            "news",
            lambda page: page.focus_release(release_id) if hasattr(page, "focus_release") else None,
        )

    def refresh_sidebar_version(self) -> None:
        sidebar = getattr(self._view, "shell_sidebar", None)
        callback = getattr(sidebar, "refresh_version_label", None)
        if callable(callback):
            callback()

    def refresh_home_news(self) -> None:
        page = getattr(self._view, "home_page", None)
        callback = getattr(page, "refresh_news_content", None)
        if callable(callback):
            callback()

    def open_sandbox_debug(self) -> None:
        self.switch_page("sandbox")
        self.when_page_ready(
            "sandbox",
            lambda page: page.show_debug_tab() if hasattr(page, "show_debug_tab") else None,
        )

    def refresh_debug_info(self) -> None:
        callback = getattr(self._view, "update_debug_info", None)
        if callable(callback):
            callback()

    def insert_debug_message(self, text: str, *, as_user: bool) -> None:
        normalized = str(text or "").strip()
        if not normalized:
            return
        shell_actions = getattr(self._view, "_shell_actions", None)
        if shell_actions is None:
            return
        shell_actions.insert_debug_message(
            text=normalized,
            character_id=shell_actions.current_character_id(),
            as_user=bool(as_user),
        )

    def save_debug_snapshot(self) -> None:
        callback = getattr(self._view, "_on_debug_save_snapshot", None)
        if callable(callback):
            callback()

    def load_debug_snapshot(self) -> None:
        callback = getattr(self._view, "_on_debug_load_snapshot", None)
        if callable(callback):
            callback()

    def view_debug_context(self, initial_tab: str = "request") -> None:
        callback = getattr(self._view, "_on_debug_view_last_context", None)
        if callable(callback):
            callback(initial_tab=str(initial_tab or "request"))

    def build_settings_section(self, category: str, layout) -> None:
        self._presentation.settings_sections.build_section(
            self._view,
            str(category),
            layout,
        )

    def sync_settings_mode_widgets(self, mode_value) -> None:
        from PyQt6.QtCore import Qt
        from ui.pages.settings.settings_presentation import get_mode_label

        clean_label = get_mode_label(mode_value)
        for attr_name in ("INTERFACE_MODE", "chat_mode_combobox"):
            widget = getattr(self._view, attr_name, None)
            if widget is None or not hasattr(widget, "findText"):
                continue
            index = widget.findText(clean_label, Qt.MatchFlag.MatchFixedString)
            if index < 0 or widget.currentIndex() == index:
                continue
            widget.blockSignals(True)
            try:
                widget.setCurrentIndex(index)
            finally:
                widget.blockSignals(False)

    def apply_settings_aux_visibility(self) -> None:
        try:
            from ui.widgets.status_indicators_widget import apply_capture_visibility

            apply_capture_visibility(self._view)
        except Exception:
            pass

        sidebar = getattr(self._view, "shell_sidebar", None)
        if sidebar is None or not hasattr(sidebar, "apply_section_visibility"):
            return
        try:
            from ui.widgets.settings_panel import is_section_enabled

            sidebar.apply_section_visibility(is_section_enabled)
        except Exception:
            pass

    def refresh_tester_code(self) -> None:
        entry = getattr(self._view, "_tester_code_entry", None)
        if entry is None:
            return
        value = self._presentation.settings.get("TESTER_CODE", "")
        entry.setText(str(value or ""))

    def register_status_indicator(self, attr_name: str, widget) -> None:
        from ui.widgets.status_indicators_widget import _register_indicator

        _register_indicator(self._view, str(attr_name), widget)

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

        # Page widgets outlive this coordinator until Qt destroys the main
        # window. Close their presentation models explicitly before the global
        # TaskSupervisor is shut down; otherwise queued refreshes can race with
        # application shutdown and attempt to start new worker threads.
        pages = getattr(view, "page_map", {})
        closed_models: set[int] = set()
        for page in tuple(pages.values()) if isinstance(pages, dict) else ():
            for attribute in (
                "view_model",
                "_view_model",
                "_character_state_view_model",
                "_chat_panel_view_model",
            ):
                model = getattr(page, attribute, None)
                close_model = getattr(model, "close", None)
                if not callable(close_model) or id(model) in closed_models:
                    continue
                try:
                    close_model()
                except Exception as exc:
                    logger.debug(
                        "Page presentation model close failed during shutdown: %s",
                        exc,
                    )
                closed_models.add(id(model))

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
