from __future__ import annotations

from typing import Any, Callable


class _BoundActions:
    def __init__(self) -> None:
        self._target: Any = None

    def bind(self, target: Any) -> None:
        self._target = target


class ShellActionsAdapter(_BoundActions):
    @property
    def is_closing(self) -> bool:
        return bool(self._target and self._target.is_closing)

    def load_history(self) -> None:
        if self._target is None:
            raise RuntimeError("Shell actions are not bound")
        self._target.load_history()

    def request_debug_info(self, callback: Callable[[Any], None]) -> None:
        if self._target is not None:
            self._target.request_debug_info(callback)

    def request_token_stats(self, callback: Callable[[Any], None]) -> None:
        if self._target is not None:
            self._target.request_token_stats(callback)

    def clear_chat(self) -> bool:
        if self._target is None:
            return False
        self._target.clear_chat()
        return True

    def send_message(self, **kwargs):
        if self._target is None:
            return False
        return self._target.send_message(**kwargs)

    def load_more_history(self) -> None:
        if self._target is not None:
            self._target.load_more_history()

    def close_application(self) -> None:
        if self._target is not None:
            self._target.close_application()

    def insert_debug_message(self, **kwargs) -> None:
        if self._target is not None:
            self._target.insert_debug_message(**kwargs)

    def save_snapshot(self, character_id: str) -> None:
        if self._target is not None:
            self._target.save_snapshot(character_id)

    def load_snapshot(self, *, file_path: str, character_id: str) -> None:
        if self._target is not None:
            self._target.load_snapshot(
                file_path=file_path,
                character_id=character_id,
            )

    def snapshot_start_directory(self, character_id: str) -> str:
        if self._target is None:
            return "."
        return str(self._target.snapshot_start_directory(character_id))

    def current_character_id(self) -> str:
        return self._target.current_character_id() if self._target is not None else ""

    def request_status(self, callback: Callable[[Any], None]) -> None:
        if self._target is not None:
            self._target.request_status(callback)

    def voice_model_state(self, model_id: str) -> tuple[bool, bool]:
        if self._target is None:
            return False, False
        return self._target.voice_model_state(model_id)


class WindowActionsAdapter(_BoundActions):
    def reopen_install_logs(self) -> None:
        if self._target is not None:
            self._target.reopen_install_logs()

    def close(self) -> None:
        if self._target is not None:
            self._target.close()


class MainPageActionsAdapter(_BoundActions):
    def initialize(self) -> None:
        if self._target is None:
            raise RuntimeError("Main page actions are not bound")
        self._target.initialize()

    def show_settings_category(self, category, *, force=False, subsection=None) -> None:
        if self._target is not None:
            self._target.show_settings_category(
                category,
                force=force,
                subsection=subsection,
            )

    def switch_page(self, page_key: str, *, activate: bool = True) -> None:
        if self._target is not None:
            self._target.switch_page(page_key, activate=activate)

    def is_current(self, page_key: str) -> bool:
        return bool(self._target and self._target.is_current(page_key))

    def show_guide(self) -> None:
        if self._target is not None:
            self._target.show_guide()

    def view_last_context(self) -> None:
        if self._target is not None:
            self._target.view_last_context()

    def refresh_status(self) -> None:
        if self._target is not None:
            self._target.refresh_status()

    def activate_current_page(self) -> bool:
        return bool(self._target and self._target.activate_current_page())

    def open_release_page(self, release_id: str = "") -> None:
        if self._target is not None:
            self._target.open_release_page(release_id)

    def refresh_sidebar_version(self) -> None:
        if self._target is not None:
            self._target.refresh_sidebar_version()

    def refresh_home_news(self) -> None:
        if self._target is not None:
            self._target.refresh_home_news()

    def open_sandbox_debug(self) -> None:
        if self._target is not None:
            self._target.open_sandbox_debug()

    def refresh_debug_info(self) -> None:
        if self._target is not None:
            self._target.refresh_debug_info()

    def insert_debug_message(self, text: str, *, as_user: bool) -> None:
        if self._target is not None:
            self._target.insert_debug_message(text, as_user=as_user)

    def save_debug_snapshot(self) -> None:
        if self._target is not None:
            self._target.save_debug_snapshot()

    def load_debug_snapshot(self) -> None:
        if self._target is not None:
            self._target.load_debug_snapshot()

    def view_debug_context(self, initial_tab: str = "request") -> None:
        if self._target is not None:
            self._target.view_debug_context(initial_tab)

    def build_settings_section(self, category: str, layout) -> None:
        if self._target is not None:
            self._target.build_settings_section(category, layout)

    def sync_settings_mode_widgets(self, mode_value) -> None:
        if self._target is not None:
            self._target.sync_settings_mode_widgets(mode_value)

    def apply_settings_aux_visibility(self) -> None:
        if self._target is not None:
            self._target.apply_settings_aux_visibility()

    def refresh_tester_code(self) -> None:
        if self._target is not None:
            self._target.refresh_tester_code()

    def register_status_indicator(self, attr_name: str, widget) -> None:
        if self._target is not None:
            self._target.register_status_indicator(attr_name, widget)

    def refresh_logs(self) -> None:
        if self._target is not None:
            self._target.refresh_logs()

    def refresh_news(self) -> None:
        if self._target is not None:
            self._target.refresh_news()

    def news_content(self) -> str:
        return self._target.news_content() if self._target is not None else ""

    def news_releases(self) -> list[Any]:
        return self._target.news_releases() if self._target is not None else []

    def refresh_home_primary_label(self) -> None:
        if self._target is not None:
            self._target.refresh_home_primary_label()

    def set_home_progress(self, text, value, maximum, *, busy=False) -> None:
        if self._target is not None:
            self._target.set_home_progress(text, value, maximum, busy=busy)

    def hide_home_progress(self) -> None:
        if self._target is not None:
            self._target.hide_home_progress()

    def run_home_primary_action(self) -> None:
        if self._target is not None:
            self._target.run_home_primary_action()

    def run_home_install_unity(self) -> None:
        if self._target is not None:
            self._target.run_home_install_unity()

    def run_home_verify_action(self) -> None:
        if self._target is not None:
            self._target.run_home_verify_action()

    def show_home_extra_menu(self, anchor_widget) -> None:
        if self._target is not None:
            self._target.show_home_extra_menu(anchor_widget)

    def find_unity_executable(self):
        return self._target.find_unity_executable() if self._target is not None else None