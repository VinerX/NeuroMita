from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from main_logger import logger
from core.events import Events, Event
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC
from core.services import services
from services.contracts import LocalVoiceService, VoiceModelService
from .base_controller import BaseController
from .voice_models_view_model import VoiceModelsViewModel
from utils import getTranslationVariant as _

from ui.windows.voice_model_view import VoiceModelSettingsView


class VoiceModelGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._view_model = VoiceModelsViewModel(
            load_snapshot=self._load_view_snapshot,
            install=self.request_install,
            uninstall=self.request_uninstall,
            save=self._save_values,
            close_view=self._close_with_values,
            open_documentation=self.open_documentation,
            resolve_description=self._resolve_description,
        )
        self._vm_view: VoiceModelSettingsView | None = VoiceModelSettingsView(
            self._view_model,
            auto_initialize=False,
        )
        super().__init__(main_controller, view)

        self._register_window_on_ready()


    # Passive-view command/data boundary.
    def model_catalog_snapshot(self):
        service = services().get_optional(VoiceModelService)
        return service.model_catalog_snapshot() if service is not None else []

    def installed_models_snapshot(self):
        service = services().get_optional(VoiceModelService)
        return service.installed_models_snapshot() if service is not None else set()

    def dependencies_status(self):
        service = services().get_optional(VoiceModelService)
        return service.dependencies_status() if service is not None else {}

    def _load_view_snapshot(self) -> dict:
        return {
            "models_data": self.model_catalog_snapshot(),
            "installed_models": self.installed_models_snapshot(),
            "dependencies_status": self.dependencies_status(),
        }

    def request_install(self, model_id: str) -> bool:
        return bool(self._on_install_model(Event(Events.VoiceModel.INSTALL_MODEL, {"model_id": str(model_id), "with_ui": True})))

    def request_uninstall(self, model_id: str) -> bool:
        return bool(self._on_uninstall_model(Event(Events.VoiceModel.UNINSTALL_MODEL, {"model_id": str(model_id), "with_ui": True})))

    def save_view_settings(self) -> None:
        self._on_save_settings(Event(Events.VoiceModel.SAVE_SETTINGS))

    def close_view(self) -> None:
        self._on_close_dialog(Event(Events.VoiceModel.CLOSE_DIALOG))

    def update_description(self, key: str) -> None:
        self._on_update_description(Event(Events.VoiceModel.UPDATE_DESCRIPTION, str(key)))

    def clear_description(self) -> None:
        self._on_clear_description(Event(Events.VoiceModel.CLEAR_DESCRIPTION))

    def open_documentation(self, path: str) -> None:
        self.event_bus.emit(Events.VoiceModel.OPEN_DOC, str(path))

    def triton_status(self, *, refresh: bool = False) -> dict:
        service = services().get_optional(LocalVoiceService)
        return dict(service.triton_status(refresh=refresh) or {}) if service is not None else {}

    def _register_window_on_ready(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return
        self.view.window_manager.set_dialog_on_ready("voice_models", self._on_voice_models_dialog_ready)

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS_DIALOG, self._on_legacy_open_voice_models, weak=False)

        self.event_bus.subscribe(Events.VoiceModel.INSTALL_MODEL, self._on_install_model, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.UNINSTALL_MODEL, self._on_uninstall_model, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.SAVE_SETTINGS, self._on_save_settings, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.CLOSE_DIALOG, self._on_close_dialog, weak=False)

        self.event_bus.subscribe(Events.VoiceModel.MODEL_INSTALL_STARTED, self._on_install_started, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.MODEL_INSTALL_FINISHED, self._on_install_finished, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.MODEL_UNINSTALL_STARTED, self._on_uninstall_started, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.MODEL_UNINSTALL_FINISHED, self._on_uninstall_finished, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.REFRESH_MODEL_PANELS, self._on_refresh_panels_requested, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.REFRESH_SETTINGS_DISPLAY, self._on_refresh_settings_requested, weak=False)

        self.event_bus.subscribe(Events.VoiceModel.UPDATE_DESCRIPTION, self._on_update_description, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.CLEAR_DESCRIPTION, self._on_clear_description, weak=False)

        self.event_bus.subscribe(Events.Audio.SHOW_VC_REDIST_DIALOG, self._on_show_vc_redist_dialog, weak=False)
        self.event_bus.subscribe(Events.Audio.SHOW_TRITON_DIALOG, self._on_show_triton_dialog, weak=False)

    def _backend(self):
        return self._service_or_none("voice_model_controller")

    def _attach_view_to_dialog(self, dialog):
        if not dialog or not hasattr(dialog, "layout") or dialog.layout() is None:
            return
        if not self._vm_view:
            return

        try:
            if self._vm_view.parent() is not None:
                self._vm_view.setParent(None)
        except Exception:
            pass

        layout = dialog.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        layout.addWidget(self._vm_view)

    def _on_voice_models_dialog_ready(self, dialog, payload: dict):
        self._dialog = dialog
        self._attach_view_to_dialog(dialog)
        if self._vm_view:
            QTimer.singleShot(0, self._view_model.refresh)

    def _on_legacy_open_voice_models(self, event: Event):
        self.event_bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "ai_hub", "payload": {"category": "tts"}})

    def _ask_question_in_vm_view(self, title: str, message: str) -> bool:
        parent = self._dialog or self._vm_view or self.view
        reply = QMessageBox.question(
            parent,
            str(title),
            str(message),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_install_model(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        model_id = data.get("model_id")
        if not model_id:
            return False

        backend = self._backend()
        if backend is None:
            logger.error("VoiceModelGuiController: backend VoiceModelController не инициализирован.")
            return False

        try:
            preflight = backend.get_install_preflight(str(model_id))
        except Exception as exc:
            logger.warning(f"VoiceModelGuiController: install preflight failed for '{model_id}': {exc}")
            preflight = {}

        if preflight.get("blocked"):
            self.event_bus.emit(
                Events.GUI.SHOW_ERROR_MESSAGE,
                {
                    "title": preflight.get("title") or _("Ошибка установки", "Installation error"),
                    "message": preflight.get("message") or _("Установка этой модели сейчас недоступна.", "This model cannot be installed right now."),
                },
            )
            return False

        if preflight.get("ask"):
            proceed = self._ask_question_in_vm_view(
                str(preflight.get("title") or _("Backend не установлен", "Backend missing")),
                str(preflight.get("message") or ""),
            )
            if not proceed:
                cancel_message = str(preflight.get("cancel_message") or "").strip()
                if cancel_message:
                    self.event_bus.emit(
                        Events.GUI.SHOW_INFO_MESSAGE,
                        {
                            "title": _("Установка отменена", "Installation cancelled"),
                            "message": cancel_message,
                        },
                    )
                return False

        backend.start_install(
            str(model_id),
            with_ui=bool(data.get("with_ui", True)),
            timeout_sec=float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC),
        )
        return True

    def _on_uninstall_model(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        model_id = data.get("model_id")
        if not model_id:
            return False

        backend = self._backend()
        if backend is None:
            logger.error("VoiceModelGuiController: backend VoiceModelController не инициализирован.")
            return False

        voice_models = services().get_optional(VoiceModelService)
        models = voice_models.model_catalog_snapshot() if voice_models is not None else []
        model_data = next((m for m in models if m.get("id") == model_id), None)
        model_name = (model_data or {}).get("name", model_id)

        local_voice = services().get_optional(LocalVoiceService)
        is_initialized = bool(
            local_voice and local_voice.check_initialized(str(model_id), strict=True)
        )

        if is_initialized:
            self.event_bus.emit(
                Events.GUI.SHOW_ERROR_MESSAGE,
                {
                    "title": _("Модель Активна", "Model Active"),
                    "message": _(
                        f"Модель '{model_name}' сейчас используется или инициализирована.\n\n"
                        "Пожалуйста, перезапустите приложение полностью, чтобы освободить ресурсы, "
                        "прежде чем удалять эту модель.",
                        f"Model '{model_name}' is currently in use or initialized.\n\n"
                        "Please restart the application completely to free resources "
                        "before uninstalling this model."
                    )
                }
            )
            return False

        message = _(
            f"Вы уверены, что хотите удалить модель '{model_name}'?\n\n"
            "Это действие необратимо!",
            f"Are you sure you want to uninstall the model '{model_name}'?\n\n"
            "This action is irreversible!"
        )

        confirmed = self._ask_question_in_vm_view(_("Подтверждение Удаления", "Confirm Uninstallation"), message)
        if not confirmed:
            return False

        backend.start_uninstall(
            str(model_id),
            with_ui=bool(data.get("with_ui", True)),
            timeout_sec=float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC),
        )
        return True

    def _on_install_started(self, event: Event):
        model_id = (event.data or {}).get("model_id")
        if model_id:
            self._view_model.operation_started("install", str(model_id))

    def _on_install_finished(self, event: Event):
        payload = event.data or {}
        success = bool(payload.get("success"))
        self._view_model.operation_finished(
            success=success,
            error=str(payload.get("error") or "") or None,
        )
        if success:
            self._after_models_changed()

    def _on_uninstall_started(self, event: Event):
        model_id = (event.data or {}).get("model_id")
        if model_id:
            self._view_model.operation_started("uninstall", str(model_id))

    def _on_uninstall_finished(self, event: Event):
        payload = event.data or {}
        success = bool(payload.get("success"))
        self._view_model.operation_finished(
            success=success,
            error=str(payload.get("error") or "") or None,
        )
        if success:
            self._after_models_changed()

    def _on_refresh_panels_requested(self, _event: Event):
        self._view_model.refresh()

    def _on_refresh_settings_requested(self, _event: Event):
        self._view_model.refresh()

    def _on_save_settings(self, event: Event):
        backend = self._backend()
        if backend is None or self._vm_view is None:
            return

        values = self._vm_view.get_all_section_values()
        try:
            backend.save_settings_values(values)
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек локальных моделей: {e}", exc_info=True)

        self._after_models_changed()
        self._view_model.refresh()

    def _save_values(self, values: dict) -> None:
        backend = self._backend()
        if backend is None:
            raise RuntimeError("VoiceModelController is not initialized")
        backend.save_settings_values(dict(values))
        self._after_models_changed()

    def _close_with_values(self, values: dict) -> None:
        self._save_values(values)
        self.event_bus.emit(
            Events.GUI.CLOSE_WINDOW,
            {"window_id": "voice_models", "destroy": False},
        )

    def _on_close_dialog(self, event: Event):
        self._on_save_settings(event)
        self.event_bus.emit(Events.GUI.CLOSE_WINDOW, {"window_id": "voice_models", "destroy": False})

    def _after_models_changed(self):
        self.event_bus.emit(Events.Audio.REFRESH_VOICE_MODULES)
        if self.view and hasattr(self.view, "update_local_voice_combobox"):
            QTimer.singleShot(0, self.view.update_local_voice_combobox)

        settings = getattr(self.main_controller, "settings", None)
        backend = self._backend()
        if settings is None or backend is None:
            return

        try:
            installed = backend.installed_models.copy()
        except Exception:
            installed = set()

        try:
            current_model_id = settings.get("NM_CURRENT_VOICEOVER", None)
        except Exception:
            current_model_id = None

        if current_model_id and current_model_id not in installed:
            new_model_id = next(iter(installed), None) if installed else None
            try:
                settings.set("NM_CURRENT_VOICEOVER", new_model_id)
                settings.save_settings()
            except Exception:
                pass
            audio_controller = self._service_or_none("audio_controller")
            if audio_controller is not None:
                try:
                    audio_controller.current_local_voice_id = new_model_id
                except Exception:
                    pass

            if self.view and hasattr(self.view, "update_local_voice_combobox"):
                QTimer.singleShot(0, self.view.update_local_voice_combobox)

    def _on_update_description(self, event: Event):
        self._view_model.dispatch_description(event.data)

    def _on_clear_description(self, event: Event):
        self._view_model.dispatch_description(None)

    def _resolve_description(self, key) -> str:
        backend = self._backend()
        if backend is None:
            return _("Select a model to see details.", "Select a model to see details.")
        try:
            models = backend.local_voice_models
            model_ids = {m.get("id") for m in (models or [])}
            if key in model_ids:
                return str(backend.model_descriptions.get(key, backend.default_description_text))
            if key:
                return str(backend.setting_descriptions.get(key, backend.default_description_text))
            return str(backend.default_description_text)
        except Exception:
            return _("Select a model to see details.", "Select a model to see details.")

    def close(self) -> None:
        self._view_model.close()
        super().close()

    def _on_show_vc_redist_dialog(self, event: Event):
        wm = getattr(self.view, "window_manager", None) if self.view else None
        if wm is not None:
            res = wm.show_dialog_blocking("vc_redist_dialog", {})
            return res.get("choice", "close")
        logger.error("VC runtime dialog requested without WindowManager")
        return "close"

    def _on_show_triton_dialog(self, event: Event):
        deps = event.data or {}
        wm = getattr(self.view, "window_manager", None) if self.view else None
        if wm is not None:
            res = wm.show_dialog_blocking("triton_deps_dialog", {"dependencies_status": deps})
            return res.get("choice", "skip")
        logger.error("Triton dependency dialog requested without WindowManager")
        return "skip"
