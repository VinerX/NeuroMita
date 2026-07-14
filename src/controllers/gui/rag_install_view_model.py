from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from core.events import Events, get_event_bus
from managers.rag.install_spec import TARGET_EMBEDDINGS, TARGET_RERANKER
from ui.settings.rag_install_presentation import (
    ActivateRagInstall,
    OpenRagAiHub,
    RagInstallShowError,
    RagInstallState,
    RagInstallTargetState,
    RefreshRagInstall,
)
from utils import getTranslationVariant as _


def resolve_rag_component_id(target: str) -> str:
    """AI Hub показывает модели отдельными карточками — возвращает id карточки
    активной модели цели. Для кастомной модели (нет в пресетах) — пустая строка,
    тогда AI Hub просто откроет категорию RAG."""
    try:
        from managers.rag.model_catalog import spec_for_hf
        from handlers.embedding_presets import resolve_full_config
        from managers.rag.pipeline.config import resolve_ce_model

        if target == TARGET_EMBEDDINGS:
            active_hf = str(resolve_full_config().get("hf_name") or "").strip()
        elif target == TARGET_RERANKER:
            active_hf = str(resolve_ce_model() or "").strip()
        else:
            active_hf = ""
        spec = spec_for_hf(target, active_hf) if active_hf else None
        return str(spec["id"]) if spec else ""
    except Exception:
        return ""


def open_rag_ai_hub(target: str) -> None:
    """Открыть AI Hub на категории RAG с подсветкой карточки активной модели."""
    get_event_bus().emit(
        Events.GUI.SHOW_WINDOW,
        {
            "window_id": "ai_hub",
            "payload": {
                "category": "rag",
                "component_id": resolve_rag_component_id(target),
            },
        },
    )


def _is_rag_install_event(event: Any) -> bool:
    data = getattr(event, "data", None) or {}
    task_id = str(data.get("task_id") or "")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return task_id.startswith("rag:") or meta.get("kind") == "rag"


class RagInstallViewModel(IntentViewModel[RagInstallState]):
    """Статусы установки RAG-бэкендов/моделей и переход в AI Hub."""

    def __init__(self, *, settings_data: Any, parent=None) -> None:
        super().__init__(RagInstallState(), parent)
        self._settings_data = settings_data
        bus = get_event_bus()
        for event_name in (Events.Install.TASK_FINISHED, Events.Install.TASK_FAILED):
            self.track_subscription(
                bus.subscribe(event_name, self._on_install_changed, weak=False)
            )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ActivateRagInstall):
            self.refresh(force=False)
            return
        if isinstance(intent, RefreshRagInstall):
            self.refresh(force=bool(intent.force))
            return
        if isinstance(intent, OpenRagAiHub):
            self._open_ai_hub(str(intent.target))

    def refresh(self, *, force: bool = False) -> None:
        from controllers.gui.settings_data_prefetch import (
            RAG_CE_STATUS,
            RAG_EMBED_STATUS,
            _load_rag_ce_status,
            _load_rag_embed_status,
        )

        self._request(RAG_EMBED_STATUS, _load_rag_embed_status, self._apply_embed, "rag-embed-status", force)
        self._request(RAG_CE_STATUS, _load_rag_ce_status, self._apply_ce, "rag-ce-status", force)

    def _request(self, key, worker, apply, name: str, force: bool) -> None:
        cached = self._settings_data.get(key, None)
        if cached is not None and not force:
            apply(cached)
            return
        self._settings_data.request(self, key, worker, apply, name=name, force=force)

    def _apply_embed(self, status: dict) -> None:
        self.update_state(
            embeddings=RagInstallTargetState(
                backend=str(status.get("backend") or ""),
                index=str(status.get("index") or ""),
                button_visible=bool(status.get("visible")),
                loading=False,
            )
        )

    def _apply_ce(self, status: dict) -> None:
        self.update_state(
            reranker=RagInstallTargetState(
                backend=str(status.get("backend") or ""),
                model=str(status.get("model") or ""),
                loaded=str(status.get("loaded") or ""),
                button_visible=bool(status.get("visible")),
                loading=False,
            )
        )

    def _open_ai_hub(self, target: str) -> None:
        from dataclasses import replace

        if target == TARGET_EMBEDDINGS:
            self.update_state(embeddings=replace(self.state.embeddings, button_busy=True))
        elif target == TARGET_RERANKER:
            self.update_state(reranker=replace(self.state.reranker, button_busy=True))
        try:
            open_rag_ai_hub(target)
        except Exception as exc:
            self.emit_effect(
                RagInstallShowError(
                    _("Ошибка", "Error"),
                    _(
                        "Не удалось открыть AI Hub:\n{e}", "Failed to open AI Hub:\n{e}"
                    ).format(e=exc),
                )
            )
            self.refresh(force=True)

    def _on_install_changed(self, event: Any) -> None:
        if not _is_rag_install_event(event):
            return
        self._post_ui(self._refresh_after_install)

    def _refresh_after_install(self) -> None:
        from controllers.gui.settings_data_prefetch import RAG_CE_STATUS, RAG_EMBED_STATUS

        self._settings_data.clear(RAG_EMBED_STATUS)
        self._settings_data.clear(RAG_CE_STATUS)
        self.refresh(force=True)
