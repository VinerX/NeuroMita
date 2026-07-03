from __future__ import annotations

from typing import Any

from core.backends import BackendKind
from main_logger import logger

from core.events import Event, Events, get_event_bus
from core.install_types import InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    make_component_id,
)
from installables import get_installable_registry, refresh_installable_registry


class InstallableController:
    def __init__(self) -> None:
        self.event_bus = get_event_bus()
        self._list_cache_plain: list[dict[str, Any]] | None = None
        self._list_cache_with_status: list[dict[str, Any]] | None = None
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        eb = self.event_bus
        eb.subscribe(Events.Installable.LIST, self._on_list, weak=False)
        eb.subscribe(Events.Installable.GET, self._on_get, weak=False)
        eb.subscribe(Events.Installable.GET_STATUS, self._on_get_status, weak=False)
        eb.subscribe(Events.Installable.INSTALL, self._on_install, weak=False)
        eb.subscribe(Events.Installable.UNINSTALL, self._on_uninstall, weak=False)
        eb.subscribe(Events.Installable.INITIALIZE, self._on_initialize, weak=False)
        eb.subscribe(Events.Installable.GET_SETTINGS_SCHEMA, self._on_get_settings_schema, weak=False)
        eb.subscribe(Events.Installable.LOAD_SETTINGS, self._on_load_settings, weak=False)
        eb.subscribe(Events.Installable.SAVE_SETTINGS, self._on_save_settings, weak=False)
        eb.subscribe(Events.Install.TASK_STARTED, self._on_install_task_mutated, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_mutated, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_task_mutated, weak=False)

    def _invalidate_list_cache(self) -> None:
        self._list_cache_plain = None
        self._list_cache_with_status = None

    def _is_installable_task(self, data: dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        component_id = str(data.get("component_id") or meta.get("component_id") or "").strip()
        return ":" in component_id or str(meta.get("category") or "").strip() != ""

    def _on_install_task_mutated(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        if self._is_installable_task(data):
            self._invalidate_list_cache()

    def _component_id(self, data: dict[str, Any]) -> str:
        raw = str(data.get("component_id") or data.get("id") or "").strip()
        if raw:
            return raw
        category = data.get("category")
        item_id = data.get("item_id") or data.get("model_id") or data.get("model") or data.get("engine") or data.get("target")
        if category and item_id:
            return make_component_id(str(category), str(item_id))
        raise ValueError("Installable payload requires component_id or category+item_id")

    def _get_component(self, data: dict[str, Any]):
        registry = refresh_installable_registry() if data.get("refresh") else get_installable_registry()
        return registry.require(self._component_id(data))

    def _fallback_category(self, component) -> ComponentCategory:
        raw = getattr(component, "category", ComponentCategory.DEPENDENCY)
        if isinstance(raw, ComponentCategory):
            return raw
        try:
            return ComponentCategory(str(raw or "").strip().lower())
        except Exception:
            return ComponentCategory.DEPENDENCY

    def _fallback_metadata(self, component, exc: Exception) -> ComponentMetadata:
        category = self._fallback_category(component)
        item_id = str(getattr(component, "item_id", "") or getattr(component, "id", "") or "unknown").strip() or "unknown"
        component_id = str(getattr(component, "id", "") or make_component_id(category, item_id)).strip()
        legacy_kind = str(getattr(component, "legacy_kind", "") or category.value).strip()
        logger.error(f"Installable LIST metadata failed for '{component_id}': {exc}", exc_info=True)
        return ComponentMetadata(
            id=component_id,
            item_id=item_id,
            category=category,
            title=item_id,
            description="Component metadata is unavailable.",
            backend=BackendKind.NONE,
            legacy_kind=legacy_kind,
        )

    def _safe_metadata(self, component) -> ComponentMetadata:
        try:
            return component.metadata()
        except Exception as exc:
            return self._fallback_metadata(component, exc)

    def _safe_status(self, component, ctx: dict[str, Any], metadata: ComponentMetadata) -> ComponentStatus:
        try:
            return component.status(ctx)
        except Exception as exc:
            logger.error(f"Installable LIST status failed for '{metadata.id}': {exc}", exc_info=True)
            return ComponentStatus(
                id=metadata.id,
                code=ComponentStatusCode.FAILED,
                installed=False,
                ready=False,
                message=f"Failed to inspect component: {exc}",
                backend=metadata.backend,
                backend_ok=False,
                details={"error": str(exc)},
            )

    def _on_list(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        include_status = bool(data.get("include_status", False))
        ctx = data.get("ctx") if isinstance(data.get("ctx"), dict) else {}
        category = data.get("category")

        if data.get("refresh"):
            self._invalidate_list_cache()
            # Явный «Проверить обновления» → форсим свежий манифест версий голосов
            # (компоненты читают ctx["refresh"], чтобы минуть свой TTL-кэш).
            ctx = {**ctx, "refresh": True}

        cached_rows = None
        if not ctx and not data.get("refresh"):
            cached_rows = self._list_cache_with_status if include_status else self._list_cache_plain
        if cached_rows is not None:
            if category:
                value = str(category or "").strip().lower()
                return [
                    row for row in cached_rows
                    if str(((row.get("metadata") or {}).get("category") or "")).strip().lower() == value
                ]
            return list(cached_rows)

        registry = refresh_installable_registry() if data.get("refresh") else get_installable_registry()
        category = data.get("category")
        if category:
            try:
                items = registry.by_category(str(category))
            except Exception:
                items = []
        else:
            items = registry.all()

        result = []
        for item in items:
            metadata = self._safe_metadata(item)
            row = {"metadata": metadata.as_dict()}
            if include_status:
                row["status"] = self._safe_status(item, ctx, metadata).as_dict()
            result.append(row)

        if not ctx and not category:
            if include_status:
                self._list_cache_with_status = list(result)
            else:
                self._list_cache_plain = list(result)
        return result

    def _on_get(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            item = self._get_component(data)
            return item.metadata().as_dict()
        except Exception as exc:
            logger.error(f"Installable GET failed: {exc}", exc_info=True)
            return None

    def _on_get_status(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            item = self._get_component(data)
            ctx = data.get("ctx") if isinstance(data.get("ctx"), dict) else {}
            return item.status(ctx).as_dict()
        except Exception as exc:
            logger.error(f"Installable GET_STATUS failed: {exc}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # ConfigurableComponent bridge (used by AI Hub Settings tab)
    # ------------------------------------------------------------------

    def _as_configurable(self, component) -> Any:
        """Return the component if it implements ConfigurableComponent,
        else None. Uses duck-typing rather than the Protocol runtime check
        to keep the import set lean."""
        for attr in ("settings_schema", "load_settings", "save_settings"):
            if not callable(getattr(component, attr, None)):
                return None
        return component

    def _on_get_settings_schema(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            component = self._get_component(data)
        except Exception as exc:
            logger.error(f"Installable GET_SETTINGS_SCHEMA: not found: {exc}")
            return None
        configurable = self._as_configurable(component)
        if configurable is None:
            return []
        try:
            schema = configurable.settings_schema()
            return list(schema or [])
        except Exception as exc:
            logger.error(f"Installable GET_SETTINGS_SCHEMA failed: {exc}", exc_info=True)
            return []

    def _on_load_settings(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            component = self._get_component(data)
        except Exception as exc:
            logger.error(f"Installable LOAD_SETTINGS: not found: {exc}")
            return {}
        configurable = self._as_configurable(component)
        if configurable is None:
            return {}
        try:
            values = configurable.load_settings()
            return dict(values or {})
        except Exception as exc:
            logger.error(f"Installable LOAD_SETTINGS failed: {exc}", exc_info=True)
            return {}

    def _on_save_settings(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        values = data.get("values")
        if not isinstance(values, dict):
            return {"ok": False, "errors": {"_": "values must be a dict"}}
        try:
            component = self._get_component(data)
        except Exception as exc:
            return {"ok": False, "errors": {"_": str(exc)}}
        configurable = self._as_configurable(component)
        if configurable is None:
            return {"ok": False, "errors": {"_": "Component is not configurable"}}

        # If the component exposes validate_settings, run it first so the UI
        # can surface per-field errors before we touch persistence.
        validate = getattr(configurable, "validate_settings", None)
        if callable(validate):
            try:
                result = validate(values)
                ok = bool(getattr(result, "ok", True))
                errors = dict(getattr(result, "errors", {}) or {})
                if not ok:
                    return {"ok": False, "errors": errors}
            except Exception as exc:
                logger.error(f"Installable SAVE_SETTINGS validate failed: {exc}", exc_info=True)
                return {"ok": False, "errors": {"_": str(exc)}}

        try:
            configurable.save_settings(values)
            return {"ok": True, "errors": {}}
        except Exception as exc:
            logger.error(f"Installable SAVE_SETTINGS failed: {exc}", exc_info=True)
            return {"ok": False, "errors": {"_": str(exc)}}

    def _on_install(self, event: Event):
        self._run(event, op="install")

    def _on_uninstall(self, event: Event):
        self._run(event, op="uninstall")

    def _on_initialize(self, event: Event):
        self._run(event, op="initialize")

    def _run(self, event: Event, *, op: str) -> bool:
        data = event.data if isinstance(event.data, dict) else {}
        try:
            component = self._get_component(data)
        except Exception as exc:
            logger.error(f"Installable {op}: component not found: {exc}", exc_info=True)
            return False

        with_ui = bool(data.get("with_ui", True))
        timeout_sec = float(data.get("timeout_sec", 3600.0) or 3600.0)
        base_ctx = data.get("ctx") if isinstance(data.get("ctx"), dict) else {}
        # "Clean" reinstall: ignore the already-installed shortcut, force pip
        # reinstall and re-download artifacts (recovers from a broken/partial
        # download instead of refusing because files "exist").
        clean = bool(data.get("clean"))

        def runner(*_args, **kwargs) -> InstallPlan:
            run_ctx = dict(base_ctx)
            raw_ctx = kwargs.get("ctx") if isinstance(kwargs.get("ctx"), dict) else {}
            run_ctx.update(raw_ctx)
            run_ctx["clean"] = clean
            if kwargs.get("pip_installer") is not None:
                run_ctx["pip_installer"] = kwargs.get("pip_installer")
            if kwargs.get("callbacks") is not None:
                run_ctx["callbacks"] = kwargs.get("callbacks")

            if op == "install":
                return component.build_install_plan(run_ctx)
            if op == "uninstall":
                return component.build_uninstall_plan(run_ctx)
            plan = component.build_initialize_plan(run_ctx)
            if plan is None:
                return InstallPlan(actions=[], already_installed=True, already_installed_status="Nothing to initialize")
            return plan

        meta = {
            "kind": component.legacy_kind or component.category.value,
            "category": component.category.value,
            "component_id": component.id,
            "item_id": component.item_id,
            "op": op,
            "clean": clean,
        }
        if isinstance(data.get("meta"), dict):
            meta.update(data["meta"])
            meta.setdefault("component_id", component.id)
            meta.setdefault("category", component.category.value)
            meta.setdefault("item_id", component.item_id)
            meta.setdefault("op", op)

        title = data.get("title") or self._title(component, op)
        payload = {
            "kind": meta.get("kind"),
            "item_id": component.item_id,
            "component_id": component.id,
            "task_id": data.get("task_id") or f"{component.category.value}:{op}:{component.item_id}",
            "title": title,
            "initial_status": data.get("initial_status") or "Preparing...",
            "timeout_sec": timeout_sec,
            "meta": meta,
            "runner": runner,
        }

        # Optional UI override hooks. AI Hub and other embedded installers can
        # provide their own log/progress window; keep those objects intact so
        # InstallGuiController uses that window instead of spawning the global one.
        if data.get("install_window") is not None:
            payload["install_window"] = data.get("install_window")
        if data.get("install_callbacks") is not None:
            payload["install_callbacks"] = data.get("install_callbacks")

        self.event_bus.emit(Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS, payload)
        return True

    def _title(self, component, op: str) -> str:
        try:
            title = component.metadata().title
        except Exception:
            title = component.item_id
        labels = {
            "install": "Installing",
            "uninstall": "Uninstalling",
            "initialize": "Initializing",
        }
        return f"{labels.get(op, op.title())}: {title}"
