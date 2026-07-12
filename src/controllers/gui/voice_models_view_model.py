from __future__ import annotations

from typing import Any, Callable

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import immutable_payload
from ui.windows.voice_model_presentation import (
    CloseVoiceModels,
    InstallVoiceModel,
    OpenVoiceDocumentation,
    RefreshVoiceModels,
    RequestVoiceDescription,
    SaveVoiceSettings,
    UninstallVoiceModel,
    VoiceDescriptionEffect,
    VoiceModelsState,
    VoiceOperationRejectedEffect,
)


class VoiceModelsViewModel(IntentViewModel[VoiceModelsState]):
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], dict[str, Any]],
        install: Callable[[str], bool | None],
        uninstall: Callable[[str], bool | None],
        save: Callable[[dict[str, Any]], None],
        close_view: Callable[[dict[str, Any]], None],
        open_documentation: Callable[[str], None],
        resolve_description: Callable[[str | None], str],
        parent=None,
    ) -> None:
        super().__init__(VoiceModelsState(), parent)
        self._load_snapshot = load_snapshot
        self._install = install
        self._uninstall = uninstall
        self._save = save
        self._close_view = close_view
        self._open_documentation = open_documentation
        self._resolve_description = resolve_description

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, RefreshVoiceModels):
            self.refresh()
            return
        if isinstance(intent, InstallVoiceModel):
            model_id = str(intent.model_id or "").strip()
            if not model_id or self.state.operation is not None:
                self.emit_effect(VoiceOperationRejectedEffect("Voice model operation is already running"))
                return
            self.update_state(
                operation="install",
                operation_model_id=model_id,
                error=None,
            )
            try:
                accepted = self._install(model_id)
                if accepted is False:
                    self.update_state(operation=None, operation_model_id=None)
            except Exception as exc:
                self.update_state(operation=None, operation_model_id=None, error=str(exc))
            return
        if isinstance(intent, UninstallVoiceModel):
            model_id = str(intent.model_id or "").strip()
            if not model_id or self.state.operation is not None:
                self.emit_effect(VoiceOperationRejectedEffect("Voice model operation is already running"))
                return
            self.update_state(
                operation="uninstall",
                operation_model_id=model_id,
                error=None,
            )
            try:
                accepted = self._uninstall(model_id)
                if accepted is False:
                    self.update_state(operation=None, operation_model_id=None)
            except Exception as exc:
                self.update_state(operation=None, operation_model_id=None, error=str(exc))
            return
        if isinstance(intent, SaveVoiceSettings):
            try:
                self._save(dict(intent.values))
            except Exception as exc:
                self.update_state(error=str(exc))
                return
            self.refresh()
            return
        if isinstance(intent, CloseVoiceModels):
            try:
                self._close_view(dict(intent.values))
            except Exception as exc:
                self.update_state(error=str(exc))
            return
        if isinstance(intent, OpenVoiceDocumentation):
            self._open_documentation(str(intent.path))
            return
        if isinstance(intent, RequestVoiceDescription):
            self.emit_effect(
                VoiceDescriptionEffect(self._resolve_description(intent.key))
            )

    def refresh(self) -> None:
        if not self.state.loading:
            self.update_state(loading=True, error=None)
        self.run_coalesced(
            "voice-models-refresh",
            self._load_snapshot,
            self._apply_snapshot,
            self._apply_error,
        )

    def operation_started(self, operation: str, model_id: str) -> None:
        self.update_state(
            operation=str(operation),
            operation_model_id=str(model_id),
            error=None,
        )

    def operation_finished(self, *, success: bool, error: str | None = None) -> None:
        self.update_state(
            operation=None,
            operation_model_id=None,
            error=None if success else str(error or "Voice model operation failed"),
        )
        if success:
            self.refresh()

    def dispatch_description(self, key: str | None) -> None:
        self.emit_effect(
            VoiceDescriptionEffect(self._resolve_description(key))
        )

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        models = tuple(
            immutable_payload(dict(item))
            for item in (snapshot.get("models_data") or ())
        )
        installed = frozenset(str(item) for item in (snapshot.get("installed_models") or ()))
        dependencies = immutable_payload(
            dict(snapshot.get("dependencies_status") or {})
        )
        self.update_state(
            models=models,
            installed_models=installed,
            dependencies_status=dependencies,
            loading=False,
            error=None,
            revision=self.state.revision + 1,
        )

    def _apply_error(self, error: Exception) -> None:
        self.update_state(loading=False, error=str(error))