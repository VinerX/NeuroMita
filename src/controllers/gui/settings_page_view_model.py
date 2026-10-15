from __future__ import annotations
from core.error_utils import format_exception

import time
from collections.abc import Callable
from typing import Any
from main_logger import logger

from controllers.gui.intent_view_model import IntentViewModel
from ui.pages.settings.settings_presentation import (
    PrepareSettingsSection,
    SettingsPageState,
    SettingsSectionFailed,
    SettingsSectionReady,
    SettingsSectionFeaturesReady,
)

class SettingsPageViewModel(IntentViewModel[SettingsPageState]):

    def __init__(
        self,
        *,
        host: Any,
        app: Any,
        settings_data: Any,
        prepare_section: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(SettingsPageState(), parent)
        self._host = host
        self._app = app
        self._settings_data = settings_data
        self._prepare_section = prepare_section

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, PrepareSettingsSection):
            self._prepare(intent)

    def _prepare(self, intent: PrepareSettingsSection) -> None:
        category = str(intent.category or "").strip()
        if not category:
            return
        gui_feature = str(intent.gui_feature or "").strip()

        loading = set(self.state.loading_sections)
        loading.add(category)
        failures = dict(self.state.failed_sections)
        failures.pop(category, None)
        self.update_state(
            loading_sections=frozenset(loading),
            failed_sections=tuple(sorted(failures.items())),
        )

        def worker() -> None:
            started = time.perf_counter()
            if self._prepare_section is not None:
                self._prepare_section(category)
            logger.debug(
                "[Settings UI] %s imports (worker): %.1f ms",
                category,
                (time.perf_counter() - started) * 1000,
            )
            self._settings_data.prefetch_section(self._host, category)
            if gui_feature:
                gui_wait_started = time.perf_counter()
                while not self._app.gui_ready:
                    if self.is_closed:
                        return
                    if self._app.startup_error:
                        raise RuntimeError(self._app.startup_error)
                    time.sleep(0.04)
                logger.debug(
                    "[Settings UI] %s GUI readiness (worker): %.1f ms",
                    category,
                    (time.perf_counter() - gui_wait_started) * 1000,
                )
            needs_backend = bool(
                intent.require_backend
                or (intent.feature_names and not intent.defer_features)
            )
            if needs_backend:
                deadline = time.monotonic() + 6.0
                while not self._app.backend_ready:
                    startup_error = str(self._app.startup_error or "").strip()
                    if startup_error:
                        raise RuntimeError(startup_error)
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Backend is not ready")
                    time.sleep(0.04)

            for feature_name in (() if intent.defer_features else intent.feature_names):
                future = self._app.ensure_feature_async(str(feature_name))
                instance = future.result(timeout=3600)
                if instance is None:
                    raise RuntimeError(
                        f"Runtime feature '{feature_name}' did not become ready"
                    )
            logger.debug(
                "[Settings UI] %s preparation (worker): %.1f ms",
                category,
                (time.perf_counter() - started) * 1000,
            )

        def failed(error: Exception) -> None:
            message = format_exception(error)
            self._finish(category, message)
            self.emit_effect(SettingsSectionFailed(category, message))

        def applied(_result: object) -> None:
            started = time.perf_counter()
            try:
                # Backend feature creation is intentionally performed by the
                # worker above. Optional GUI controllers may construct
                # QObject/QWidget/QTimer instances and therefore must only be
                # created while this callback is running on the Qt thread.
                if gui_feature:
                    self._app.ensure_optional_gui(gui_feature)
                logger.debug(
                    "[Settings UI] %s controllers (Qt): %.1f ms",
                    category,
                    (time.perf_counter() - started) * 1000,
                )
            except Exception as exc:
                failed(exc)
                return
            self._finish(category, None)
            if intent.defer_features and intent.feature_names:
                self.update_state(
                    preparing_features=self.state.preparing_features | {category},
                )
            self.emit_effect(SettingsSectionReady(category))
            if intent.defer_features and intent.feature_names:
                self._prepare_features(category, intent.feature_names)

        self.run_exclusive(
            f"settings-section:{category}",
            worker,
            applied,
            failed,
        )

    def _prepare_features(self, category: str, feature_names: tuple[str, ...]) -> None:
        def worker():
            started = time.perf_counter()
            deadline = time.monotonic() + 6.0
            while not self._app.backend_ready:
                if self._app.startup_error:
                    raise RuntimeError(self._app.startup_error)
                if time.monotonic() >= deadline:
                    raise RuntimeError("Backend is not ready")
                time.sleep(0.04)
            for feature_name in feature_names:
                feature_started = time.perf_counter()
                if (
                    self._app.ensure_feature_async(feature_name).result(timeout=3600)
                    is None
                ):
                    raise RuntimeError(
                        f"Runtime feature '{feature_name}' did not become ready"
                    )
                logger.debug(
                    "[Settings UI] %s feature %s (worker): %.1f ms",
                    category,
                    feature_name,
                    (time.perf_counter() - feature_started) * 1000,
                )
            logger.debug(
                "[Settings UI] %s deferred features (worker): %.1f ms",
                category,
                (time.perf_counter() - started) * 1000,
            )

        def finished(error: Exception | None):
            failures = dict(self.state.feature_errors)
            if error is None:
                failures.pop(category, None)
            else:
                failures[category] = format_exception(error)
                logger.warning(
                    "Settings section '%s' runtime preparation failed: %s",
                    category,
                    failures[category],
                )
            self.update_state(
                preparing_features=self.state.preparing_features - {category},
                feature_errors=tuple(sorted(failures.items())),
            )
            if error is None:
                self.emit_effect(SettingsSectionFeaturesReady(category))

        self.run_exclusive(
            f"settings-features:{category}",
            worker,
            lambda _result: finished(None),
            finished,
        )

    def _finish(self, category: str, error: str | None) -> None:
        loading = set(self.state.loading_sections)
        loading.discard(category)
        failures = dict(self.state.failed_sections)
        if error:
            failures[category] = error
        else:
            failures.pop(category, None)
        self.update_state(
            loading_sections=frozenset(loading),
            failed_sections=tuple(sorted(failures.items())),
        )
