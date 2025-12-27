from PyQt6.QtCore import QTimer, QEventLoop

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController
from utils import getTranslationVariant as _

from ui.windows.voice_model_view import VoiceModelSettingsView


class VoiceModelGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._vm_view: VoiceModelSettingsView | None = VoiceModelSettingsView(auto_initialize=False)
        super().__init__(main_controller, view)

        self._register_window_on_ready()

    def _register_window_on_ready(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return
        self.view.window_manager.set_dialog_on_ready("voice_models", self._on_voice_models_dialog_ready)

    def subscribe_to_events(self):
        # legacy compatibility: старые места могут продолжать эмитить этот event
        self.event_bus.subscribe(Events.Audio.OPEN_VOICE_MODEL_SETTINGS_DIALOG, self._on_legacy_open_voice_models, weak=False)

        self.event_bus.subscribe(Events.VoiceModel.INSTALL_MODEL, self._on_install_model, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.UNINSTALL_MODEL, self._on_uninstall_model, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.SAVE_SETTINGS, self._on_save_settings, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.CLOSE_DIALOG, self._on_close_dialog, weak=False)

        self.event_bus.subscribe(Events.VoiceModel.UPDATE_DESCRIPTION, self._on_update_description, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.CLEAR_DESCRIPTION, self._on_clear_description, weak=False)
        self.event_bus.subscribe(Events.VoiceModel.GET_SECTION_VALUES, self._on_get_section_values, weak=False)

        self.event_bus.subscribe(Events.Audio.SHOW_VC_REDIST_DIALOG, self._on_show_vc_redist_dialog, weak=False)
        self.event_bus.subscribe(Events.Audio.SHOW_TRITON_DIALOG, self._on_show_triton_dialog, weak=False)

    def _backend(self):
        return getattr(self.main_controller, "voice_model_controller", None)

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
            QTimer.singleShot(0, self._vm_view.refresh_all)

    def _on_legacy_open_voice_models(self, event: Event):
        self.event_bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "voice_models"})

    def _ask_question_in_vm_view(self, title: str, message: str) -> bool:
        if not self._vm_view:
            return False
        holder = {"answer": False}
        loop = QEventLoop()
        self._vm_view.ask_question_signal.emit(title, message, holder, loop)
        loop.exec()
        return bool(holder.get("answer"))

    def _create_action_window(self, title: str, status: str):
        if not self._vm_view:
            return None
        win_holder = {}
        win_loop = QEventLoop()
        self._vm_view.create_voice_action_window_signal.emit(title, status, win_holder, win_loop)
        win_loop.exec()
        return win_holder.get("window")

    def _on_install_model(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        model_id = data.get("model_id")
        if not model_id:
            return

        backend = self._backend()
        if backend is None:
            logger.error("VoiceModelGuiController: backend VoiceModelController не инициализирован.")
            return

        if self._vm_view:
            self._vm_view.install_started_signal.emit(model_id)

        try:
            models = self.event_bus.emit_and_wait(Events.VoiceModel.GET_MODEL_DATA, timeout=1.0)
            models = models[0] if models else []
            model_data = next((m for m in models if m.get("id") == model_id), None)
        except Exception:
            model_data = None

        if model_data and model_data.get("rtx30plus", False) and not backend.is_gpu_rtx30_or_40():
            gpu_info = backend.gpu_name if getattr(backend, "gpu_name", None) else "не определена"
            if getattr(backend, "detected_gpu_vendor", None) and backend.detected_gpu_vendor != "NVIDIA":
                gpu_info = f"{backend.detected_gpu_vendor} GPU"

            model_name = model_data.get("name", model_id)
            message = _(
                f"Эта модель ('{model_name}') оптимизирована для NVIDIA RTX 30xx/40xx.\n\n"
                f"Ваша видеокарта ({gpu_info}) может не обеспечить достаточной производительности.\n\n"
                "Продолжить установку?",
                f"This model ('{model_name}') is optimized for NVIDIA RTX 30xx/40xx.\n\n"
                f"Your GPU ({gpu_info}) may be insufficient.\n\n"
                "Continue installation?"
            )

            proceed = self._ask_question_in_vm_view(_("Предупреждение", "Warning"), message)
            if not proceed:
                if self._vm_view:
                    self._vm_view.install_finished_signal.emit({"model_id": model_id, "success": False})
                return

        progress_cb = data.get("progress_callback")
        status_cb = data.get("status_callback")
        log_cb = data.get("log_callback")

        success = False
        try:
            res = self.event_bus.emit_and_wait(
                Events.Audio.LOCAL_INSTALL_MODEL,
                {"model_id": model_id, "progress_callback": progress_cb, "status_callback": status_cb, "log_callback": log_cb},
                timeout=7200000.0
            )
            success = bool(res and res[0])
        except Exception as e:
            logger.error(f"INSTALL exception for {model_id}: {e}", exc_info=True)
            success = False

        try:
            backend.reload()
            backend.save_installed_models_list()
        except Exception:
            pass

        if self._vm_view:
            self._vm_view.install_finished_signal.emit({"model_id": model_id, "success": success})

        if success:
            self._after_models_changed()

    def _on_uninstall_model(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        model_id = data.get("model_id")
        if not model_id:
            return

        backend = self._backend()
        if backend is None:
            logger.error("VoiceModelGuiController: backend VoiceModelController не инициализирован.")
            return

        try:
            models = self.event_bus.emit_and_wait(Events.VoiceModel.GET_MODEL_DATA, timeout=1.0)
            models = models[0] if models else []
            model_data = next((m for m in models if m.get("id") == model_id), None)
            model_name = (model_data or {}).get("name", model_id)
        except Exception:
            model_name = model_id

        try:
            res = self.event_bus.emit_and_wait(Events.Audio.CHECK_MODEL_INITIALIZED, {"model_id": model_id}, timeout=1.0)
            is_initialized = bool(res and res[0])
        except Exception:
            is_initialized = False

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
            return

        message = _(
            f"Вы уверены, что хотите удалить модель '{model_name}'?\n\n"
            "Будут удалены основной пакет модели и зависимости, не используемые другими моделями (кроме g4f).\n\n"
            "Это действие необратимо!",
            f"Are you sure you want to uninstall the model '{model_name}'?\n\n"
            "The main model package and dependencies not used by other models (except g4f) will be removed.\n\n"
            "This action is irreversible!"
        )

        confirmed = self._ask_question_in_vm_view(_("Подтверждение Удаления", "Confirm Uninstallation"), message)
        if not confirmed:
            return

        window = self._create_action_window(
            _(f"Удаление {model_name}", f"Uninstalling {model_name}"),
            _(f"Удаление {model_name}...", f"Uninstalling {model_name}...")
        )

        __, status_cb, log_cb = window.get_threadsafe_callbacks() if window else (None, None, None)

        if self._vm_view:
            self._vm_view.uninstall_started_signal.emit(model_id)

        success = False
        try:
            res = self.event_bus.emit_and_wait(
                Events.Audio.LOCAL_UNINSTALL_MODEL,
                {"model_id": model_id, "status_callback": status_cb, "log_callback": log_cb},
                timeout=600.0
            )
            success = bool(res and res[0])
        except Exception as e:
            logger.error(f"UNINSTALL exception for {model_id}: {e}", exc_info=True)
            success = False

        try:
            backend.reload()
            backend.save_installed_models_list()
        except Exception:
            pass

        if self._vm_view:
            self._vm_view.uninstall_finished_signal.emit({"model_id": model_id, "success": success})

        if window:
            if status_cb:
                status_cb(_("Удаление завершено!", "Uninstallation complete!") if success else _("Удаление завершено с ОШИБКОЙ!", "Uninstallation failed!"))
            QTimer.singleShot(3000 if success else 5000, window.close)

        if success:
            self._after_models_changed()

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
            try:
                self.main_controller.audio_controller.current_local_voice_id = new_model_id
            except Exception:
                pass

            if self.view and hasattr(self.view, "update_local_voice_combobox"):
                QTimer.singleShot(0, self.view.update_local_voice_combobox)

    def _on_update_description(self, event: Event):
        key = event.data
        if not self._vm_view:
            return

        backend = self._backend()
        if backend is None:
            self._vm_view.update_description_signal.emit(self._vm_view._get_default_description())
            return

        try:
            models = backend.local_voice_models
            model_ids = {m.get("id") for m in (models or [])}
            if key in model_ids:
                text = backend.model_descriptions.get(key, backend.default_description_text)
            else:
                text = backend.setting_descriptions.get(key, backend.default_description_text)
        except Exception:
            text = self._vm_view._get_default_description()

        self._vm_view.update_description_signal.emit(text)

    def _on_clear_description(self, event: Event):
        if self._vm_view:
            self._vm_view.clear_description_signal.emit()

    def _on_get_section_values(self, event: Event):
        if not self._vm_view:
            return {}
        model_id = event.data
        return self._vm_view.get_section_values(model_id)

    def _on_show_vc_redist_dialog(self, event: Event):
        if not self._vm_view:
            return "close"
        holder = {}
        self._vm_view.open_vc_redist_dialog.emit(holder)
        return holder.get("choice", "close")

    def _on_show_triton_dialog(self, event: Event):
        if not self._vm_view:
            return "skip"
        deps = event.data or {}
        holder = {}
        self._vm_view.open_triton_dialog.emit(deps, holder)
        return holder.get("choice", "skip")