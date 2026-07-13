from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from installables.catalog_manifest import catalog_by_id, catalog_entries
from main_logger import logger
from services.contracts import InstallableCatalogService, SettingsService


class DefaultInstallableCatalogService(InstallableCatalogService):
    """Two-phase installable catalog.

    Metadata is served from a declarative manifest and is available during the
    GUI shell phase. Component implementations are imported only for status,
    settings or install/uninstall work.
    """

    def __init__(self, settings: SettingsService | None = None) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._status_cache: dict[str, dict[str, Any]] = {}
        self._runtime_registry_prepared = False
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="installable-state",
        )
        self._settings_subscription = None
        if settings is not None:
            try:
                self._settings_subscription = settings.subscribe(
                    self._on_setting_changed,
                    replay=False,
                )
            except Exception:
                self._settings_subscription = None

    def _on_setting_changed(self, _change: Any) -> None:
        # Component readiness can depend on device/model/provider settings.
        # A single invalidation point prevents stale per-screen interpretations.
        self.invalidate()

    def _language(self) -> str:
        if self._settings is None:
            return "RU"
        try:
            return str(self._settings.get("LANGUAGE", "RU") or "RU").upper()
        except Exception:
            return "RU"

    def _metadata(self, entry) -> dict[str, Any]:
        language = self._language()
        source = entry.metadata_en if language == "EN" else entry.metadata_ru
        result = copy.deepcopy(source)
        if language not in {"RU", "EN"}:
            try:
                from localization import translate_for_language

                result["title"] = translate_for_language(
                    language,
                    str(entry.metadata_ru.get("title") or ""),
                    str(entry.metadata_en.get("title") or ""),
                )
                result["description"] = translate_for_language(
                    language,
                    str(entry.metadata_ru.get("description") or ""),
                    str(entry.metadata_en.get("description") or ""),
                )
            except Exception:
                pass
        return result

    @staticmethod
    def _matches_category(entry, category: str | None) -> bool:
        if not category:
            return True
        target = str(category).strip().lower()
        actual = str(entry.metadata_ru.get("category") or "").strip().lower()
        return actual == target

    def list_rows(
        self,
        *,
        include_status: bool = False,
        refresh: bool = False,
        category: str | None = None,
        status_category: str | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        all_entries = catalog_entries()
        entries = tuple(
            entry for entry in all_entries if self._matches_category(entry, category)
        )

        if include_status:
            status_entries = tuple(
                entry
                for entry in all_entries
                if self._matches_category(entry, status_category or category)
            )
            self._refresh_statuses(status_entries, refresh=refresh, ctx=ctx)

        with self._lock:
            statuses = copy.deepcopy(self._status_cache)

        rows: list[dict[str, Any]] = []
        for entry in entries:
            row = {"metadata": self._metadata(entry)}
            status = statuses.get(entry.id)
            if status is not None:
                row["status"] = status
            rows.append(row)
        return rows

    def get_row(
        self,
        component_id: str,
        *,
        include_status: bool = True,
        refresh: bool = False,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(component_id or "").strip()
        entry = catalog_by_id().get(normalized)
        if entry is None:
            raise KeyError(f"Unknown installable component: {normalized}")

        if include_status:
            self._refresh_statuses((entry,), refresh=refresh, ctx=ctx)

        row: dict[str, Any] = {"metadata": self._metadata(entry)}
        if include_status:
            with self._lock:
                status = copy.deepcopy(self._status_cache.get(normalized))
            if status is not None:
                row["status"] = status
        return row

    def get_status(
        self,
        component_id: str,
        *,
        refresh: bool = False,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.get_row(
            component_id,
            include_status=True,
            refresh=refresh,
            ctx=ctx,
        )
        status = row.get("status")
        if not isinstance(status, dict):
            raise RuntimeError(f"Component status is unavailable: {component_id}")
        return status

    def is_ready(
        self,
        component_id: str,
        *,
        refresh: bool = False,
        ctx: dict[str, Any] | None = None,
    ) -> bool:
        return bool(
            self.get_status(
                component_id,
                refresh=refresh,
                ctx=ctx,
            ).get("ready", False)
        )

    def ready_item_ids(
        self,
        category: str,
        *,
        refresh: bool = False,
        ctx: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        rows = self.list_rows(
            include_status=True,
            refresh=refresh,
            category=str(category or "").strip().lower(),
            ctx=ctx,
        )
        result: list[str] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if not isinstance(metadata, dict) or not isinstance(status, dict):
                continue
            if bool(status.get("ready", False)):
                item_id = str(metadata.get("item_id") or "").strip()
                if item_id:
                    result.append(item_id)
        return tuple(result)

    def list_rows_async(
        self,
        callback,
        *,
        include_status: bool = False,
        refresh: bool = False,
        category: str | None = None,
        status_category: str | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        def run() -> None:
            try:
                rows = self.list_rows(
                    include_status=include_status,
                    refresh=refresh,
                    category=category,
                    status_category=status_category,
                    ctx=ctx,
                )
                callback(rows, None)
            except BaseException as exc:
                callback([], exc)

        self._executor.submit(run)

    def get_status_async(
        self,
        component_id: str,
        callback,
        *,
        refresh: bool = False,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        def run() -> None:
            try:
                callback(
                    self.get_status(component_id, refresh=refresh, ctx=ctx),
                    None,
                )
            except BaseException as exc:
                callback({}, exc)

        self._executor.submit(run)

    def require_component(self, component_id: str, *, refresh: bool = False) -> Any:
        normalized = str(component_id or "").strip()
        if normalized not in catalog_by_id():
            raise KeyError(f"Unknown installable component: {normalized}")
        from installables.registry_builder import (
            get_installable_registry,
            refresh_installable_registry,
        )

        registry = refresh_installable_registry() if refresh else get_installable_registry()
        return registry.require(normalized)

    def install_preview(
        self,
        component_id: str,
        *,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from core.backends import BackendKind, get_backend_service
        from utils.gpu_utils import check_gpu_provider, format_primary_gpu_label

        component = self.require_component(component_id)
        runtime_ctx = dict(ctx or {})
        runtime_ctx.setdefault("gpu_vendor", str(check_gpu_provider() or "CPU"))
        plan = component.build_install_plan(runtime_ctx)
        backend_kind = get_backend_service().build_requirement(
            plan.required_backend
        ).kind
        backend_ready = True
        backend_id = ""
        backend_title = ""
        backend_packages: list[str] = []
        backend_size = ""
        backend_status: dict[str, Any] = {}
        if backend_kind is not BackendKind.NONE:
            backend_id = f"backend:{backend_kind.value}"
            backend_title = {
                BackendKind.CUDA: "PyTorch CUDA (NVIDIA)",
                BackendKind.CPU: "PyTorch CPU",
                BackendKind.ONNX: "ONNX Runtime",
            }.get(backend_kind, backend_kind.value.upper())
            canonical_backend_status = self.get_status(backend_id, ctx=runtime_ctx)
            backend_ready = bool(canonical_backend_status.get("ready"))
            backend_status = dict(canonical_backend_status.get("details") or {})
            backend_packages.extend(
                str(item) for item in backend_status.get("install_packages") or ()
            )
            backend_entry = catalog_by_id().get(backend_id)
            if backend_entry is not None:
                backend_meta = self._metadata(backend_entry)
                backend_title = str(backend_meta.get("title") or backend_title)
                backend_size = str(backend_meta.get("size") or "")

        metadata = component.metadata()
        action_descriptions = [
            str(action.description or action.type)
            for action in plan.actions
            if str(action.description or action.type).strip()
        ]
        component_is_backend = str(metadata.category.value) == "backend"
        backend_will_install = bool(
            backend_id and not backend_ready and not component_is_backend
        )
        additional_components: list[dict[str, Any]] = []
        if backend_will_install:
            additional_components.append(
                {
                    "id": backend_id,
                    "title": backend_title,
                    "size": backend_size,
                    "packages": list(dict.fromkeys(backend_packages)),
                    "reason": "required_backend",
                }
            )

        return {
            "component_id": component.id,
            "component_title": metadata.title,
            "component_size": metadata.size,
            "component_is_backend": component_is_backend,
            "gpu": format_primary_gpu_label(),
            "backend_kind": backend_kind.value,
            "backend_id": backend_id,
            "backend_title": backend_title,
            "backend_packages": list(dict.fromkeys(backend_packages)),
            "backend_size": backend_size,
            "backend_status": backend_status,
            "backend_ready": backend_ready,
            "backend_will_install": backend_will_install,
            "additional_components": additional_components,
            "actions": action_descriptions,
        }

    def invalidate(self, component_id: str | None = None) -> None:
        with self._lock:
            if component_id:
                self._status_cache.pop(str(component_id), None)
            else:
                self._status_cache.clear()
        try:
            from installables.registry_builder import get_installable_registry

            get_installable_registry().invalidate(component_id=component_id)
        except Exception:
            pass

    @staticmethod
    def _as_configurable(component: Any) -> Any | None:
        for attr in ("settings_schema", "load_settings", "save_settings"):
            if not callable(getattr(component, attr, None)):
                return None
        return component

    def settings_schema(self, component_id: str) -> list[dict[str, Any]]:
        try:
            component = self._as_configurable(self.require_component(component_id))
            if component is None:
                return []
            return list(component.settings_schema() or [])
        except Exception as exc:
            logger.error(
                f"Installable settings schema failed for '{component_id}': {exc}",
                exc_info=True,
            )
            return []

    def load_settings(self, component_id: str) -> dict[str, Any]:
        try:
            component = self._as_configurable(self.require_component(component_id))
            if component is None:
                return {}
            return dict(component.load_settings() or {})
        except Exception as exc:
            logger.error(
                f"Installable settings load failed for '{component_id}': {exc}",
                exc_info=True,
            )
            return {}

    def save_component_settings(
        self, component_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            return {"ok": False, "errors": {"_": "values must be a dict"}}
        try:
            component = self._as_configurable(self.require_component(component_id))
            if component is None:
                return {"ok": False, "errors": {"_": "Component is not configurable"}}
            validate = getattr(component, "validate_settings", None)
            if callable(validate):
                result = validate(values)
                if not bool(getattr(result, "ok", True)):
                    return {
                        "ok": False,
                        "errors": dict(getattr(result, "errors", {}) or {}),
                    }
            component.save_settings(values)
            self.invalidate(component_id)
            return {"ok": True, "errors": {}}
        except Exception as exc:
            logger.error(
                f"Installable settings save failed for '{component_id}': {exc}",
                exc_info=True,
            )
            return {"ok": False, "errors": {"_": str(exc)}}

    def _refresh_statuses(
        self,
        entries: Iterable[Any],
        *,
        refresh: bool,
        ctx: dict[str, Any] | None,
    ) -> None:
        unique = tuple(dict.fromkeys(entry.id for entry in entries))
        if not unique:
            return

        with self._lock:
            missing = [
                component_id
                for component_id in unique
                if refresh or component_id not in self._status_cache
            ]
        if not missing:
            return

        self._prepare_runtime_registry()

        if refresh:
            for component_id in missing:
                self.invalidate(component_id)

        runtime_ctx = dict(ctx or {})
        if refresh:
            runtime_ctx["refresh"] = True

        by_id = catalog_by_id()

        def inspect(component_id: str) -> tuple[str, dict[str, Any]]:
            entry = by_id[component_id]
            try:
                from core.runtime_environments import runtime_environments

                metadata = entry.metadata_ru
                component_ctx = runtime_environments().component_context(
                    category=str(metadata.get("category") or ""),
                    item_id=str(metadata.get("item_id") or component_id.split(":", 1)[-1]),
                    ctx=runtime_ctx,
                )
                component = self.require_component(component_id)
                value = component.status(component_ctx)
                return component_id, value.as_dict()
            except Exception as exc:
                logger.error(
                    f"Installable status failed for '{component_id}': {exc}",
                    exc_info=True,
                )
                return component_id, {
                    "id": component_id,
                    "code": "failed",
                    "installed": False,
                    "ready": False,
                    "message": f"Failed to inspect component: {exc}",
                    "backend": str(entry.metadata_ru.get("backend") or "none"),
                    "backend_ok": False,
                    "details": {"error": str(exc)},
                }

        workers = min(4, len(missing))
        if workers <= 1:
            inspected = [inspect(component_id) for component_id in missing]
        else:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="installable-catalog",
            ) as executor:
                inspected = list(executor.map(inspect, missing))

        with self._lock:
            for component_id, status in inspected:
                self._status_cache[component_id] = status

    def _prepare_runtime_registry(self) -> None:
        with self._lock:
            if self._runtime_registry_prepared:
                return
            self._runtime_registry_prepared = True
        try:
            from core.runtime_environments import runtime_environments

            manager = runtime_environments()
            migrate = getattr(manager, "migrate_legacy_environment_ids", None)
            if callable(migrate):
                migrate()
            recover = getattr(manager, "recover_unregistered_overlays", None)
            if callable(recover):
                recover()
        except Exception as exc:
            logger.warning(f"Runtime environment registry preparation failed: {exc}")
