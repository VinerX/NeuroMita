from __future__ import annotations

from threading import RLock
from typing import Any, Callable


from core.events import Events, get_event_bus
from core.services import use
from services.contracts import ApiPresetService, CharacterRegistry, EmbeddingPresetService
from main_logger import logger
from controllers.gui.async_runner import dispatch_to_gui, run_async
from utils import getTranslationVariant as _


API_PROVIDER_NAMES = "api_provider_names"
CAMERA_LIST = "camera_list"
CHARACTER_SETTINGS_SNAPSHOT = "character_settings_snapshot"
EMBED_PRESET_ITEMS = "embed_preset_items"
RAG_CE_STATUS = "rag_ce_status"
RAG_EMBED_STATUS = "rag_embed_status"


Callback = Callable[[Any], None]
ErrorCallback = Callable[[Exception], None]
Worker = Callable[[], Any]


class SettingsDataCache:
    def __init__(self) -> None:
        self._lock = RLock()
        self._values: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}
        self._loading: set[str] = set()
        self._callbacks: dict[str, list[tuple[Any, Callback | None, ErrorCallback | None]]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._values

    def request(
        self,
        target: Any,
        key: str,
        worker: Worker,
        on_ready: Callback | None = None,
        on_error: ErrorCallback | None = None,
        *,
        name: str | None = None,
        force: bool = False,
    ):
        with self._lock:
            if not force and key in self._values:
                value = self._values[key]
                if on_ready is not None:
                    dispatch_to_gui(target, lambda value=value: on_ready(value))
                return None

            if on_ready is not None or on_error is not None:
                self._callbacks.setdefault(key, []).append((target, on_ready, on_error))

            if key in self._loading:
                return None

            self._loading.add(key)
            self._errors.pop(key, None)

        def _apply(value: Any) -> None:
            with self._lock:
                self._values[key] = value
                self._loading.discard(key)
                callbacks = self._callbacks.pop(key, [])
            for cb_target, cb_ok, _cb_err in callbacks:
                if cb_ok is not None:
                    dispatch_to_gui(cb_target, lambda value=value, cb_ok=cb_ok: cb_ok(value))

        def _fail(exc: Exception) -> None:
            with self._lock:
                self._errors[key] = exc
                self._loading.discard(key)
                callbacks = self._callbacks.pop(key, [])
            for cb_target, _cb_ok, cb_err in callbacks:
                if cb_err is not None:
                    dispatch_to_gui(cb_target, lambda exc=exc, cb_err=cb_err: cb_err(exc))

        return run_async(target, worker, _apply, _fail, name=name or f"settings-prefetch:{key}")

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._values.clear()
                self._errors.clear()
                return
            self._values.pop(key, None)
            self._errors.pop(key, None)


def prefetch_settings_section(gui, category: str, cache: SettingsDataCache) -> None:
    """Владелец кэша — presentation-хаб (`presentation.settings_data`);
    модуль больше не держит глобального синглтона."""
    category = str(category or "").strip().lower()

    if category == "api":
        cache.request(
            gui,
            API_PROVIDER_NAMES,
            _load_api_provider_names,
            name="settings-section-api-providers",
        )
        return

    if category == "characters":
        cache.request(
            gui,
            CHARACTER_SETTINGS_SNAPSHOT,
            _load_character_settings_snapshot,
            name="settings-section-characters",
        )
        return

    if category == "models":
        cache.request(
            gui,
            EMBED_PRESET_ITEMS,
            _load_embed_preset_items,
            name="settings-section-embed-presets",
        )
        if bool(gui.settings.get("RAG_ENABLED", False)):
            cache.request(
                gui,
                RAG_EMBED_STATUS,
                _load_rag_embed_status,
                name="settings-section-rag-embed",
            )
            cache.request(
                gui,
                RAG_CE_STATUS,
                _load_rag_ce_status,
                name="settings-section-rag-ce",
            )
        return

    if category == "screen" and bool(gui.settings.get("ENABLE_CAMERA_CAPTURE", False)):
        try:
            from importlib.util import find_spec

            if find_spec("cv2") is None:
                return
        except (ImportError, AttributeError, ValueError):
            return
        cache.request(
            gui,
            CAMERA_LIST,
            _load_camera_list,
            name="settings-section-cameras",
        )


def api_provider_names_from_result(result) -> list[str]:
    meta = result[0] if result else None
    if not isinstance(meta, dict):
        return []

    names: list[str] = []
    seen: set[str] = set()
    for preset in meta.get("custom", []) or []:
        name = str(getattr(preset, "name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def embed_preset_items_from_meta(meta) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if not meta:
        from presets.embedding_provider_presets import list_builtin_presets

        for preset in list_builtin_presets():
            if preset.get("id") == "custom_local":
                continue
            items.append((preset["name"], preset["id"]))
        return items

    for preset in meta.get("builtin", []) or []:
        if preset.get("id") == "custom_local":
            continue
        items.append((preset["name"], preset["id"]))
    for preset in meta.get("custom", []) or []:
        items.append(("\u270e " + preset["name"], preset["id"]))
    return items


def _load_api_provider_names() -> list[str]:
    meta = use(ApiPresetService).list_meta()
    return api_provider_names_from_result([meta])


def _load_character_settings_snapshot() -> dict[str, Any]:
    registry = use(CharacterRegistry)
    character_list = registry.all_ids()
    current_char_id = registry.current_id()

    return {
        "character_list": [str(c or "").strip() for c in (character_list or []) if str(c or "").strip()],
        "current_char_id": current_char_id,
    }


def _load_embed_preset_items() -> list[tuple[str, Any]]:
    return embed_preset_items_from_meta(use(EmbeddingPresetService).list_meta())


def _load_camera_list() -> list[str]:
    try:
        from ui.settings.screen_analysis_settings import get_camera_list

        return get_camera_list()
    except Exception:
        logger.warning("[settings_prefetch] Failed to prefetch camera list", exc_info=True)
        return [_("No cameras found", "No cameras found")]


def _load_rag_embed_status() -> dict[str, Any]:
    from controllers.gui import rag_memory_controller as rag
    from core.services import use
    from services.contracts import InstallableCatalogService

    status = use(InstallableCatalogService).get_status("rag:embeddings")
    details = status.get("details") if isinstance(status.get("details"), dict) else {}
    required = bool(details.get("required", True))
    missing = ", ".join(str(item) for item in (details.get("missing_required") or ()))
    backend = (
        _("Не требуется", "Not required")
        if not required
        else _("Установлен", "Installed")
        if bool(status.get("ready", False))
        else _("Нужна установка ({items})", "Needs install ({items})").format(items=missing)
        if missing
        else _("Нужна установка", "Needs install")
    )

    return {
        "backend": backend,
        "index": rag._get_embed_status_text(),
        "visible": required and not bool(status.get("ready", False)),
    }


def _load_rag_ce_status() -> dict[str, Any]:
    from controllers.gui import rag_memory_controller as rag
    from core.services import use
    from managers.rag.pipeline.config import resolve_ce_model
    from services.contracts import InstallableCatalogService

    status = use(InstallableCatalogService).get_status("rag:reranker")
    details = status.get("details") if isinstance(status.get("details"), dict) else {}
    required = bool(details.get("required", True))
    missing = ", ".join(str(item) for item in (details.get("missing_required") or ()))
    backend = (
        _("Не требуется", "Not required")
        if not required
        else _("Установлен", "Installed")
        if bool(status.get("ready", False))
        else _("Нужна установка ({items})", "Needs install ({items})").format(items=missing)
        if missing
        else _("Нужна установка", "Needs install")
    )
    model_name = str(resolve_ce_model() or "")
    missing_models = tuple(details.get("download_models") or ())
    model_status = (
        _("Не выбрана", "Not selected")
        if not model_name
        else _("Не скачана", "Not downloaded") + f" ({model_name})"
        if missing_models
        else _("Скачана", "Downloaded") + f" ({model_name})"
    )

    return {
        "backend": backend,
        "model": model_status,
        "loaded": rag._get_ce_loaded_status(),
        "visible": required and not bool(status.get("ready", False)),
    }
