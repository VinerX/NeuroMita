from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from utils import _
from core.events import Events


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

        if data.get("success"):
            msg = str(data.get("message") or _("Успешно", "Success"))
            QMessageBox.information(v, _("Результат тестирования", "Test Result"), msg)
        else:
            msg = str(data.get("message") or _("Неизвестная ошибка", "Unknown error"))
            QMessageBox.warning(v, _("Ошибка подключения", "Connection Error"), msg)

    def _process_test_failed(self, data: dict):
        v = self.view
        v.test_button.setEnabled(True)
        v.test_button.setText(_("Тест подключения", "Test connection"))
        msg = str(data.get("message") or _("Неизвестная ошибка", "Unknown error"))
        QMessageBox.warning(v, _("Ошибка тестирования", "Test Error"), msg)