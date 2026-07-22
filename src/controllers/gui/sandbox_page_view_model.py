from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from controllers.gui.sandbox_page_controller import SandboxPageController
from core.events import Events, get_event_bus
from main_logger import logger
from services.contracts import SettingsService
from core.services import use
from ui.pages.sandbox_presentation import (
    SandboxActivated,
    SandboxBudgetState,
    SandboxCharacterSelected,
    SandboxClearHistoryRequested,
    SandboxHistoryCleared,
    SandboxLastRequestState,
    SandboxMemoryState,
    SandboxModelItem,
    SandboxModelSelected,
    SandboxOpenHistory,
    SandboxOpenHistoryRequested,
    SandboxPromptSelected,
    SandboxRefreshRequested,
    SandboxRefreshVoicePanelsRequested,
    SandboxSettingChanged,
    SandboxShowError,
    SandboxState,
    SandboxStatusState,
)


class SandboxPageViewModel(IntentViewModel[SandboxState]):
    """Owns Sandbox presentation state, refreshes and backend subscriptions."""

    _MEMORY_SETTING_KEYS = frozenset({"MODEL_MESSAGE_LIMIT", "MEMORY_CAPACITY"})
    _BUDGET_SETTING_KEYS = frozenset({"MAX_MODEL_TOKENS"})
    _STATUS_SETTING_KEYS = frozenset(
        {
            "USE_VOICEOVER",
            "VOICEOVER_METHOD",
            "LOCAL_VOICE_MODEL_ID",
            "NM_CURRENT_VOICEOVER",
            "MIC_ACTIVE",
            "RECOGNIZER_TYPE",
            "RAG_ENABLED",
            "RAG_PIPELINE_PRESET",
            "RAG_VECTOR_SEARCH_ENABLED",
            "RAG_EMBED_PRESET_ID",
            "RAG_EMBED_MODEL",
            "MEMORY_PROFILE",
        }
    )

    def __init__(
        self,
        *,
        host: Any,
        controller: SandboxPageController | None = None,
        parent=None,
    ) -> None:
        self._host = host
        self._controller = controller or SandboxPageController()
        self._settings = use(SettingsService)
        initial_settings = self._controller.settings_snapshot()
        super().__init__(
            SandboxState(settings=self._freeze_mapping(initial_settings)),
            parent,
        )
        self._request_started_at: float | None = None

        bus = get_event_bus()
        for event_name, callback in (
            (Events.Model.ON_STARTED_RESPONSE_GENERATION, self._on_model_started),
            (Events.Model.ON_SUCCESSFUL_RESPONSE, self._on_model_succeeded),
            (Events.Model.ON_FAILED_RESPONSE, self._on_model_failed),
            (Events.GUI.UPDATE_TOKEN_COUNT_UI, self._on_token_count_changed),
            (Events.GUI.SET_SETTINGS_ICON_INDICATOR, self._on_indicator_changed),
            (Events.GUI.UPDATE_STATUS_COLORS, self._on_status_changed),
            (Events.Install.TASK_FINISHED, self._on_install_finished),
            (Events.VoiceModel.MODEL_INSTALL_FINISHED, self._on_install_finished),
            (Events.History.COMPRESSED, self._on_history_changed),
            (Events.Character.CURRENT_CHANGED, self._on_character_changed),
            (Events.Character.RELOAD_DATA, self._on_character_changed),
            (Events.ApiPresets.PRESET_SAVED, self._on_presets_changed),
            (Events.ApiPresets.PRESET_DELETED, self._on_presets_changed),
            (Events.ApiPresets.PRESET_IMPORTED, self._on_presets_changed),
        ):
            self.track_subscription(bus.subscribe(event_name, callback, weak=False))

        self.track_subscription(self._settings.subscribe(self._on_setting_changed))

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, SandboxActivated):
            self.refresh_all()
            return
        if isinstance(intent, SandboxRefreshRequested):
            self._refresh_section(intent.section)
            return
        if isinstance(intent, SandboxModelSelected):
            self._select_model(intent.preset_id)
            return
        if isinstance(intent, SandboxPromptSelected):
            self._select_prompt(intent.prompt_set)
            return
        if isinstance(intent, SandboxCharacterSelected):
            self._select_character(intent.character_id, intent.reload_data)
            return
        if isinstance(intent, SandboxSettingChanged):
            self._set_setting(intent.key, intent.value)
            return
        if isinstance(intent, SandboxClearHistoryRequested):
            self._clear_history()
            return
        if isinstance(intent, SandboxOpenHistoryRequested):
            cid = str(intent.character_id or self.state.current_character_id).strip()
            if cid:
                try:
                    self._controller.open_history(self._host, cid)
                except Exception as exc:
                    self.emit_effect(SandboxShowError("History", str(exc)))
            return
        if isinstance(intent, SandboxRefreshVoicePanelsRequested):
            self._controller.refresh_voice_panels()
            self.refresh_status()

    def game_link_connected(self) -> bool:
        """Живое состояние TCP-связи с модом — для начального заполнения строки
        «Связь с игрой» (дальше её двигает update_status_colors). Живёт здесь,
        а не во view: view пассивна и не ходит в сервисы."""
        try:
            from core.services import services
            from services.contracts import GameLinkService

            svc = services().get_optional(GameLinkService)
            return bool(svc.is_connected()) if svc is not None else False
        except Exception:
            return False

    def refresh_all(self) -> None:
        self.refresh_selectors()
        self.refresh_status()
        self.refresh_memory()
        self.refresh_budget()

    def refresh_selectors(self) -> None:
        self._update(selectors_loading=True, error=None)

        def worker() -> dict[str, Any]:
            meta, current_model_id = self._controller.model_snapshot()
            characters, current_character = self._controller.character_snapshot()
            character_id, prompts, current_prompt = self._controller.prompt_snapshot(
                current_character
            )
            model_items: list[SandboxModelItem] = []
            for preset in list((meta or {}).get("custom", []) or []):
                preset_id = getattr(preset, "id", None)
                if preset_id is None:
                    continue
                name = str(getattr(preset, "name", "") or "")
                model = str(getattr(preset, "default_model", "") or "")
                label = f"{name} ({model})" if model else name
                model_items.append(SandboxModelItem(int(preset_id), label))
            return {
                "model_items": tuple(model_items),
                "current_model_id": (
                    int(current_model_id) if current_model_id is not None else None
                ),
                "character_items": tuple(str(item) for item in characters),
                "current_character_id": str(character_id or current_character or ""),
                "prompt_items": tuple(str(item) for item in prompts),
                "current_prompt": str(current_prompt or ""),
            }

        def applied(payload: dict[str, Any]) -> None:
            self._update(selectors_loading=False, error=None, **payload)

        def failed(error: Exception) -> None:
            self._update(selectors_loading=False, error=str(error))
            self.emit_effect(SandboxShowError("Sandbox", str(error)))

        self.run_coalesced("sandbox-selectors", worker, applied, failed)

    def refresh_status(self) -> None:
        def worker() -> tuple[dict[str, Any], dict[str, str]]:
            return self._controller.settings_snapshot(), self._controller.rag_status()

        def applied(payload: tuple[dict[str, Any], dict[str, str]]) -> None:
            settings, rag = payload
            status = replace(
                self.state.status,
                rag_preset_name=str(rag.get("preset_name") or "Custom"),
                rag_model_name=str(rag.get("model_name") or ""),
            )
            self._update(settings=self._freeze_mapping(settings), status=status)

        self.run_coalesced("sandbox-status", worker, applied, self._report_refresh_error)

    def refresh_memory(self) -> None:
        settings = dict(self.state.settings)
        message_limit = int(settings.get("MODEL_MESSAGE_LIMIT", 35) or 35)
        memory_limit = int(settings.get("MEMORY_CAPACITY", 50) or 50)
        self._update(memory=replace(self.state.memory, loading=True))

        def worker() -> dict[str, Any]:
            return self._controller.memory_summary(
                message_limit=message_limit,
                memory_limit=memory_limit,
            )

        def applied(raw: dict[str, Any]) -> None:
            effective = raw.get("effective_history")
            memory = SandboxMemoryState(
                messages=self._format_count(
                    effective if effective is not None else raw.get("history_active"),
                    message_limit,
                ),
                memories=self._format_count(raw.get("memories_active"), memory_limit),
                forgotten=self._format_count(raw.get("memories_forgotten")),
                missing=self._format_pair(
                    raw.get("missing_history"), raw.get("missing_memory")
                ),
                trash=self._format_pair(
                    raw.get("history_deleted"), raw.get("memories_deleted")
                ),
                last=self._format_timestamp(raw.get("last_activity")),
                db_size=self._format_bytes(raw.get("db_size_bytes")),
                loading=False,
            )
            self._update(memory=memory)

        def failed(error: Exception) -> None:
            self._update(memory=replace(self.state.memory, loading=False), error=str(error))

        self.run_coalesced("sandbox-memory", worker, applied, failed)

    def refresh_budget(self) -> None:
        self._update(budget=replace(self.state.budget, loading=True))

        def worker() -> SandboxBudgetState:
            settings = self._controller.settings_snapshot(("MAX_MODEL_TOKENS",))
            stats = self._controller.token_stats()
            maximum = max(1, int(settings.get("MAX_MODEL_TOKENS", 32000) or 32000))
            cost = stats.get("estimated_input_cost")
            return SandboxBudgetState(
                used=int(stats.get("estimated_context_tokens") or 0),
                maximum=maximum,
                estimated_cost=float(cost) if cost is not None else 0.0,
                loading=False,
            )

        self.run_coalesced(
            "sandbox-budget",
            worker,
            lambda value: self._update(budget=value),
            lambda error: self._update(
                budget=replace(self.state.budget, loading=False), error=str(error)
            ),
        )

    def _refresh_section(self, section: str) -> None:
        normalized = str(section or "all").strip().lower()
        if normalized in ("all", "selectors"):
            self.refresh_selectors()
        if normalized in ("all", "status"):
            self.refresh_status()
        if normalized in ("all", "memory"):
            self.refresh_memory()
        if normalized in ("all", "budget"):
            self.refresh_budget()

    def _select_model(self, preset_id: int) -> None:
        try:
            self._controller.select_model(int(preset_id))
        except Exception as exc:
            self.emit_effect(SandboxShowError("Model", str(exc)))
            return
        self._update(current_model_id=int(preset_id))
        self.refresh_budget()
        # Смена модели меняет окно контекста и цену → пересчитать счётчик под
        # чатом (иначе он держит окно/оценку прошлой модели, напр. 32к).
        get_event_bus().emit(Events.GUI.UPDATE_TOKEN_COUNT)

    def _select_prompt(self, prompt_set: str) -> None:
        try:
            self._controller.select_prompt(self.state.current_character_id, prompt_set)
        except Exception as exc:
            self.emit_effect(SandboxShowError("Prompt", str(exc)))
            return
        self._update(current_prompt=str(prompt_set))

    def _select_character(self, character_id: str, reload_data: bool) -> None:
        cid = str(character_id or "").strip()
        if not cid:
            return
        try:
            self._controller.select_character(cid, reload_data=reload_data)
        except Exception as exc:
            self.emit_effect(SandboxShowError("Character", str(exc)))
            return
        self._update(current_character_id=cid, prompt_items=(), current_prompt="")
        self.refresh_selectors()
        self.refresh_memory()

    def _set_setting(self, key: str, value: Any) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        current = dict(self.state.settings)
        missing = object()
        previous = current.get(normalized, missing)
        current[normalized] = value
        self._update(settings=self._freeze_mapping(current))
        try:
            self._controller.update_setting(normalized, value)
        except Exception as exc:
            if previous is missing:
                current.pop(normalized, None)
            else:
                current[normalized] = previous
            self._update(settings=self._freeze_mapping(current), error=str(exc))
            self.emit_effect(SandboxShowError("Settings", str(exc)))

    def _clear_history(self) -> None:
        try:
            self._controller.clear_current_history()
        except Exception as exc:
            self.emit_effect(SandboxShowError("History", str(exc)))
            return
        self.emit_effect(SandboxHistoryCleared())
        self.refresh_memory()

    def _on_setting_changed(self, change: Any) -> None:
        key = str(getattr(change, "key", "") or "")
        value = getattr(change, "value", None)
        if not key:
            return

        def apply() -> None:
            if self.is_closed:
                return
            settings = dict(self.state.settings)
            settings[key] = value
            self._update(settings=self._freeze_mapping(settings))
            if key in self._STATUS_SETTING_KEYS:
                self.refresh_status()
            if key in self._MEMORY_SETTING_KEYS:
                self.refresh_memory()
            if key in self._BUDGET_SETTING_KEYS:
                self.refresh_budget()
            if key.startswith("PROMPT_SET_"):
                self.refresh_selectors()

        self._post_ui(apply)

    def _on_model_started(self, event: Any) -> None:
        self._request_started_at = time.perf_counter()
        self._post_ui(
            lambda: self._update(
                last_request=replace(
                    self.state.last_request,
                    status="running",
                    error="",
                    model_name=self._controller.current_model_name(),
                )
            )
        )

    def _on_model_succeeded(self, event: Any) -> None:
        self._finish_model_request(True, "")

    def _on_model_failed(self, event: Any) -> None:
        data = getattr(event, "data", None) or {}
        self._finish_model_request(False, str(data.get("error") or ""))

    def _finish_model_request(self, ok: bool, error: str) -> None:
        started = self._request_started_at
        latency = time.perf_counter() - started if started is not None else None
        self._request_started_at = None

        def apply() -> None:
            self._update(
                last_request=replace(
                    self.state.last_request,
                    status="success" if ok else "error",
                    error=str(error or ""),
                    latency_seconds=latency,
                    model_name=self._controller.current_model_name(),
                    finished_at=time.strftime("%H:%M:%S"),
                )
            )
            self.refresh_budget()
            self.refresh_memory()

        self._post_ui(apply)

    def _on_token_count_changed(self, event: Any) -> None:
        self._post_ui(self.refresh_budget)

    def _on_indicator_changed(self, event: Any) -> None:
        data = getattr(event, "data", None) or {}
        category = str(data.get("category") or "")
        indicator = data.get("state")

        def apply() -> None:
            indicators = dict(self.state.status.indicators)
            indicators[category] = indicator
            self._update(
                status=replace(
                    self.state.status,
                    indicators=tuple(sorted(indicators.items())),
                )
            )

        self._post_ui(apply)

    def _on_status_changed(self, event: Any) -> None:
        self._post_ui(self.refresh_status)

    def _on_install_finished(self, event: Any) -> None:
        self._post_ui(lambda: (self._controller.refresh_voice_panels(), self.refresh_status()))

    def _on_history_changed(self, event: Any) -> None:
        self._post_ui(self.refresh_memory)

    def _on_character_changed(self, event: Any) -> None:
        self._post_ui(lambda: (self.refresh_selectors(), self.refresh_memory()))

    def _on_presets_changed(self, event: Any) -> None:
        self._post_ui(self.refresh_selectors)

    def _report_refresh_error(self, error: Exception) -> None:
        logger.debug("Sandbox refresh failed: %s", error, exc_info=True)
        self._update(error=str(error))

    def _update(self, **changes: Any) -> None:
        changes.setdefault("revision", self.state.revision + 1)
        self.update_state(**changes)

    @staticmethod
    def _freeze_mapping(values: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
        return tuple(sorted((str(key), value) for key, value in values.items()))

    @staticmethod
    def _format_count(value: Any, limit: int | None = None) -> str:
        if value is None:
            return "—"
        return f"{value} / {limit}" if limit is not None else str(value)

    @staticmethod
    def _format_pair(first: Any, second: Any) -> str:
        if first is None and second is None:
            return "—"
        return f"{first or 0} / {second or 0}"

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        text = str(value or "").strip().replace("T", " ")
        if not text:
            return "—"
        parts = text.split(" ", 1)
        date = parts[0]
        tm = parts[1][:5] if len(parts) > 1 else ""
        if "." in date:
            chunks = date.split(".")
            date = ".".join(chunks[:2]) if len(chunks) >= 2 else date
        elif "-" in date:
            chunks = date.split("-")
            date = "-".join(chunks[1:3]) if len(chunks) >= 3 else date
        return f"{date} {tm}".strip()

    @staticmethod
    def _format_bytes(value: Any) -> str:
        try:
            size = float(value or 0)
        except (TypeError, ValueError):
            return "—"
        if size <= 0:
            return "—"
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"