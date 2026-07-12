from __future__ import annotations

import time
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.pages.settings.settings_presentation import (
    PrepareSettingsSection,
    SettingsPageState,
    SettingsSectionFailed,
    SettingsSectionReady,
)


class SettingsPageViewModel(IntentViewModel[SettingsPageState]):
    def __init__(self, *, host: Any, app: Any, settings_data: Any, parent=None) -> None:
        super().__init__(SettingsPageState(), parent)
        self._host = host
        self._app = app
        self._settings_data = settings_data

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, PrepareSettingsSection):
            self._prepare(intent)

    def _prepare(self, intent: PrepareSettingsSection) -> None:
        category = str(intent.category or "").strip()
        if not category:
            return

        loading = set(self.state.loading_sections)
        loading.add(category)
        failures = dict(self.state.failed_sections)
        failures.pop(category, None)
        self.update_state(
            loading_sections=frozenset(loading),
            failed_sections=tuple(sorted(failures.items())),
        )

        def worker() -> None:
            self._settings_data.prefetch_section(self._host, category)
            needs_backend = bool(intent.require_backend or intent.feature_names)
            if needs_backend:
                deadline = time.monotonic() + 6.0
                while not self._app.backend_ready:
                    startup_error = str(self._app.startup_error or "").strip()
                    if startup_error:
                        raise RuntimeError(startup_error)
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Backend is not ready")
                    time.sleep(0.04)

            for feature_name in intent.feature_names:
                future = self._app.ensure_feature_async(str(feature_name))
                future.result(timeout=3600)

            if intent.gui_feature:
                self._app.ensure_optional_gui(str(intent.gui_feature))

        def applied(_result: object) -> None:
            self._finish(category, None)
            self.emit_effect(SettingsSectionReady(category))

        def failed(error: Exception) -> None:
            message = str(error)
            self._finish(category, message)
            self.emit_effect(SettingsSectionFailed(category, message))

        self.run_exclusive(
            f"settings-section:{category}",
            worker,
            applied,
            failed,
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