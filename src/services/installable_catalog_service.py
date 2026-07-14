from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import Future, wait
from typing import Any, Iterable

from core.daemon_executor import DaemonExecutor
from core.installables.compatibility import evaluate_installable_compatibility
from core.services import services
from installables.catalog_manifest import catalog_by_id, catalog_entries
from main_logger import logger
from services.asr_settings_service import ensure_asr_settings_service
from services.contracts import (
    ASRSettingsService,
    HardwareInventoryService,
    InstallableCatalogService,
    SettingsService,
)


class DefaultInstallableCatalogService(InstallableCatalogService):
    """Two-phase installable catalog.

    Metadata is served from a declarative manifest and is available during the
    GUI shell phase. Component implementations are imported only for status,
    settings or install/uninstall work.
    """

    def __init__(
        self,
        settings: SettingsService | None = None,
        *,
        hardware: HardwareInventoryService | None = None,
        asr_settings: ASRSettingsService | None = None,
        status_timeout_sec: float = 15.0,
    ) -> None:
        self._settings = settings
        self._hardware = hardware or services().get_optional(HardwareInventoryService)
        self._asr_settings = asr_settings or ensure_asr_settings_service()
        self._status_timeout_sec = max(0.1, float(status_timeout_sec))
        self._lock = threading.RLock()
        self._status_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._inflight: dict[tuple[str, str], Future[Any]] = {}
        self._component_revisions: dict[str, int] = {}
        self._closed = False
        self._runtime_registry_prepared = False
        self._probe_executor = DaemonExecutor(
            4,
            thread_name_prefix="installable-probe",
        )
        self._async_executor = DaemonExecutor(
            2,
            thread_name_prefix="installable-request",
        )
        self._settings_subscription = None
        self._asr_settings_subscription = None
        if settings is not None:
            try:
                self._settings_subscription = settings.subscribe(
                    self._on_setting_changed,
                    replay=False,
                )
            except Exception:
                self._settings_subscription = None
        try:
            self._asr_settings_subscription = self._asr_settings.subscribe(
                self._on_asr_setting_changed,
                replay=False,
            )
        except Exception:
            self._asr_settings_subscription = None

    def _on_setting_changed(self, _change: Any) -> None:
        # Component readiness can depend on device/model/provider settings.
        # A single invalidation point prevents stale per-screen interpretations.
        self.invalidate()

    def _on_asr_setting_changed(self, change: Any) -> None:
        engine_id = str(getattr(change, "engine_id", "") or "").strip()
        self.invalidate(f"asr:{engine_id}" if engine_id else None)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = tuple(self._inflight.values())
            self._inflight.clear()
            self._status_cache.clear()
        for future in futures:
            future.cancel()
        self._async_executor.shutdown(cancel_futures=True)
        self._probe_executor.shutdown(cancel_futures=True)
        for subscription in (self._settings_subscription, self._asr_settings_subscription):
            close = getattr(subscription, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

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

    def _hardware_snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        hardware = self._hardware or services().get_optional(HardwareInventoryService)
        if hardware is None:
            return {"vendor": "CPU", "platform": ""}
        try:
            return dict(hardware.snapshot(refresh=refresh) or {})
        except Exception as exc:
            logger.warning(f"Hardware inventory failed during catalog evaluation: {exc}")
            return {"vendor": "CPU", "platform": "", "error": str(exc)}

    def _compatibility(
        self,
        entry,
        status: dict[str, Any] | None,
        *,
        ctx: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = self._metadata(entry)
        backend = str((status or {}).get("backend") or metadata.get("backend") or "none")
        vendor = str((ctx or {}).get("gpu_vendor") or "").strip()
        if not vendor:
            vendor = str(self._hardware_snapshot().get("vendor") or "CPU")
        return evaluate_installable_compatibility(
            component_id=entry.id,
            backend=backend,
            gpu_vendor=vendor,
            language=self._language(),
        )

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

        statuses: dict[str, dict[str, Any]] = {}
        if include_status:
            status_entries = tuple(
                entry
                for entry in all_entries
                if self._matches_category(entry, status_category or category)
            )
            statuses = self._refresh_statuses(status_entries, refresh=refresh, ctx=ctx)

        rows: list[dict[str, Any]] = []
        for entry in entries:
            row = {"metadata": self._metadata(entry)}
            status = statuses.get(entry.id)
            if status is not None:
                row["status"] = status
            row["compatibility"] = self._compatibility(entry, status, ctx=ctx)
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

        statuses = (
            self._refresh_statuses((entry,), refresh=refresh, ctx=ctx)
            if include_status
            else {}
        )

        row: dict[str, Any] = {"metadata": self._metadata(entry)}
        if include_status:
            status = statuses.get(normalized)
            if status is not None:
                row["status"] = status
        else:
            status = None
        row["compatibility"] = self._compatibility(entry, status, ctx=ctx)
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

        self._async_executor.submit(run)

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

        self._async_executor.submit(run)

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

        component = self.require_component(component_id)
        entry = catalog_by_id().get(str(component_id or "").strip())
        if entry is None:
            raise KeyError(component_id)
        runtime_ctx = self._component_context(entry, ctx=ctx, refresh=False)
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

        hardware = self._hardware_snapshot()
        primary = hardware.get("primary") if isinstance(hardware.get("primary"), dict) else {}
        gpu_label = str(primary.get("name") or hardware.get("vendor") or "CPU")
        return {
            "component_id": component.id,
            "component_title": metadata.title,
            "component_size": metadata.size,
            "component_is_backend": component_is_backend,
            "gpu": gpu_label,
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
        abandoned: list[Future[Any]] = []
        with self._lock:
            if component_id:
                normalized = str(component_id)
                self._component_revisions[normalized] = self._component_revisions.get(normalized, 0) + 1
                for key in tuple(self._status_cache):
                    if key[0] == normalized:
                        self._status_cache.pop(key, None)
                for key in tuple(self._inflight):
                    if key[0] == normalized:
                        abandoned.append(self._inflight.pop(key))
            else:
                for entry in catalog_entries():
                    self._component_revisions[entry.id] = self._component_revisions.get(entry.id, 0) + 1
                self._status_cache.clear()
                abandoned.extend(self._inflight.values())
                self._inflight.clear()
        for future in abandoned:
            future.cancel()
            self._probe_executor.abandon(future)
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
    ) -> dict[str, dict[str, Any]]:
        by_id = {entry.id: entry for entry in entries}
        if not by_id:
            return {}

        with self._lock:
            if self._closed:
                raise RuntimeError("Installable catalog is closed")

        self._prepare_runtime_registry()
        if refresh:
            for component_id in by_id:
                self.invalidate(component_id)

        contexts: dict[str, dict[str, Any]] = {}
        keys: dict[str, tuple[str, str]] = {}
        for component_id, entry in by_id.items():
            component_ctx = self._component_context(entry, ctx=ctx, refresh=refresh)
            contexts[component_id] = component_ctx
            keys[component_id] = (component_id, self._context_fingerprint(component_ctx))

        futures: dict[tuple[str, str], Future[Any]] = {}
        generations: dict[tuple[str, str], int] = {}
        with self._lock:
            for component_id, key in keys.items():
                if key in self._status_cache:
                    continue
                revision = self._component_revisions.get(component_id, 0)
                generations[key] = revision
                future = self._inflight.get(key)
                if future is None:
                    future = self._probe_executor.submit(
                        self._inspect_component,
                        by_id[component_id],
                        contexts[component_id],
                    )
                    self._inflight[key] = future
                futures[key] = future

        if futures:
            done, pending = wait(
                tuple(set(futures.values())),
                timeout=self._status_timeout_sec,
            )
            results: dict[tuple[str, str], dict[str, Any]] = {}
            for key, future in futures.items():
                component_id = key[0]
                if future in pending:
                    future.cancel()
                    self._probe_executor.abandon(future)
                    results[key] = self._failed_status(
                        by_id[component_id],
                        f"Status probe timed out after {self._status_timeout_sec:.1f}s",
                        code="timeout",
                    )
                    continue
                try:
                    results[key] = dict(future.result())
                except BaseException as exc:
                    logger.error(
                        f"Installable status failed for '{component_id}': {exc}",
                        exc_info=True,
                    )
                    results[key] = self._failed_status(by_id[component_id], str(exc))

            with self._lock:
                for key, future in futures.items():
                    if self._inflight.get(key) is future:
                        self._inflight.pop(key, None)
                if not self._closed:
                    for key, status in results.items():
                        component_id = key[0]
                        if self._component_revisions.get(component_id, 0) == generations[key]:
                            self._status_cache[key] = copy.deepcopy(status)

        with self._lock:
            return {
                component_id: copy.deepcopy(self._status_cache[key])
                for component_id, key in keys.items()
                if key in self._status_cache
            }

    def _component_context(
        self,
        entry: Any,
        *,
        ctx: dict[str, Any] | None,
        refresh: bool,
    ) -> dict[str, Any]:
        metadata = entry.metadata_ru
        category = str(metadata.get("category") or "").strip().lower()
        item_id = str(metadata.get("item_id") or entry.id.split(":", 1)[-1]).strip()
        result = dict(ctx or {})
        hardware = self._hardware_snapshot(refresh=False)
        result.setdefault("gpu_vendor", str(hardware.get("vendor") or "CPU"))
        result.setdefault("platform", str(hardware.get("platform") or ""))
        if category == "asr":
            result.setdefault("engine_settings", self._asr_settings.model_settings(item_id))
            result["asr_settings_revision"] = self._asr_settings.revision
        if refresh:
            result["refresh"] = True

        from core.runtime_environments import runtime_environments

        return runtime_environments().component_context(
            category=category,
            item_id=item_id,
            ctx=result,
        )

    @staticmethod
    def _context_fingerprint(ctx: dict[str, Any]) -> str:
        stable_ctx = {
            key: value
            for key, value in ctx.items()
            if key not in {"refresh", "timeout_sec", "callbacks"}
        }
        payload = json.dumps(stable_ctx, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _inspect_component(self, entry: Any, component_ctx: dict[str, Any]) -> dict[str, Any]:
        component = self.require_component(entry.id)
        return dict(component.status(dict(component_ctx)).as_dict())

    @staticmethod
    def _failed_status(entry: Any, error: str, *, code: str = "failed") -> dict[str, Any]:
        return {
            "id": entry.id,
            "code": code,
            "installed": False,
            "ready": False,
            "message": f"Failed to inspect component: {error}",
            "backend": str(entry.metadata_ru.get("backend") or "none"),
            "backend_ok": False,
            "details": {"error": str(error)},
        }

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
