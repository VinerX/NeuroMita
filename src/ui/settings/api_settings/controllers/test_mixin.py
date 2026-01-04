from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from utils import _
from core.events import Events
from ui.settings.api_settings.dialogs.models_loaded_dialog import ModelsLoadedDialog

class TestMixin:
    def _test_connection(self) -> None:
        v = self.view
        base_id = v.template_combo.currentData()
        try:
            base_id = int(base_id) if base_id is not None else None
        except Exception:
            base_id = None

        if not self.current_preset_id and not base_id:
            QMessageBox.warning(
                v,
                _("Предупреждение", "Warning"),
                _("Выберите пресет или шаблон для тестирования", "Select a preset or template to test"),
            )
            return

        v.test_button.setEnabled(False)
        v.test_button.setText(_("Тестирование...", "Testing..."))

        self.event_bus.emit(Events.ApiPresets.TEST_CONNECTION, {
            "id": self.current_preset_id,
            "base": base_id,
            "key": v.api_key_row.text(),
        })

    def _on_test_result(self, event):
        data = event.data or {}
        if data.get("id") != self.current_preset_id:
            return
        self.test_result_received.emit(dict(data))

    def _on_test_failed(self, event):
        data = event.data or {}
        if data.get("id") != self.current_preset_id:
            return
        self.test_result_failed.emit(dict(data))

    def _process_test_result(self, data: dict):
        v = self.view
        v.test_button.setEnabled(True)
        v.test_button.setText(_("Тест подключения", "Test connection"))

        success = bool(data.get("success"))
        msg = str(data.get("message") or (_("Успешно", "Success") if success else _("Неизвестная ошибка", "Unknown error")))
        models = data.get("models") or []
        if not isinstance(models, list):
            models = []

        # нормализуем список
        cleaned: list[str] = []
        seen = set()
        for m in models:
            s = str(m or "").strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)

        if success and cleaned:
            try:
                v.api_model_list_model.setStringList(cleaned)
            except Exception:
                pass

            try:
                dlg = ModelsLoadedDialog(v, models=cleaned, message=msg)
                if dlg.exec() == dlg.DialogCode.Accepted:
                    chosen = dlg.selected_model()
                    if chosen:
                        v.api_model_row.set_text(chosen)
                        try:
                            self._on_field_changed()
                        except Exception:
                            pass
                return
            except Exception:
                QMessageBox.information(v, _("Результат тестирования", "Test Result"), msg + "\n\n" + "\n".join(cleaned))
                return

        if success:
            QMessageBox.information(v, _("Результат тестирования", "Test Result"), msg)
        else:
            QMessageBox.warning(v, _("Ошибка подключения", "Connection Error"), msg)

    def _process_test_failed(self, data: dict):
        v = self.view
        v.test_button.setEnabled(True)
        v.test_button.setText(_("Тест подключения", "Test connection"))
        msg = str(data.get("message") or _("Неизвестная ошибка", "Unknown error"))
        QMessageBox.warning(v, _("Ошибка тестирования", "Test Error"), msg)