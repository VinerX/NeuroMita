from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QTimer

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import immutable_payload, mutable_payload
from controllers.gui.presentation_contracts import UiSettingsDataKey, UiTopic
from ui.settings.embed_provider_presentation import (
    ActivateEmbedProvider,
    AddEmbedPreset,
    DeleteEmbedPreset,
    DownloadEmbedModel,
    EmbedProviderShowError,
    EmbedProviderState,
    RefreshEmbedPresets,
    ReorderEmbedPresets,
    SaveEmbedPreset,
    SelectEmbedPreset,
    TestEmbedPreset,
)
from utils import getTranslationVariant as _


class EmbedProviderViewModel(IntentViewModel[EmbedProviderState]):
    def __init__(self, *, host: Any, presentation: Any, parent=None) -> None:
        super().__init__(EmbedProviderState(), parent)
        self._host = host
        self._presentation = presentation
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(self._test_timed_out)
        self.track_subscription(
            presentation.events.subscribe(
                UiTopic.EMBEDDING_PRESET_TEST_RESULT,
                self._on_test_result,
                weak=False,
            )
        )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ActivateEmbedProvider):
            selected = intent.selected_preset_id
            if selected is None:
                selected = self._presentation.settings.get(
                    "RAG_EMBED_PRESET_ID", "local_hf"
                )
            self.refresh_presets(selected, force=False)
            return
        if isinstance(intent, RefreshEmbedPresets):
            self.refresh_presets(intent.selected_preset_id, force=intent.force)
            return
        if isinstance(intent, SelectEmbedPreset):
            self.select_preset(intent.preset_id)
            return
        if isinstance(intent, SaveEmbedPreset):
            self.save_preset(intent.payload, intent.hf_token)
            return
        if isinstance(intent, AddEmbedPreset):
            self.add_preset(intent.name)
            return
        if isinstance(intent, DeleteEmbedPreset):
            self.delete_preset(intent.preset_id)
            return
        if isinstance(intent, ReorderEmbedPresets):
            self.reorder_presets(intent.custom_ids)
            return
        if isinstance(intent, TestEmbedPreset):
            self.test_preset(intent.preset_id)
            return
        if isinstance(intent, DownloadEmbedModel):
            self.download_model(intent.payload, intent.hf_token)

    def refresh_presets(self, selected: Any = None, *, force: bool) -> None:
        target = selected if selected is not None else self.state.selected_preset_id
        self.update_state(loading_presets=True, error=None)

        def worker() -> tuple[tuple[str, Any], ...]:
            meta = self._presentation.embeddings.list_meta()
            items = self._presentation.settings_data.embed_preset_items_from_meta(meta)
            return tuple((str(label), item_id) for label, item_id in items)

        def applied(items: tuple[tuple[str, Any], ...]) -> None:
            chosen = target
            ids = tuple(item_id for _label, item_id in items)
            if chosen not in ids:
                chosen = ids[0] if ids else None
            self.update_state(
                preset_items=items,
                selected_preset_id=chosen,
                loading_presets=False,
                items_revision=self.state.items_revision + 1,
                error=None,
            )
            if chosen is not None:
                self.select_preset(chosen)
            else:
                self.update_state(
                    config=None,
                    downloaded=False,
                    loading_config=False,
                    status_text="",
                    status_kind="normal",
                    config_revision=self.state.config_revision + 1,
                )

        def failed(error: Exception) -> None:
            cached = self._presentation.settings_data.get(
                UiSettingsDataKey.EMBED_PRESET_ITEMS, ()
            )
            items = tuple((str(label), item_id) for label, item_id in (cached or ()))
            self.update_state(
                preset_items=items,
                loading_presets=False,
                error=str(error),
                items_revision=self.state.items_revision + 1,
            )

        if not force:
            cached = self._presentation.settings_data.get(
                UiSettingsDataKey.EMBED_PRESET_ITEMS, None
            )
            if cached is not None:
                applied(tuple((str(label), item_id) for label, item_id in cached))
                return
        self.run_coalesced("embed-provider-presets", worker, applied, failed)

    def select_preset(self, preset_id: Any) -> None:
        if self.state.testing and preset_id != self.state.testing_preset_id:
            self._test_timer.stop()
        self.update_state(
            selected_preset_id=preset_id,
            loading_config=True,
            testing=False,
            testing_preset_id=None,
            status_text=_("Загрузка пресета...", "Loading preset..."),
            status_kind="normal",
            error=None,
        )

        def worker() -> dict[str, Any] | None:
            cfg = self._fetch_config(preset_id)
            if not cfg:
                return None
            payload = dict(cfg)
            provider = str(payload.get("provider_name") or "local")
            if provider == "local":
                payload["known_models"] = list(
                    self._presentation.embeddings.local_model_names()
                )
            payload["hf_token"] = str(
                self._presentation.settings.get("HF_TOKEN", "") or ""
            )
            payload["downloaded"] = bool(
                self._presentation.rag.is_embed_model_downloaded()
            )
            payload["index_status"] = str(
                self._presentation.rag.embed_status_text() or ""
            )
            return payload

        def applied(cfg: dict[str, Any] | None) -> None:
            if cfg is None:
                self.update_state(
                    loading_config=False,
                    error=_("Пресет не найден", "Preset not found"),
                    status_kind="error",
                )
                return
            self._presentation.settings.set("RAG_EMBED_PRESET_ID", preset_id)
            self.update_state(
                selected_preset_id=preset_id,
                config=immutable_payload(cfg),
                downloaded=bool(cfg.get("downloaded")),
                loading_config=False,
                status_text=str(cfg.get("index_status") or ""),
                status_kind="normal",
                error=None,
                config_revision=self.state.config_revision + 1,
            )

        self.run_latest(
            "embed-provider-config",
            worker,
            applied,
            lambda error: self.update_state(
                loading_config=False,
                error=str(error),
                status_text=_("Ошибка: ", "Error: ") + str(error),
                status_kind="error",
            ),
        )

    def save_preset(self, payload: Any, hf_token: str) -> None:
        if self.state.operation is not None:
            return
        data = dict(mutable_payload(payload) or {})
        self.update_state(
            operation="save",
            status_text=_("Сохранение...", "Saving..."),
            status_kind="normal",
            error=None,
        )

        def worker() -> Any:
            self._presentation.settings.set("HF_TOKEN", str(hf_token or ""))
            return self._presentation.embeddings.save(data)

        def applied(saved_id: Any) -> None:
            self.update_state(
                operation=None,
                status_text=_("Сохранено", "Saved"),
                status_kind="success",
            )
            if saved_id is not None:
                self._presentation.settings.set("RAG_EMBED_PRESET_ID", saved_id)
                self.refresh_presets(saved_id, force=True)

        self.run_exclusive(
            "embed-provider-save",
            worker,
            applied,
            self._operation_failed,
        )

    def add_preset(self, name: str) -> None:
        if self.state.operation is not None:
            return
        name = str(name or "").strip()
        if not name:
            return
        payload = {
            "id": None,
            "name": name,
            "provider_name": "local",
            "model": "",
            "url": "",
            "key": "",
            "reserve_keys": [],
            "query_prefix": "",
        }
        self.update_state(operation="add", error=None)
        self.run_exclusive(
            "embed-provider-add",
            lambda: self._presentation.embeddings.save(payload),
            lambda new_id: self._finish_mutation(new_id),
            self._operation_failed,
        )

    def delete_preset(self, preset_id: Any) -> None:
        if self.state.operation is not None:
            return
        if preset_id is None or isinstance(preset_id, str):
            return
        self.update_state(operation="delete", error=None)
        self.run_exclusive(
            "embed-provider-delete",
            lambda: self._presentation.embeddings.delete(preset_id),
            lambda _ok: self._finish_mutation(None),
            self._operation_failed,
        )

    def reorder_presets(self, custom_ids: tuple[Any, ...]) -> None:
        if self.state.operation is not None:
            return
        self.update_state(operation="reorder", error=None)
        selected = self.state.selected_preset_id
        self.run_exclusive(
            "embed-provider-reorder",
            lambda: self._presentation.embeddings.reorder(list(custom_ids)),
            lambda _ok: self._finish_mutation(selected),
            self._operation_failed,
        )

    def test_preset(self, preset_id: Any) -> None:
        if preset_id is None or self.state.testing:
            return
        self.update_state(
            testing=True,
            testing_preset_id=preset_id,
            status_text=_("Тестирование...", "Testing..."),
            status_kind="normal",
            error=None,
        )
        try:
            self._presentation.events.publish(
                UiTopic.EMBEDDING_PRESET_TEST, {"id": preset_id}
            )
        except Exception as exc:
            self.update_state(
                testing=False,
                testing_preset_id=None,
                status_text=_("Ошибка: ", "Error: ") + str(exc),
                status_kind="error",
                error=str(exc),
            )
            return
        self._test_timer.start(30_000)

    def download_model(self, payload: Any, hf_token: str) -> None:
        if self.state.operation is not None:
            return
        data = dict(mutable_payload(payload) or {})
        self.update_state(operation="download", error=None)

        def worker() -> Any:
            self._presentation.settings.set("HF_TOKEN", str(hf_token or ""))
            return self._presentation.embeddings.save(data)

        def applied(saved_id: Any) -> None:
            self.update_state(operation=None)
            self._presentation.rag.download_embed_model()
            self.refresh_presets(
                saved_id if saved_id is not None else self.state.selected_preset_id,
                force=True,
            )

        self.run_exclusive(
            "embed-provider-download",
            worker,
            applied,
            self._operation_failed,
        )

    def _finish_mutation(self, selected: Any) -> None:
        self.update_state(operation=None)
        self.refresh_presets(selected, force=True)

    def _operation_failed(self, error: Exception) -> None:
        self.update_state(
            operation=None,
            error=str(error),
            status_text=_("Ошибка: ", "Error: ") + str(error),
            status_kind="error",
        )
        self.emit_effect(EmbedProviderShowError(str(error)))

    def _on_test_result(self, event: Any) -> None:
        data = dict(getattr(event, "data", None) or {})
        self._post_ui(lambda: self._apply_test_result(data))

    def _apply_test_result(self, data: dict[str, Any]) -> None:
        if data.get("id") != self.state.testing_preset_id:
            return
        self._test_timer.stop()
        success = bool(data.get("success"))
        marker = "✓ " if success else "✗ "
        message = str(data.get("message") or ("OK" if success else "Error"))
        self.update_state(
            testing=False,
            testing_preset_id=None,
            status_text=marker + message,
            status_kind="success" if success else "error",
        )

    def _test_timed_out(self) -> None:
        if self.state.testing:
            self.update_state(
                testing=False,
                testing_preset_id=None,
                status_text=_("Тест не ответил", "Test timed out"),
                status_kind="error",
            )

    def _fetch_config(self, preset_id: Any) -> dict[str, Any] | None:
        try:
            cfg = self._presentation.embeddings.get_full(preset_id)
            if isinstance(cfg, dict) and cfg:
                return dict(cfg)
        except Exception:
            pass
        try:
            from presets.embedding_provider_presets import get_builtin_preset

            builtin = get_builtin_preset(str(preset_id))
            if not builtin:
                return None
            provider = builtin["provider"]
            model = builtin["default_model"]
            return {
                "id": builtin["id"],
                "name": builtin["name"],
                "provider_name": provider,
                "model": model,
                "hf_name": model if provider == "local" else "",
                "api_url": builtin.get("default_url") or "",
                "api_key": None,
                "reserve_keys": [],
                "headers": dict(builtin.get("default_headers") or {}),
                "query_prefix": "",
                "dimensions": int(builtin.get("default_dimensions") or 0),
                "extra": dict(builtin.get("default_extra") or {}),
                "key_url": builtin.get("key_url") or "",
                "known_models": list(builtin.get("known_models") or []),
                "is_builtin": True,
            }
        except Exception:
            return None
