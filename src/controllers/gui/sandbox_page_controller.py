from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.events import Events, get_event_bus
from core.services import services, use
from handlers.embedding_presets import resolve_full_config
from managers.database_manager import DatabaseManager
from managers.prompt_catalogue_manager import list_prompt_sets
from managers.rag.pipeline.config import RAG_PIPELINE_PRESETS, _b, match_pipeline_preset
from services.contracts import (
    ApiPresetService,
    CharacterRegistry,
    HistoryService,
    ModelStateService,
    SettingsService,
)


class SandboxPageController:
    """Application-facing operations required by the passive Sandbox view."""

    def __init__(self) -> None:
        self._bus = get_event_bus()

    @staticmethod
    def _characters() -> CharacterRegistry:
        return use(CharacterRegistry)

    @staticmethod
    def _api_presets() -> ApiPresetService:
        return use(ApiPresetService)

    @staticmethod
    def _settings() -> SettingsService:
        return use(SettingsService)

    def current_character_id(self) -> str:
        return str(self._characters().current_id() or "")

    def current_character(self):
        return self._characters().current()

    def character_snapshot(self) -> tuple[list[str], str]:
        registry = self._characters()
        ids = [str(item) for item in (registry.all_ids() or ["Crazy"])]
        current = str(registry.current_id() or (ids[0] if ids else ""))
        return ids, current

    def select_character(self, character_id: str, *, reload_data: bool = True) -> None:
        cid = str(character_id or "").strip()
        if not cid:
            return
        self._bus.emit(Events.Character.SET_CURRENT, {"character_id": cid})
        if reload_data:
            self._bus.emit(Events.Character.RELOAD_DATA)

    def clear_current_history(self) -> None:
        self._bus.emit(Events.Character.CLEAR_HISTORY)

    def open_history(self, host: Any, character_id: str) -> None:
        self.select_character(character_id, reload_data=False)
        from controllers.gui.character_settings_logic import open_db_viewer

        open_db_viewer(host, character_id=str(character_id or "").strip() or None)

    def settings_snapshot(self, keys: Iterable[str] | None = None) -> dict[str, Any]:
        return dict(self._settings().snapshot(keys) or {})

    def update_setting(self, key: str, value: Any) -> None:
        self._settings().update(str(key), value)

    def effective_prompt_history_count(self, character, dialog_limit: int) -> int | None:
        if character is None:
            return None
        prepared = use(HistoryService).prepare_for_prompt(
            character=character,
            memory_limit=int(dialog_limit or 0),
            is_game_master=False,
            save_missed_history=False,
            image_quality={},
        )
        return len(prepared.messages)

    def model_snapshot(self) -> tuple[dict[str, Any], int | None]:
        service = services().get_optional(ApiPresetService)
        if service is None:
            return {}, None
        return dict(service.list_meta() or {}), service.current_id()

    def select_model(self, preset_id: int) -> None:
        self._api_presets().set_current(int(preset_id))

    def current_model_name(self) -> str:
        service = self._api_presets()
        current_id = service.current_id()
        for preset in (service.list_meta() or {}).get("custom", []) or []:
            preset_id = getattr(preset, "id", None)
            if preset_id is not None and current_id is not None and int(preset_id) == int(current_id):
                return str(getattr(preset, "name", "") or "")
        return ""

    def prompt_snapshot(self, character_id: str) -> tuple[str, list[str], str]:
        cid = str(character_id or self.current_character_id()).strip()
        try:
            options = [str(item) for item in (list_prompt_sets("Prompts", cid) or [])]
        except Exception:
            options = []
        try:
            current = str(self._settings().get(f"PROMPT_SET_{cid}", "") or "") if cid else ""
        except Exception:
            current = ""
        return cid, options, current

    def select_prompt(self, character_id: str, prompt_set: str) -> None:
        cid = str(character_id or self.current_character_id()).strip()
        if not cid:
            return
        settings = self._settings()
        settings.update(f"PROMPT_SET_{cid}", str(prompt_set))
        settings.save_settings()
        self._bus.emit(Events.Character.RELOAD_DATA)

    def refresh_voice_panels(self) -> None:
        self._bus.emit(Events.GUI.VOICEOVER_REFRESH)
        self._bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)

    def rag_status(self) -> dict[str, str]:
        settings = self._settings()
        try:
            from controllers.gui.rag_memory_controller import _load_user_presets

            user_presets = _load_user_presets() or {}
        except Exception:
            user_presets = {}
        name = str(settings.get("RAG_PIPELINE_PRESET", "Keyword+FTS only") or "").strip()
        known = set(RAG_PIPELINE_PRESETS) | set(user_presets)
        if name in ("", "Custom") or name not in known:
            name = match_pipeline_preset(user_presets) or "Custom"
        model_name = ""
        if _b(settings.get("RAG_VECTOR_SEARCH_ENABLED", False), False):
            config = resolve_full_config() or {}
            model_name = str(
                config.get("model")
                or config.get("hf_name")
                or config.get("db_model_key")
                or ""
            )
        return {"preset_name": name, "model_name": model_name}

    def memory_summary(self, *, message_limit: int, memory_limit: int) -> dict[str, Any]:
        cid = self.current_character_id()
        character = self.current_character()
        db = None
        stats: dict[str, Any] = {}
        try:
            db = DatabaseManager()
            stats = dict(db.get_world_stats(cid) or {})
        except Exception:
            pass
        missing_history = missing_memory = None
        if db is not None and cid:
            try:
                missing_history, missing_memory = db.count_missing_embeddings(cid)
            except Exception:
                pass
        try:
            effective = self.effective_prompt_history_count(character, message_limit)
        except Exception:
            effective = None
        return {
            "effective_history": effective,
            "message_limit": int(message_limit),
            "memory_limit": int(memory_limit),
            "missing_history": missing_history,
            "missing_memory": missing_memory,
            **stats,
        }

    def token_stats(self) -> dict[str, Any]:
        service = services().get_optional(ModelStateService)
        return dict(service.token_stats() or {}) if service is not None else {}
