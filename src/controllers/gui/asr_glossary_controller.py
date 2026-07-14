from PyQt6.QtCore import QTimer

from core.events import Events, Event
from core.services import services
from main_logger import logger
from services.contracts import (
    InstallableCatalogService,
    InstallableOperationsService,
)
from .base_controller import BaseController
from .asr_glossary_view_model import AsrGlossaryViewModel

from ui.windows.asr_glossary_view import AsrGlossaryView


class AsrGlossaryGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._view_model = AsrGlossaryViewModel(
            load_catalog=self._load_catalog,
            load_settings=self._load_settings,
            install_model=self._install_model,
            set_option=self._set_recognizer_option,
        )
        self._glossary_view: AsrGlossaryView | None = AsrGlossaryView(self._view_model)
        self._view_model.setParent(self._glossary_view)
        super().__init__(main_controller, view)

        self._register_window_on_ready()

    def _register_window_on_ready(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return
        self.view.window_manager.set_dialog_on_ready("asr_glossary", self._on_dialog_ready)

    def subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

    def _on_dialog_ready(self, dialog, payload: dict):
        self._dialog = dialog

        if not self._glossary_view:
            return

        if dialog.layout() is None:
            logger.error("ASR glossary dialog has no layout")
            return

        try:
            if self._glossary_view.parent() is not None:
                self._glossary_view.setParent(None)
        except Exception:
            pass

        lay = dialog.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        lay.addWidget(self._glossary_view)

        QTimer.singleShot(0, self._view_model.refresh)

    def _install_model(self, engine_id: str) -> None:
        normalized = str(engine_id or "").strip()
        operations = services().get(InstallableOperationsService)
        admission = operations.install(
            {
                "component_id": f"asr:{normalized}",
                "with_ui": True,
                "task_id": f"asr:install:{normalized}",
                "meta": {"kind": "asr", "category": "asr"},
            }
        )
        if not admission.accepted:
            raise RuntimeError(admission.error or "ASR installation was rejected")

    def _load_catalog(self, refresh: bool) -> list[dict]:
        catalog = services().get(InstallableCatalogService)
        rows = catalog.list_rows(
            include_status=True,
            refresh=bool(refresh),
            category="asr",
            status_category="asr",
        )
        result: list[dict] = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if not isinstance(metadata, dict) or not isinstance(status, dict):
                continue
            details = status.get("details")
            details = dict(details) if isinstance(details, dict) else {}
            missing_required = list(details.get("missing_required") or ())
            if not bool(status.get("backend_ok", True)) and "backend" not in missing_required:
                missing_required.append("backend")
            result.append(
                {
                    "id": str(metadata.get("item_id") or ""),
                    "component_id": str(metadata.get("id") or ""),
                    "name": str(metadata.get("title") or metadata.get("item_id") or ""),
                    "description": str(metadata.get("description") or ""),
                    "languages": list(metadata.get("languages") or ()),
                    "tags": list(metadata.get("tags") or ()),
                    "links": [],
                    "installed": bool(status.get("ready", False)),
                    "ready": bool(status.get("ready", False)),
                    "status": dict(status),
                    "missing_required": missing_required,
                    "missing_optional": list(details.get("missing_optional") or ()),
                    "details": [dict(status)],
                }
            )
        return result


    def _set_recognizer_option(self, engine_id: str, key: str, value) -> None:
        catalog = services().get(InstallableCatalogService)
        component_id = f"asr:{str(engine_id or '').strip()}"
        values = catalog.load_settings(component_id)
        values[str(key)] = value
        result = catalog.save_component_settings(component_id, values)
        if not bool(result.get("ok", False)):
            raise RuntimeError(str(result.get("errors") or "Failed to save ASR settings"))

    def _load_settings(self, engine_id: str) -> dict:
        catalog = services().get(InstallableCatalogService)
        component_id = f"asr:{str(engine_id or '').strip()}"
        return {
            "schema": catalog.settings_schema(component_id) or [],
            "values": catalog.load_settings(component_id) or {},
        }

    def _is_asr_task(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("kind") == "asr":
            return True
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return meta.get("kind") == "asr"

    def _task_model_id(self, data: dict) -> str | None:
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return data.get("item_id") or meta.get("item_id") or data.get("model")

    def _on_install_progress(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_progress(
            engine_id=str(model),
            progress=int(data.get("progress", 0) or 0),
            status=str(data.get("status", "") or ""),
        )

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_finished(str(model))

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_failed(
            str(model),
            str(data.get("error", "") or ""),
        )

    def close(self) -> None:
        self._view_model.close()
        super().close()
