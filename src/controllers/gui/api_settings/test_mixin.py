from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QMenu

from utils import _
from presets.api_endpoints import resolve_api_url, resolve_test_url
from presets.model_selection import select_catalog_model
from core.networking.errors import valid_http_url
from core.events import Events
from ui.settings.api_settings.dialogs.models_loaded_dialog import ModelsLoadedDialog
from services.provider_settings import describe_protocol, list_provider_accounts


class TestMixin:
    def _load_account_models(self) -> None:
        self._test_connection(action='list_models')

    def _show_accounts(self) -> None:
        protocol_id = self._current_protocol_id_ui()

        def show(accounts):
            if protocol_id != self._current_protocol_id_ui():
                return
            menu = QMenu(self.view)
            for account in accounts:
                item = menu.addAction(str(account['label']))
                item.setCheckable(True)
                item.setChecked(bool(account['active']))
                item.triggered.connect(lambda _checked=False, aid=account['id']:
                    self._test_connection(action='select_account', account_id=aid))
            menu.addSeparator()
            menu.addAction(_("Добавить аккаунт", "Add account"), lambda: self._test_connection(action='add_account'))
            menu.addAction(_("Обновить список моделей", "Refresh models"), lambda: self._test_connection(action='list_models'))
            menu.addAction(_("Выйти", "Sign out"), lambda: self._test_connection(action='sign_out'))
            button = self.view.account_button
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

        self._bus_call_async(lambda: list_provider_accounts(protocol_id), show,
            lambda exc: QMessageBox.warning(self.view, _("Аккаунты", "Accounts"), str(exc)), name='provider-accounts')

    def _test_connection(self, *, action: str = '', account_id: str = '') -> None:
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

        test_url = resolve_test_url(
            self._active_template or {}, v.api_url_row.text(), v.api_test_url_row.text()
        )
        descriptor = describe_protocol(self._current_protocol_id_ui())
        if descriptor.connection_action == 'test_connection' and not valid_http_url(test_url):
            QMessageBox.warning(
                v,
                _("Некорректный URL проверки", "Invalid test URL"),
                _(
                    "Укажите корректный HTTP или HTTPS URL с адресом сервера.",
                    "Enter a valid HTTP or HTTPS URL with a server address.",
                ),
            )
            v.api_test_url_row.edit.setFocus()
            return
        v.test_button.setEnabled(False)
        v.test_button.setProperty("apiTesting", True)
        v.test_button.setText(_("Проверка…", "Checking…"))
        self._apply_provider_ui(self._current_protocol_id_ui())

        self.event_bus.emit(
            Events.ApiPresets.TEST_CONNECTION,
            {
                "id": self.current_preset_id,
                "base": base_id,
                "key": v.api_key_row.text(),
                "url": resolve_api_url(
                    self._active_template or {}, v.api_url_row.text()
                ),
                "test_url": v.api_test_url_row.text().strip(),
                "protocol_id": self._current_protocol_id_ui(),
                'action': action or descriptor.connection_action,
                'account_id': account_id,
            },
        )

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
        v.test_button.setProperty("apiTesting", False)
        v.test_button.setText(_("Проверить", "Check"))
        self._apply_help_links(getattr(self, "_last_help_preset", {}) or {})
        self._apply_provider_ui(self._current_protocol_id_ui())
        account = data.get('account') or {}
        if account and hasattr(v, 'account_button'):
            v.account_button.setText(str(account.get('email') if account.get('signed_in') else _("Аккаунты", "Accounts")))

        success = bool(data.get("success"))
        if success and data.get('show_plan_usage_notice'):
            QMessageBox.information(v, _("Вы используете план ChatGPT", "You're using your ChatGPT plan"), _(
                'Запросы этого провайдера расходуют вашу квоту ChatGPT/Codex. Управлять использованием можно в настройках ChatGPT.',
                'Requests from this provider use your ChatGPT/Codex allowance. Manage usage in ChatGPT settings.'))
        msg = str(data.get("message") or (_("Успешно", "Success") if success else _("Неизвестная ошибка", "Unknown error")))
        models = data.get("models") or []
        model_infos = data.get("model_infos") or []
        if not isinstance(models, list):
            models = []
        if not isinstance(model_infos, list):
            model_infos = []

        # нормализуем список
        cleaned: list[str] = []
        seen = set()
        for m in models:
            s = str(m or "").strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)

        if success and cleaned:
            preset = getattr(self, 'current_preset_data', None) or {}
            preferred = str(preset.get('preferred_model', (self._active_template or {}).get('preferred_model', '')) or '')
            if preferred or describe_protocol(self._current_protocol_id_ui()).account_actions:
                current = v.api_model_row.text().strip()
                selected = select_catalog_model(current, cleaned, preferred)
                if selected != current:
                    v.api_model_row.set_text(selected)
                    self._on_field_changed()
            try:
                v.api_model_list_model.setStringList(cleaned)
            except Exception:
                pass

            try:
                dlg = ModelsLoadedDialog(v, models=cleaned, model_infos=model_infos, message=msg)
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
        v.test_button.setProperty("apiTesting", False)
        v.test_button.setText(_("Проверить", "Check"))
        self._apply_help_links(getattr(self, "_last_help_preset", {}) or {})
        self._apply_provider_ui(self._current_protocol_id_ui())
        msg = str(data.get("message") or _("Неизвестная ошибка", "Unknown error"))
        if data.get("error") == "no_test_url":
            QMessageBox.information(
                v, _("Проверка не настроена", "Check not configured"), msg
            )
        else:
            QMessageBox.warning(v, _("Ошибка тестирования", "Test Error"), msg)
