from __future__ import annotations

from typing import Any, Callable

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import immutable_payload
from ui.windows.asr_glossary_presentation import (
    AsrGlossaryState,
    InstallAsrModel,
    LoadAsrSettings,
    RefreshAsrGlossary,
    SetAsrOption,
)


class AsrGlossaryViewModel(IntentViewModel[AsrGlossaryState]):
    def __init__(
        self,
        *,
        load_catalog: Callable[[bool], list[dict[str, Any]]],
        load_settings: Callable[[str], dict[str, Any]],
        install_model: Callable[[str], None],
        set_option: Callable[[str, str, Any], None],
        parent=None,
    ) -> None:
        super().__init__(AsrGlossaryState(), parent)
        self._load_catalog = load_catalog
        self._load_settings = load_settings
        self._install_model = install_model
        self._set_option = set_option

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, RefreshAsrGlossary):
            self.refresh(force=bool(intent.force))
            return
        if isinstance(intent, LoadAsrSettings):
            self.load_settings(str(intent.engine_id))
            return
        if isinstance(intent, InstallAsrModel):
            engine_id = str(intent.engine_id or "").strip()
            if not engine_id or self.state.installing_model_id is not None:
                return
            self.update_state(
                installing_model_id=engine_id,
                install_progress=None,
                install_status="Preparing...",
                install_error=None,
                install_revision=self.state.install_revision + 1,
            )
            try:
                self._install_model(engine_id)
            except Exception as exc:
                self.install_failed(engine_id, str(exc))
            return
        if isinstance(intent, SetAsrOption):
            try:
                self._set_option(
                    str(intent.engine_id),
                    str(intent.key),
                    intent.value,
                )
            except Exception as exc:
                self.update_state(settings_error=str(exc))

    def refresh(self, *, force: bool = True) -> None:
        if not self.state.loading:
            self.update_state(loading=True, error=None)
        self.run_coalesced(
            "asr-glossary-refresh",
            lambda: self._load_catalog(bool(force)),
            self._apply_catalog,
            lambda error: self.update_state(loading=False, error=str(error)),
        )

    def load_settings(self, engine_id: str) -> None:
        normalized = str(engine_id or "").strip()
        if not normalized:
            return
        self.update_state(
            settings_engine_id=normalized,
            settings_loading=True,
            settings_error=None,
        )
        self.run_latest(
            "asr-glossary-settings",
            lambda: self._load_settings(normalized),
            lambda payload: self._apply_settings(normalized, payload),
            lambda error: self._apply_settings_error(normalized, error),
        )

    def install_progress(
        self,
        engine_id: str,
        progress: int | None,
        status: str,
    ) -> None:
        normalized = str(engine_id or "").strip()
        if not normalized:
            return

        def apply() -> None:
            self.update_state(
                installing_model_id=normalized,
                install_progress=progress,
                install_status=str(status or ""),
                install_error=None,
                install_revision=self.state.install_revision + 1,
            )

        self._post_ui(apply)

    def install_finished(self, engine_id: str) -> None:
        normalized = str(engine_id or "").strip()

        def apply() -> None:
            self.update_state(
                installing_model_id=None,
                install_progress=100,
                install_status="Installed successfully",
                install_error=None,
                install_revision=self.state.install_revision + 1,
            )
            self.refresh(force=True)

        self._post_ui(apply)

    def install_failed(self, engine_id: str, error: str) -> None:
        normalized = str(engine_id or "").strip()

        def apply() -> None:
            self.update_state(
                installing_model_id=None,
                install_progress=None,
                install_status="",
                install_error=str(error or "Install failed"),
                install_revision=self.state.install_revision + 1,
            )

        self._post_ui(apply)

    def _apply_catalog(self, rows: list[dict[str, Any]]) -> None:
        self.update_state(
            models=tuple(immutable_payload(dict(row)) for row in (rows or ())),
            loading=False,
            error=None,
            catalog_revision=self.state.catalog_revision + 1,
        )

    def _apply_settings(self, engine_id: str, payload: dict[str, Any]) -> None:
        if self.state.settings_engine_id != engine_id:
            return
        self.update_state(
            settings_schema=tuple(
                immutable_payload(dict(item))
                for item in (payload.get("schema") or ())
            ),
            settings_values=immutable_payload(dict(payload.get("values") or {})),
            settings_loading=False,
            settings_error=None,
            settings_revision=self.state.settings_revision + 1,
        )

    def _apply_settings_error(self, engine_id: str, error: Exception) -> None:
        if self.state.settings_engine_id != engine_id:
            return
        self.update_state(
            settings_schema=(),
            settings_values=immutable_payload({}),
            settings_loading=False,
            settings_error=str(error),
            settings_revision=self.state.settings_revision + 1,
        )