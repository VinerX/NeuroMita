from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from core.events import Event, Events, get_event_bus
from ui.mvvm import immutable_payload, mutable_payload
from ui.windows.ai_hub.helpers import meta_from_row, status_from_row
from ui.windows.ai_hub.settings_presentation import (
    AIHubSettingsChanged,
    AIHubSettingsState,
    AIHubSettingsWarning,
    ApplyAIHubSettingsRows,
    CompileAIHubModel,
    DeleteAIHubModelCompilation,
    ResetAIHubSettings,
    SaveAIHubSettings,
    SelectAIHubSettingsComponent,
)
from utils import getTranslationVariant as _


class AIHubSettingsViewModel(IntentViewModel[AIHubSettingsState]):
    def __init__(self, *, catalog, application, parent=None) -> None:
        super().__init__(AIHubSettingsState(), parent)
        self._catalog = catalog
        self._application = application
        self._category: str | None = None
        bus = get_event_bus()
        self.track_subscription(
            bus.subscribe(Events.VoiceModel.MODEL_COMPILE_STARTED, self._on_compile_started, weak=False)
        )
        self.track_subscription(
            bus.subscribe(Events.VoiceModel.MODEL_COMPILE_FINISHED, self._on_compile_finished, weak=False)
        )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ApplyAIHubSettingsRows):
            self.apply_rows(intent.rows, intent.category)
            return
        if isinstance(intent, SelectAIHubSettingsComponent):
            self.select_component(intent.component_id)
            return
        if isinstance(intent, AIHubSettingsChanged):
            if not self.state.loading and not self.state.saving:
                self.update_state(
                    dirty=True,
                    status_text=_(
                        "Есть несохранённые изменения",
                        "Unsaved changes",
                    ),
                )
            return
        if isinstance(intent, SaveAIHubSettings):
            self.save(intent.values)
            return
        if isinstance(intent, ResetAIHubSettings):
            if self.state.selected_component_id:
                self.select_component(self.state.selected_component_id)
            return
        if isinstance(intent, CompileAIHubModel):
            self._start_compile(clear_only=False)
            return
        if isinstance(intent, DeleteAIHubModelCompilation):
            self._start_compile(clear_only=True)

    def apply_rows(self, rows_payload: Any, category: str | None) -> None:
        rows = list(mutable_payload(rows_payload) or [])
        components: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            meta = meta_from_row(row)
            if category and str(meta.get("category") or "") != str(category):
                continue
            status = status_from_row(row)
            code = str(status.get("code") or "")
            if not (status.get("installed") or status.get("ready") or code in {"installed", "ready"}):
                continue
            component_id = str(meta.get("id") or "").strip()
            if not component_id:
                continue
            components.append((component_id, str(meta.get("title") or component_id)))

        selected = self.state.selected_component_id
        normalized_category = str(category) if category is not None else None
        component_tuple = tuple(components)
        if component_tuple == self.state.components and normalized_category == self._category:
            return
        self._category = normalized_category
        ids = {item[0] for item in components}
        if selected not in ids:
            selected = components[0][0] if components else ""
        self.update_state(
            components=component_tuple,
            selected_component_id=selected,
            components_revision=self.state.components_revision + 1,
            dirty=False,
            status_text="",
        )
        if selected:
            self.select_component(selected)
        else:
            self.update_state(
                schema=(),
                values=(),
                field_errors=(),
                loading=False,
                form_revision=self.state.form_revision + 1,
                compile_available=False,
                compile_cache_exists=False,
                compile_cache_size_bytes=0,
                compile_busy=False,
                compile_revision=self.state.compile_revision + 1,
            )

    def select_component(self, component_id: str) -> None:
        component_id = str(component_id or "").strip()
        if not component_id:
            return
        if self.state.saving:
            self.emit_effect(
                AIHubSettingsWarning(
                    _(
                        "Дождитесь завершения сохранения настроек.",
                        "Wait for the settings save to finish.",
                    )
                )
            )
            return
        self.update_state(
            selected_component_id=component_id,
            loading=True,
            dirty=False,
            status_text=_("Загрузка настроек...", "Loading settings..."),
            field_errors=(),
        )

        def worker() -> dict[str, Any]:
            payload = {
                "schema": list(self._catalog.settings_schema(component_id) or []),
                "values": dict(self._catalog.load_settings(component_id) or {}),
            }
            if self._is_fish_compile_component(component_id):
                payload["compile_status"] = dict(self._catalog.compile_status() or {})
            return payload

        def applied(payload: dict[str, Any]) -> None:
            schema = list(payload.get("schema") or [])
            values = dict(payload.get("values") or {})
            compile_status = dict(payload.get("compile_status") or {})
            self.update_state(
                schema=immutable_payload(schema),
                values=immutable_payload(values),
                loading=False,
                dirty=False,
                status_text="" if schema else _(
                    "У этой модели нет настроек.",
                    "This model has no settings.",
                ),
                form_revision=self.state.form_revision + 1,
                compile_available=self._is_fish_compile_component(component_id),
                compile_cache_exists=bool(compile_status.get("cache_exists")),
                compile_cache_size_bytes=int(compile_status.get("cache_size_bytes") or 0),
                compile_revision=self.state.compile_revision + 1,
            )

        self.run_latest(
            "ai-hub-settings-load",
            worker,
            applied,
            lambda error: self.update_state(
                loading=False,
                status_text=str(error),
            ),
        )

    @staticmethod
    def _is_fish_compile_component(component_id: str) -> bool:
        return str(component_id or "") in {"tts:medium+", "tts:medium+low"}

    def _selected_model_id(self) -> str:
        component_id = str(self.state.selected_component_id or "")
        return component_id.split(":", 1)[1] if ":" in component_id else component_id

    def _start_compile(self, *, clear_only: bool) -> None:
        component_id = self.state.selected_component_id
        if not self._is_fish_compile_component(component_id) or self.state.compile_busy:
            return

        self.update_state(
            compile_busy=True,
            status_text=_("Подготовка backend...", "Preparing backend..."),
        )

        def prepare_backend() -> None:
            future = self._application.ensure_feature_async("installables")
            future.result(timeout=60)

        def start_operation(_result: None) -> None:
            self._application.ensure_optional_gui("install")
            accepted = bool(
                self._catalog.compile_model(component_id, clear_only=clear_only)
            )
            if accepted:
                return
            self.update_state(
                compile_busy=False,
                status_text=_(
                    "Backend подготовлен, но операция была отклонена. Подробности записаны в лог.",
                    "Backend is ready, but the operation was rejected. See the log for details.",
                ),
            )

        def preparation_failed(error: Exception) -> None:
            details = f"{type(error).__name__}: {error}"
            self.update_state(
                compile_busy=False,
                status_text=_(
                    "Не удалось подготовить backend: {details}",
                    "Failed to prepare backend: {details}",
                ).format(details=details),
            )

        started = self.run_exclusive(
            f"ai-hub-compile-prepare:{component_id}",
            prepare_backend,
            start_operation,
            preparation_failed,
        )
        if not started:
            self.update_state(
                compile_busy=False,
                status_text=_(
                    "Подготовка backend уже выполняется",
                    "Backend preparation is already running",
                ),
            )

    def _on_compile_started(self, event: Event) -> None:
        payload = event.data if isinstance(event.data, dict) else {}
        if str(payload.get("model_id") or "") != self._selected_model_id():
            return
        self.update_state(
            compile_busy=True,
            status_text=(
                _("Удаление кеша компиляции...", "Deleting compilation cache...")
                if payload.get("clear_only")
                else _("Компиляция запущена...", "Compilation started...")
            ),
        )

    def _on_compile_finished(self, event: Event) -> None:
        payload = event.data if isinstance(event.data, dict) else {}
        if str(payload.get("model_id") or "") != self._selected_model_id():
            return
        success = bool(payload.get("success"))
        self.update_state(
            compile_busy=False,
            status_text=(
                _("Операция завершена", "Operation completed")
                if success else str(payload.get("error") or _("Ошибка операции", "Operation failed"))
            ),
        )
        self._refresh_compile_status()

    def _refresh_compile_status(self) -> None:
        if not self.state.compile_available:
            return

        def applied(payload: dict[str, Any]) -> None:
            self.update_state(
                compile_cache_exists=bool(payload.get("cache_exists")),
                compile_cache_size_bytes=int(payload.get("cache_size_bytes") or 0),
                compile_revision=self.state.compile_revision + 1,
            )

        self.run_latest(
            "ai-hub-compile-status",
            lambda: dict(self._catalog.compile_status() or {}),
            applied,
            lambda _error: None,
        )

    def save(self, values_payload: Any) -> None:
        component_id = self.state.selected_component_id
        if not component_id or self.state.saving:
            return
        values = dict(mutable_payload(values_payload) or {})
        self.update_state(saving=True, status_text=_("Сохранение...", "Saving..."))

        def applied(result: dict[str, Any]) -> None:
            result = dict(result or {})
            if result.get("ok"):
                self.update_state(
                    values=immutable_payload(values),
                    field_errors=(),
                    saving=False,
                    dirty=False,
                    status_text=_("Сохранено", "Saved"),
                    form_revision=self.state.form_revision + 1,
                    errors_revision=self.state.errors_revision + 1,
                )
                return
            errors = result.get("errors") if isinstance(result.get("errors"), dict) else {}
            global_error = str(errors.get("_") or "")
            field_errors = {str(k): str(v) for k, v in errors.items() if str(k) != "_"}
            self.update_state(
                field_errors=immutable_payload(field_errors),
                saving=False,
                status_text=(
                    global_error
                    or _("Проверьте ошибки", "Check errors")
                ),
                errors_revision=self.state.errors_revision + 1,
            )
            if global_error:
                self.emit_effect(AIHubSettingsWarning(global_error))

        self.run_exclusive(
            "ai-hub-settings-save",
            lambda: dict(self._catalog.save_settings(component_id, values) or {}),
            applied,
            lambda error: self._save_failed(error),
        )

    def _save_failed(self, error: Exception) -> None:
        self.update_state(saving=False, status_text=str(error))
        self.emit_effect(AIHubSettingsWarning(str(error)))
