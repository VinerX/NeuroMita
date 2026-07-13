from __future__ import annotations

from typing import Any

from main_logger import logger

from core.events import Event, EventDelivery, Events, get_event_bus
from core.services import services
from services.contracts import (
    InstallAdmission,
    InstallableCatalogService,
    InstallableOperationsService,
    InstallQueueService,
    SettingsService,
)
from services.installable_catalog_service import DefaultInstallableCatalogService
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC, InstallPlan
from core.installables import make_component_id


class InstallableController(InstallableOperationsService):
    def __init__(self, catalog: InstallableCatalogService | None = None) -> None:
        self.event_bus = get_event_bus()
        if catalog is None:
            registry = services()
            if registry.is_registered(InstallableCatalogService):
                catalog = registry.get(InstallableCatalogService)
            else:
                settings = registry.get(SettingsService) if registry.is_registered(SettingsService) else None
                catalog = DefaultInstallableCatalogService(settings)
                registry.register(InstallableCatalogService, catalog)
        self.catalog = catalog
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        eb = self.event_bus
        eb.subscribe(Events.Installable.INSTALL, self._on_install, weak=False)
        eb.subscribe(Events.Installable.UNINSTALL, self._on_uninstall, weak=False)
        eb.subscribe(Events.Installable.INITIALIZE, self._on_initialize, weak=False)
        eb.subscribe(Events.Install.TASK_STARTED, self._on_install_task_mutated, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_mutated, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_task_mutated, weak=False)

    def _invalidate_list_cache(self, component_id: str | None = None) -> None:
        self.catalog.invalidate(component_id)

    def _is_installable_task(self, data: dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        component_id = str(data.get("component_id") or meta.get("component_id") or "").strip()
        return ":" in component_id or str(meta.get("category") or "").strip() != ""

    def _on_install_task_mutated(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        if self._is_installable_task(data):
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            component_id = str(data.get("component_id") or meta.get("component_id") or "").strip()
            self._invalidate_list_cache(component_id or None)

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
        return self.catalog.require_component(
            self._component_id(data),
            refresh=bool(data.get("refresh")),
        )

    def _on_list(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        ctx = data.get("ctx") if isinstance(data.get("ctx"), dict) else {}
        return self.catalog.list_rows(
            include_status=bool(data.get("include_status", False)),
            refresh=bool(data.get("refresh", False)),
            category=data.get("category"),
            status_category=data.get("status_category"),
            ctx=ctx,
        )

    def _on_get(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            component_id = self._component_id(data)
            rows = self.catalog.list_rows(category=str(component_id).split(":", 1)[0])
            for row in rows:
                metadata = row.get("metadata") if isinstance(row, dict) else None
                if isinstance(metadata, dict) and metadata.get("id") == component_id:
                    return metadata
            return self._get_component(data).metadata().as_dict()
        except Exception as exc:
            logger.error(f"Installable GET failed: {exc}", exc_info=True)
            return None

    def _on_get_status(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            return self.catalog.get_status(
                self._component_id(data),
                refresh=bool(data.get("refresh", False)),
                ctx=data.get("ctx") if isinstance(data.get("ctx"), dict) else {},
            )
        except Exception as exc:
            logger.error(f"Installable GET_STATUS failed: {exc}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # ConfigurableComponent bridge (legacy EventBus compatibility)
    # ------------------------------------------------------------------

    def _on_get_settings_schema(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            return self.catalog.settings_schema(self._component_id(data))
        except Exception as exc:
            logger.error(f"Installable GET_SETTINGS_SCHEMA failed: {exc}", exc_info=True)
            return []

    def _on_load_settings(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        try:
            return self.catalog.load_settings(self._component_id(data))
        except Exception as exc:
            logger.error(f"Installable LOAD_SETTINGS failed: {exc}", exc_info=True)
            return {}

    def _on_save_settings(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        values = data.get("values")
        try:
            return self.catalog.save_component_settings(
                self._component_id(data),
                values if isinstance(values, dict) else values,
            )
        except Exception as exc:
            logger.error(f"Installable SAVE_SETTINGS failed: {exc}", exc_info=True)
            return {"ok": False, "errors": {"_": str(exc)}}

    def install(self, payload: dict[str, Any]) -> InstallAdmission:
        return self._run_payload(payload, op="install")

    def uninstall(self, payload: dict[str, Any]) -> InstallAdmission:
        return self._run_payload(payload, op="uninstall")

    def initialize(self, payload: dict[str, Any]) -> InstallAdmission:
        return self._run_payload(payload, op="initialize")

    def _on_install(self, event: Event) -> InstallAdmission:
        data = event.data if isinstance(event.data, dict) else {}
        return self.install(data)

    def _on_uninstall(self, event: Event) -> InstallAdmission:
        data = event.data if isinstance(event.data, dict) else {}
        return self.uninstall(data)

    def _on_initialize(self, event: Event) -> InstallAdmission:
        data = event.data if isinstance(event.data, dict) else {}
        return self.initialize(data)

    def _run_payload(self, data: dict[str, Any], *, op: str) -> InstallAdmission:
        requested_task_id = str(data.get("task_id") or "")
        try:
            component = self._get_component(data)
        except Exception as exc:
            logger.error(f"Installable {op}: component not found: {exc}", exc_info=True)
            return InstallAdmission(
                accepted=False,
                task_id=requested_task_id,
                error=str(exc),
            )

        with_ui = bool(data.get("with_ui", True))
        timeout_sec = float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC)
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
        if data.get("install_style_variant") is not None:
            payload["install_style_variant"] = data.get("install_style_variant")

        queue_service = services().get_optional(InstallQueueService)
        if queue_service is not None:
            admission = queue_service.enqueue(payload, with_ui=with_ui)
        elif with_ui:
            admission = InstallAdmission(
                accepted=False,
                task_id=str(payload["task_id"]),
                error="Install queue service is unavailable",
            )
        else:
            event_name = (
                Events.Install.RUN_WITH_UI
                if with_ui
                else Events.Install.RUN_HEADLESS
            )
            accepted = self.event_bus.try_emit(
                event_name,
                payload,
                delivery=EventDelivery.COMMAND,
            )
            admission = InstallAdmission(
                accepted=accepted,
                task_id=str(payload["task_id"]),
                error=(
                    "Install queue service is unavailable"
                    if not accepted
                    else ""
                ),
            )

        if admission.accepted:
            logger.info(
                f"Installable {op} request admitted: "
                f"component={component.id}, task_id={payload['task_id']}, "
                f"duplicate={admission.duplicate}"
            )
            return admission

        error = admission.error or "Installation queue is unavailable"
        logger.error(
            f"Installable {op} request rejected: "
            f"component={component.id}, task_id={payload['task_id']}: {error}"
        )
        self.event_bus.emit(
            Events.Install.TASK_FAILED,
            {
                "task_id": payload["task_id"],
                "component_id": component.id,
                "meta": meta,
                "error": error,
            },
        )
        return InstallAdmission(
            accepted=False,
            task_id=str(payload["task_id"]),
            error=error,
        )

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
