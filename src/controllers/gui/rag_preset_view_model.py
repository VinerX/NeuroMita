from __future__ import annotations

import json
from typing import Any

from handlers.embedding_presets import sync_legacy_settings_to_preset
from managers.rag.install_spec import (
    missing_model_targets,
    start_install,
)
from managers.rag.pipeline.config import (
    RAG_DEFAULTS,
    RAG_PIPELINE_PRESETS,
    get_pipeline_preset_settings,
    list_pipeline_preset_names,
)
from services.contracts import SettingsService
from ui.settings.rag_preset_presentation import (
    ActivateRagPresets,
    ApplyRagPreset,
    ConfirmApplyRagPreset,
    ConfirmDeleteRagPreset,
    DeleteRagPreset,
    InstallMissingRagModels,
    OfferMissingRagModels,
    PromptSaveRagPreset,
    RagPresetShowError,
    RagPresetState,
    RequestApplyRagPreset,
    RequestDeleteRagPreset,
    RequestSaveRagPreset,
    SaveRagPreset,
    SelectRagPreset,
)
from utils import getTranslationVariant as _

from controllers.gui.intent_view_model import IntentViewModel


_USER_PRESETS_KEY = "RAG_PIPELINE_USER_PRESETS"
_SELECTED_PRESET_KEY = "RAG_PIPELINE_PRESET"


class RagPresetViewModel(IntentViewModel[RagPresetState]):
    def __init__(self, settings: SettingsService, parent=None) -> None:
        self._settings = settings
        super().__init__(RagPresetState(), parent)
        try:
            subscription = settings.subscribe(
                self._on_setting_changed,
                keys=(_USER_PRESETS_KEY, _SELECTED_PRESET_KEY),
            )
        except Exception:
            subscription = None
        self.track_subscription(subscription)

    def dispatch(self, intent: Any) -> None:
        if self.is_closed:
            return
        if isinstance(intent, ActivateRagPresets):
            self._refresh_state()
        elif isinstance(intent, SelectRagPreset):
            self._select(intent.name)
        elif isinstance(intent, RequestApplyRagPreset):
            if self.state.can_apply:
                self.emit_effect(ConfirmApplyRagPreset(self.state.selected))
        elif isinstance(intent, ApplyRagPreset):
            self._apply(intent.name, intent.save_current_as)
        elif isinstance(intent, RequestSaveRagPreset):
            self.emit_effect(PromptSaveRagPreset())
        elif isinstance(intent, SaveRagPreset):
            self._save(intent.name)
        elif isinstance(intent, RequestDeleteRagPreset):
            if self.state.can_delete:
                self.emit_effect(ConfirmDeleteRagPreset(self.state.selected))
        elif isinstance(intent, DeleteRagPreset):
            self._delete(intent.name)
        elif isinstance(intent, InstallMissingRagModels):
            self._install_missing(intent.targets)

    def _on_setting_changed(self, _change: Any) -> None:
        self._post_ui(self._refresh_state)

    def _load_user_presets(self) -> dict[str, dict[str, Any]]:
        raw = self._settings.get(_USER_PRESETS_KEY, "{}") or "{}"
        try:
            parsed = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            str(name): dict(values)
            for name, values in parsed.items()
            if str(name).strip() and isinstance(values, dict)
        }

    def _refresh_state(self, selected: str | None = None) -> None:
        user_presets = self._load_user_presets()
        names = tuple(list_pipeline_preset_names(user_presets))
        current = str(
            selected
            if selected is not None
            else self._settings.get(_SELECTED_PRESET_KEY, "Keyword+FTS only")
            or "Custom"
        )
        if current not in names:
            current = "Custom"
        self.set_state(
            RagPresetState(
                names=names,
                selected=current,
                can_apply=current != "Custom",
                can_delete=current not in RAG_PIPELINE_PRESETS and current != "Custom",
                busy=self.state.busy,
            )
        )

    def _select(self, name: str) -> None:
        normalized = str(name or "Custom").strip() or "Custom"
        try:
            self._settings.update(_SELECTED_PRESET_KEY, normalized)
        except Exception as exc:
            self._show_error(exc)
            return
        self._refresh_state(normalized)

    def _snapshot(self) -> dict[str, Any]:
        current = self._settings.snapshot(tuple(RAG_DEFAULTS))
        return {
            key: current.get(key, default)
            for key, default in RAG_DEFAULTS.items()
        }

    def _store_user_presets(self, presets: dict[str, dict[str, Any]]) -> None:
        self._settings.update(
            _USER_PRESETS_KEY,
            json.dumps(presets, ensure_ascii=False),
        )

    def _save(self, name: str, *, select: bool = True) -> bool:
        normalized = str(name or "").strip()
        if not normalized:
            return False
        if normalized in RAG_PIPELINE_PRESETS or normalized == "Custom":
            self.emit_effect(
                RagPresetShowError(
                    _("Ошибка", "Error"),
                    _(
                        "Нельзя перезаписать встроенный пресет «{name}».",
                        "Cannot overwrite built-in preset «{name}».",
                    ).format(name=normalized),
                )
            )
            return False
        try:
            presets = self._load_user_presets()
            presets[normalized] = self._snapshot()
            self._store_user_presets(presets)
            if select:
                self._settings.update(_SELECTED_PRESET_KEY, normalized)
        except Exception as exc:
            self._show_error(exc)
            return False
        self._refresh_state(normalized if select else None)
        return True

    def _apply(self, name: str, save_current_as: str | None) -> None:
        normalized = str(name or "").strip()
        if not normalized or normalized == "Custom":
            return
        if save_current_as is not None and not self._save(save_current_as, select=False):
            return
        settings = get_pipeline_preset_settings(normalized, self._load_user_presets())
        if settings is None:
            self._refresh_state()
            return
        try:
            for key, value in settings.items():
                self._settings.update(str(key), value)
            self._settings.update(_SELECTED_PRESET_KEY, normalized)
            if any(
                key in settings
                for key in (
                    "RAG_EMBED_MODEL",
                    "RAG_EMBED_MODEL_CUSTOM",
                    "RAG_EMBED_QUERY_PREFIX",
                )
            ):
                sync_legacy_settings_to_preset(log_migration=False, force=True)
        except Exception as exc:
            self._show_error(exc)
            return
        self._refresh_state(normalized)
        self.update_state(busy=True)
        self.run_latest(
            "rag-preset-model-status",
            self._missing_model_targets,
            self._on_missing_models,
            self._on_missing_models_error,
        )

    def _delete(self, name: str) -> None:
        normalized = str(name or "").strip()
        if normalized in RAG_PIPELINE_PRESETS or normalized == "Custom":
            return
        try:
            presets = self._load_user_presets()
            presets.pop(normalized, None)
            self._store_user_presets(presets)
            self._settings.update(_SELECTED_PRESET_KEY, "Custom")
        except Exception as exc:
            self._show_error(exc)
            return
        self._refresh_state("Custom")

    def _missing_model_targets(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return missing_model_targets(self._settings)

    def _on_missing_models(
        self,
        missing: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> None:
        self.update_state(busy=False)
        if missing:
            self.emit_effect(OfferMissingRagModels(missing))

    def _on_missing_models_error(self, exc: Exception) -> None:
        self.update_state(busy=False)
        self._show_error(exc)

    def _install_missing(self, targets: tuple[str, ...]) -> None:
        try:
            for target in dict.fromkeys(str(item) for item in targets if str(item).strip()):
                start_install(target, with_ui=True)
        except Exception as exc:
            self._show_error(exc)

    def _show_error(self, exc: Exception) -> None:
        self.emit_effect(
            RagPresetShowError(
                _("Ошибка RAG", "RAG error"),
                str(exc),
            )
        )