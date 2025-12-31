from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QMessageBox, QInputDialog, QFileDialog, QLineEdit, QLabel,
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QDialogButtonBox
)
from PyQt6.QtGui import QTextCursor
from PyQt6.QtGui import QGuiApplication as QApplication
import qtawesome as qta

from utils import _
from core.events import get_event_bus, Events
from main_logger import logger
from .widgets import CustomPresetListItem

def wire_api_settings_logic(self):
    # Служебные поля
    self.event_bus = get_event_bus()
    self.current_preset_id = None
    self.current_preset_data = {}
    self.is_loading_preset = False
    self.original_preset_state = {}
    self.custom_presets_list_items = {}
    self.pending_changes = {}
    # self.api_settings_container уже создан в UI

    def _add_custom_preset():
        name, ok = QInputDialog.getText(self, _("Новый пресет", "New preset"),
                                        _("Название пресета:", "Preset name:"))
        if not ok or not name.strip():
            return
        
        preset_data = {
            'name': name.strip(),
            'id': None,
            'pricing': 'mixed',
            'url': '',
            'default_model': '',
            'key': '',
            'known_models': [],
            'use_request': False,
            'is_g4f': False
        }
        result = self.event_bus.emit_and_wait(Events.ApiPresets.SAVE_CUSTOM_PRESET,
                                              {'data': preset_data}, timeout=1.0)
        if not result or not result[0]:
            logger.error("Failed to create new preset")
            return

    def _remove_custom_preset():
        current_item = self.custom_presets_list.currentItem()
        if not current_item or not isinstance(current_item, CustomPresetListItem):
            return
        
        if current_item.has_changes:
            reply = QMessageBox.question(self, _("Несохраненные изменения", "Unsaved changes"),
                                         _("Есть несохраненные изменения. Удалить пресет?",
                                           "There are unsaved changes. Delete preset?"),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        reply = QMessageBox.question(self, _("Удалить пресет", "Delete preset"),
                                     _("Удалить выбранный пресет?", "Delete selected preset?"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.event_bus.emit(Events.ApiPresets.DELETE_CUSTOM_PRESET, {'id': current_item.preset_id})

    def _move_preset_up():
        current_row = self.custom_presets_list.currentRow()
        if current_row > 0:
            item = self.custom_presets_list.takeItem(current_row)
            self.custom_presets_list.insertItem(current_row - 1, item)
            self.custom_presets_list.setCurrentItem(item)
            _save_presets_order()

    def _move_preset_down():
        current_row = self.custom_presets_list.currentRow()
        if current_row < self.custom_presets_list.count() - 1:
            item = self.custom_presets_list.takeItem(current_row)
            self.custom_presets_list.insertItem(current_row + 1, item)
            self.custom_presets_list.setCurrentItem(item)
            _save_presets_order()

    def _save_presets_order():
        order = []
        for i in range(self.custom_presets_list.count()):
            item = self.custom_presets_list.item(i)
            if isinstance(item, CustomPresetListItem):
                order.append(item.preset_id)
        self.event_bus.emit(Events.ApiPresets.SAVE_PRESETS_ORDER, {'order': order})

    def _on_custom_preset_selection_changed():
        if self.is_loading_preset:
            return
        current_item = self.custom_presets_list.currentItem()
        
        if self.current_preset_id and self.current_preset_id in self.custom_presets_list_items:
            old_item = self.custom_presets_list_items[self.current_preset_id]
            if old_item.has_changes:
                reply = QMessageBox.question(
                    self, _("Несохраненные изменения", "Unsaved changes"),
                    _("Сохранить изменения?", "Save changes?"),
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No |
                    QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    self.custom_presets_list.setCurrentItem(old_item)
                    return
                elif reply == QMessageBox.StandardButton.Yes:
                    _save_preset()
        
        if current_item and isinstance(current_item, CustomPresetListItem):
            self.remove_preset_btn.setEnabled(True)
            self.move_up_btn.setEnabled(self.custom_presets_list.currentRow() > 0)
            self.move_down_btn.setEnabled(self.custom_presets_list.currentRow() < self.custom_presets_list.count() - 1)
            _load_preset(current_item.preset_id)
            if self.api_settings_container:
                self.api_settings_container.setVisible(True)
        else:
            self.remove_preset_btn.setEnabled(False)
            self.move_up_btn.setEnabled(False)
            self.move_down_btn.setEnabled(False)
            if self.api_settings_container:
                self.api_settings_container.setVisible(False)

    def _select_custom_preset(preset_id):
        for i in range(self.custom_presets_list.count()):
            item = self.custom_presets_list.item(i)
            if isinstance(item, CustomPresetListItem) and item.preset_id == preset_id:
                self.custom_presets_list.setCurrentItem(item)
                break

    def _export_preset():
        if self.current_preset_id:
            path, _ = QFileDialog.getSaveFileName(
                self, _("Экспорт пресета", "Export preset"),
                f"preset_{self.current_preset_id}.json",
                "JSON Files (*.json)"
            )
            if path:
                self.event_bus.emit(Events.ApiPresets.EXPORT_PRESET, {
                    'id': self.current_preset_id,
                    'path': path
                })

    def _save_preset():
        if not self.current_preset_id or self.current_preset_id not in self.custom_presets_list_items:
            return

        data = self.current_preset_data.copy()
        data['url'] = self.api_url_entry.text()
        data['default_model'] = self.api_model_entry.text()
        data['key'] = self.api_key_entry.text()
        data['known_models'] = self.current_preset_data.get('known_models', [])

        reserve_keys_text = self.nm_api_key_res_label.toPlainText() if hasattr(self, 'nm_api_key_res_label') else ""
        data['reserve_keys'] = [k.strip() for k in reserve_keys_text.split('\n') if k.strip()]

        if self.gemini_case_checkbox and self.current_preset_data.get('gemini_case') is None:
            data['gemini_case_override'] = self.gemini_case_checkbox.isChecked()

        if self.template_combo.currentData():
            data['base'] = self.template_combo.currentData()
        else:
            data['base'] = None

        new_id = self.event_bus.emit_and_wait(
            Events.ApiPresets.SAVE_CUSTOM_PRESET,
            {'data': data},
            timeout=1.0
        )
        if new_id and new_id[0]:
            self.original_preset_state = _get_current_state()
            _check_changes()
            if self.current_preset_id in self.custom_presets_list_items:
                item = self.custom_presets_list_items[self.current_preset_id]
                item.update_changes_indicator(False)
            return new_id[0]
        return None

    def _test_connection():
        base_id = self.template_combo.currentData()
        if not self.current_preset_id and not base_id:
            QMessageBox.warning(self, _("Предупреждение", "Warning"), 
                                _("Выберите пресет или шаблон для тестирования", 
                                  "Select a preset or template to test"))
            return
        
        has_test_url = False
        if self.current_preset_data and self.current_preset_data.get('test_url'):
            has_test_url = True
        elif base_id:
            template_data = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL,
                                                         {'id': base_id}, timeout=1.0)
            if template_data and template_data[0] and template_data[0].get('test_url'):
                has_test_url = True
        
        if not has_test_url:
            QMessageBox.warning(self, _("Предупреждение", "Warning"),
                                _("Тестирование недоступно для данного пресета/шаблона",
                                  "Testing is not available for this preset/template"))
            return
        
        self.test_button.setEnabled(False)
        self.test_button.setText(_("Тестирование...", "Testing..."))
        logger.info(f"Initiating test connection for preset {self.current_preset_id} with base {base_id}")
        
        self.event_bus.emit(Events.ApiPresets.TEST_CONNECTION, {
            'id': self.current_preset_id,
            'base': base_id,
            'key': self.api_key_entry.text()
        })
    
    def _toggle_key_visibility():
        if self.api_key_entry.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Normal)
            self.key_visibility_button.setIcon(qta.icon('fa5s.eye-slash'))
        else:
            self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
            self.key_visibility_button.setIcon(qta.icon('fa5s.eye'))
    
    def _on_template_changed():
        if self.is_loading_preset:
            return
        
        template_id = self.template_combo.currentData()
        if not self.current_preset_id:
            return
        
        if template_id is None:
            self.api_url_entry.setEnabled(True)
            for label in [self.url_help_label, self.model_help_label, self.key_help_label]:
                label.setVisible(False)
            self.test_button.setVisible(False)
            
            for field in ['api_url_entry', 'api_model_entry', 'api_key_entry', 'nm_api_key_res_label']:
                frame = getattr(self, f"{field}_frame", None)
                if frame:
                    frame.setVisible(True)  
            for field in ['g4f_version_entry', 'g4f_update_button']:
                frame = getattr(self, f"{field}_frame", None)
                if frame:
                    frame.setVisible(False)
            if self.gemini_case_checkbox:
                frame = getattr(self, "gemini_case_checkbox_frame", None)
                if frame:
                    frame.setVisible(True)
            
            self.current_preset_data['base'] = None
            self.current_preset_data['is_g4f'] = False
            self.current_preset_data['use_request'] = False
            self.current_preset_data['gemini_case'] = None
            self.current_preset_data['test_url'] = ''
            self.current_preset_data['url_tpl'] = ''
            self.current_preset_data['add_key'] = False
            self.current_preset_data['help_url'] = ''
            _check_changes()
            return
        
        template_data = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL,
                                                     {'id': template_id}, timeout=1.0)
        if not template_data or not template_data[0]:
            return
        
        template = template_data[0]
        self.is_loading_preset = True
        
        # ставим дефолтную модель нового шаблона
        default_model = template.get('default_model', '')
        self.api_model_entry.setText(default_model)  # Даже если пустая строка
        
        url_tpl = template.get('url_tpl', '')
        if url_tpl:
            current_model = self.api_model_entry.text()
            if not current_model:
                current_model = template.get('default_model', '')
                self.api_model_entry.setText(current_model)
            if '{model}' in url_tpl:
                url = url_tpl.format(model=current_model)
            else:
                url = url_tpl
            
            import re
            if template.get('add_key'):
                current_key = self.api_key_entry.text().strip()
                if current_key:
                    if 'key=' not in url:
                        sep = '&' if '?' in url else '?'
                        url = f"{url}{sep}key={current_key}"
                    else:
                        url = re.sub(r'key=[^&]*', f'key={current_key}', url)
                else:
                    url = re.sub(r'[?&]key=[^&]*', '', url)
                    url = url.rstrip('?&')
            self.api_url_entry.setText(url)
        else:
            url = template.get('url', '')
            self.api_url_entry.setText(url)
        
        self.api_url_entry.setEnabled(False)
        is_g4f = template.get('is_g4f', False)
        
        for field in ['api_url_entry', 'api_key_entry', 'nm_api_key_res_label']:
            frame = getattr(self, f"{field}_frame", None)
            if frame:
                frame.setVisible(not is_g4f)
        model_frame = getattr(self, "api_model_entry_frame", None)
        if model_frame:
            model_frame.setVisible(True)
        if self.gemini_case_checkbox:
            frame = getattr(self, "gemini_case_checkbox_frame", None)
            if frame:
                frame.setVisible(template.get('gemini_case') is None and not is_g4f)
        for field in ['g4f_version_entry', 'g4f_update_button']:
            frame = getattr(self, f"{field}_frame", None)
            if frame:
                frame.setVisible(is_g4f)
        
        self.test_button.setVisible(bool(template.get('test_url')))
        
        if template.get('documentation_url') or template.get('models_url') or template.get('key_url'):
            doc_url = template.get('documentation_url', '')
            models_url = template.get('models_url', '')
            key_url = template.get('key_url', '')
            if doc_url:
                self.url_help_label.setVisible(True)
                self.url_help_label.setText(f'<a href="{doc_url}">{_("Документация", "Documentation")}</a>')
            else:
                self.url_help_label.setVisible(False)
            if models_url:
                self.model_help_label.setVisible(True)
                self.model_help_label.setText(f'<a href="{models_url}">{_("Список моделей", "Models list")}</a>')
            else:
                self.model_help_label.setVisible(False)
            if key_url:
                self.key_help_label.setVisible(True)
                self.key_help_label.setText(f'<a href="{key_url}">{_("Получить ключ", "Get API key")}</a>')
            else:
                self.key_help_label.setVisible(False)
        else:
            for label in [self.url_help_label, self.model_help_label, self.key_help_label]:
                label.setVisible(False)
        
        known_models = template.get('known_models', [])
        if known_models:
            self.api_model_list_model.setStringList(known_models)
            # Обновляем модель автодополнения для QLineEdit
            current_text = self.api_model_entry.text()
            self.api_model_entry.completer().setModel(self.api_model_list_model)
            self.api_model_entry.setText(current_text)

        # Устанавливаем модель по умолчанию только если поле пустое
        current_model = self.api_model_entry.text()
        if not current_model:
            default_model = template.get('default_model', '')
            if default_model:
                self.api_model_entry.setText(default_model)

        self.current_preset_data['base'] = template_id
        self.current_preset_data['is_g4f'] = is_g4f
        self.current_preset_data['use_request'] = template.get('use_request', False)
        self.current_preset_data['gemini_case'] = template.get('gemini_case')
        self.current_preset_data['test_url'] = template.get('test_url', '')
        self.current_preset_data['url_tpl'] = template.get('url_tpl', '')
        self.current_preset_data['add_key'] = template.get('add_key', False)
        self.current_preset_data['documentation_url'] = template.get('documentation_url', '')
        self.current_preset_data['models_url'] = template.get('models_url', '')
        self.current_preset_data['key_url'] = template.get('key_url', '')
        
        self.is_loading_preset = False
        _check_changes()

    def _cancel_changes():
        if not self.current_preset_id or not self.original_preset_state:
            return
        self.is_loading_preset = True
        self.api_url_entry.setText(self.original_preset_state.get('url', ''))
        self.api_model_entry.setText(self.original_preset_state.get('model', ''))
        self.api_key_entry.setText(self.original_preset_state.get('key', ''))
        if hasattr(self, 'nm_api_key_res_label'):
            reserve_keys = self.original_preset_state.get('reserve_keys', [])
            self.nm_api_key_res_label.setPlainText('\n'.join(reserve_keys))
        original_base = self.original_preset_state.get('base')
        if original_base:
            for i in range(self.template_combo.count()):
                if self.template_combo.itemData(i) == original_base:
                    self.template_combo.setCurrentIndex(i)
                    break
        else:
            self.template_combo.setCurrentIndex(0)
        self.is_loading_preset = False
        _check_changes()
        if self.current_preset_id in self.custom_presets_list_items:
            item = self.custom_presets_list_items[self.current_preset_id]
            item.update_changes_indicator(False)

    def _load_preset(preset_id):
        self.is_loading_preset = True

        preset_data = self.event_bus.emit_and_wait(
            Events.ApiPresets.GET_PRESET_FULL,
            {'id': preset_id}, timeout=1.0
        )
        if not preset_data or not preset_data[0]:
            self.is_loading_preset = False
            return

        preset = preset_data[0]
        self.current_preset_data = preset
        self.current_preset_id = preset_id

        is_custom = preset_id in self.custom_presets_list_items

        state = self.event_bus.emit_and_wait(
            Events.ApiPresets.LOAD_PRESET_STATE,
            {'id': preset_id}, timeout=1.0
        )
        state = state[0] if state and state[0] else {}

        model = state.get('model', preset.get('default_model', ''))
        key = state.get('key', preset.get('key', ''))

        self.api_model_entry.setText(model)
        self.api_key_entry.setText(key)

        if hasattr(self, 'nm_api_key_res_label'):
            reserve_keys = state.get('reserve_keys', preset.get('reserve_keys', []))
            if isinstance(reserve_keys, list):
                self.nm_api_key_res_label.setPlainText('\n'.join(reserve_keys))
            else:
                self.nm_api_key_res_label.setPlainText('')

        if self.gemini_case_checkbox and preset.get('gemini_case') is None:
            if 'gemini_case' in state:
                checked = bool(state.get('gemini_case'))
            else:
                checked = bool(preset.get('gemini_case_override', False))
            self.gemini_case_checkbox.setChecked(checked)

        base = preset.get('base')
        if base:
            for i in range(self.template_combo.count()):
                if self.template_combo.itemData(i) == base:
                    self.template_combo.setCurrentIndex(i)
                    break
        else:
            self.template_combo.setCurrentIndex(0)

        is_g4f = preset.get('is_g4f', False)
        has_template = base is not None

        self.api_url_entry.setEnabled(is_custom and (not is_g4f) and (not has_template))
        self.api_model_entry.setEnabled(True)
        self.api_key_entry.setEnabled(not is_g4f)

        for field in ['api_url_entry', 'api_model_entry', 'api_key_entry', 'nm_api_key_res_label']:
            frame = getattr(self, f"{field}_frame", None)
            if frame:
                frame.setVisible(not is_g4f)

        for field in ['g4f_version_entry', 'g4f_update_button']:
            frame = getattr(self, f"{field}_frame", None)
            if frame:
                frame.setVisible(is_g4f)

        if self.gemini_case_checkbox:
            frame = getattr(self, "gemini_case_checkbox_frame", None)
            if frame:
                frame.setVisible((preset.get('gemini_case') is None) and (not is_g4f))

        def _compute_url_for_display(p: dict) -> str:
            url_tpl = p.get('url_tpl') or ''
            if url_tpl:
                cur_model = self.api_model_entry.text() or p.get('default_model', '')
                url = url_tpl.format(model=cur_model) if '{model}' in url_tpl else url_tpl
                if p.get('add_key'):
                    cur_key = self.api_key_entry.text().strip()
                    if cur_key:
                        sep = '&' if '?' in url else '?'
                        url = f"{url}{sep}key={cur_key}"
                return url
            return p.get('url', '')

        if has_template:
            display_url = _compute_url_for_display(preset)
            self.api_url_entry.setText(display_url)
        else:
            manual_url = state.get('url', preset.get('url', ''))
            self.api_url_entry.setText(manual_url)

        self.test_button.setVisible(bool(preset.get('test_url')))

        self.provider_label.setText(f"{_('Пресет', 'Preset')}: {preset.get('name', '')}")

        if preset.get('documentation_url') or preset.get('models_url') or preset.get('key_url'):
            doc_url = preset.get('documentation_url', '')
            models_url = preset.get('models_url', '')
            key_url = preset.get('key_url', '')

            if doc_url:
                self.url_help_label.setVisible(True)
                self.url_help_label.setText(f'<a href="{doc_url}">{_("Документация", "Documentation")}</a>')
            else:
                self.url_help_label.setVisible(False)

            if models_url:
                self.model_help_label.setVisible(True)
                self.model_help_label.setText(f'<a href="{models_url}">{_("Список моделей", "Models list")}</a>')
            else:
                self.model_help_label.setVisible(False)

            if key_url:
                self.key_help_label.setVisible(True)
                self.key_help_label.setText(f'<a href="{key_url}">{_("Получить ключ", "Get API key")}</a>')
            else:
                self.key_help_label.setVisible(False)
        else:
            for label in [self.url_help_label, self.model_help_label, self.key_help_label]:
                label.setVisible(False)

        known_models = preset.get('known_models', [])
        if known_models:
            self.api_model_list_model.setStringList(known_models)
            current_text = self.api_model_entry.text()
            self.api_model_entry.completer().setModel(self.api_model_list_model)
            self.api_model_entry.setText(current_text)

        self.settings.set("LAST_API_PRESET_ID", preset_id)
        self.settings.save_settings()

        self.original_preset_state = _get_current_state()

        self.save_preset_button.setVisible(is_custom)
        self.save_preset_button.setEnabled(False)

        self.is_loading_preset = False
        _check_changes()

    def _get_current_state():
        state = {
            'url': self.api_url_entry.text(),
            'model': self.api_model_entry.text(),
            'key': self.api_key_entry.text(),
            'base': self.template_combo.currentData()
        }
        if hasattr(self, 'nm_api_key_res_label'):
            reserve_keys_text = self.nm_api_key_res_label.toPlainText()
            state['reserve_keys'] = [k.strip() for k in reserve_keys_text.split('\n') if k.strip()]
        else:
            state['reserve_keys'] = []
        if self.gemini_case_checkbox and self.current_preset_data.get('gemini_case') is None:
            state['gemini_case'] = self.gemini_case_checkbox.isChecked()
        return state
    
    def _check_changes():
        if not self.current_preset_id or self.current_preset_id not in self.custom_presets_list_items:
            return
        
        current_state = _get_current_state()
        has_changes = current_state != self.original_preset_state
        
        if self.current_preset_id in self.custom_presets_list_items:
            item = self.custom_presets_list_items[self.current_preset_id]
            if item.has_changes != has_changes:
                item.update_changes_indicator(has_changes)
        
        if hasattr(self, 'api_url_entry_frame'):
            url_layout = self.api_url_entry_frame.layout()
            if url_layout and url_layout.count() > 1:
                h_layout = url_layout.itemAt(1).layout()
                if h_layout:
                    for i in range(h_layout.count()):
                        widget = h_layout.itemAt(i).widget()
                        if isinstance(widget, QLabel) and not widget.openExternalLinks():
                            url_changed = current_state['url'] != self.original_preset_state.get('url', '')
                            if url_changed:
                                widget.setText(_('Ссылка API*', 'API URL*'))
                                widget.setStyleSheet("color: #f39c12; font-weight: bold;")
                            else:
                                widget.setText(_('Ссылка API', 'API URL'))
                                widget.setStyleSheet("")
                            break
        if hasattr(self, 'api_model_entry_frame'):
            model_layout = self.api_model_entry_frame.layout()
            if model_layout and model_layout.count() > 1:
                h_layout = model_layout.itemAt(1).layout()
                if h_layout:
                    for i in range(h_layout.count()):
                        widget = h_layout.itemAt(i).widget()
                        if isinstance(widget, QLabel) and not widget.openExternalLinks():
                            model_changed = current_state['model'] != self.original_preset_state.get('model', '')
                            if model_changed:
                                widget.setText(_('Модель*', 'Model*'))
                                widget.setStyleSheet("color: #f39c12; font-weight: bold;")
                            else:
                                widget.setText(_('Модель', 'Model'))
                                widget.setStyleSheet("")
                            break
        if hasattr(self, 'api_key_entry_frame'):
            key_layout = self.api_key_entry_frame.layout()
            if key_layout and key_layout.count() > 1:
                h_layout = key_layout.itemAt(1).layout()
                if h_layout:
                    for i in range(h_layout.count()):
                        widget = h_layout.itemAt(i).widget()
                        if isinstance(widget, QLabel) and not widget.openExternalLinks():
                            key_changed = current_state['key'] != self.original_preset_state.get('key', '')
                            if key_changed:
                                widget.setText(_('API Ключ*', 'API Key*'))
                                widget.setStyleSheet("color: #f39c12; font-weight: bold;")
                            else:
                                widget.setText(_('API Ключ', 'API Key'))
                                widget.setStyleSheet("")
                            break
        if hasattr(self, 'nm_api_key_res_label_frame'):
            reserve_layout = self.nm_api_key_res_label_frame.layout()
            if reserve_layout and reserve_layout.count() > 0:
                for i in range(reserve_layout.count()):
                    widget = reserve_layout.itemAt(i).widget()
                    if isinstance(widget, QLabel) and not widget.openExternalLinks():
                        current_reserve = current_state.get('reserve_keys', [])
                        original_reserve = self.original_preset_state.get('reserve_keys', [])
                        reserve_changed = current_reserve != original_reserve
                        if reserve_changed:
                            widget.setText(_('Резервные ключи*', 'Reserve keys*'))
                            widget.setStyleSheet("color: #f39c12; font-weight: bold;")
                        else:
                            widget.setText(_('Резервные ключи', 'Reserve keys'))
                            widget.setStyleSheet("")
                        break
        
        self.save_preset_button.setEnabled(has_changes)
        self.save_preset_button.setVisible(True)
        if has_changes:
            self.save_preset_button.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    font-weight: bold;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:hover { background-color: #229954; }
                QPushButton:pressed { background-color: #1e8449; }
            """)
        else:
            self.save_preset_button.setStyleSheet("""
                QPushButton {
                    background-color: #95a5a6;
                    color: #ecf0f1;
                    font-weight: normal;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:disabled {
                    background-color: #7f8c8d;
                    color: #bdc3c7;
                }
            """)
        self.cancel_button.setVisible(has_changes)

    def _on_field_changed():
        if self.is_loading_preset:
            return
        _check_changes()
        if self.current_preset_data and not self.api_url_entry.isEnabled():
            url_tpl = self.current_preset_data.get('url_tpl')
            if url_tpl:
                model = self.api_model_entry.text()
                url = url_tpl.format(model=model) if '{model}' in url_tpl else url_tpl
                if self.current_preset_data.get('add_key'):
                    key = self.api_key_entry.text().strip()
                    import re
                    if key:
                        if 'key=' not in url:
                            sep = '&' if '?' in url else '?'
                            url = f"{url}{sep}key={key}"
                        else:
                            url = re.sub(r'key=[^&]*', f'key={key}', url)
                    else:
                        url = re.sub(r'[?&]key=[^&]*', '', url)
                        url = url.rstrip('?&')
                self.is_loading_preset = True
                self.api_url_entry.setText(url)
                self.is_loading_preset = False
                _check_changes()

    def _load_presets():
        presets_meta = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        if not presets_meta or not presets_meta[0]:
            return
        presets_meta = presets_meta[0]
        
        self.builtin_preset_ids = set()
        builtin_presets = presets_meta.get('builtin', [])
        for preset in builtin_presets:
            self.builtin_preset_ids.add(preset.id)
        
        self.provider_delegate.set_presets_meta(builtin_presets + presets_meta.get('custom', []))
        self.template_combo.clear()
        self.template_combo.addItem(_("Без шаблона", "No template"), None)
        
        current_changes = {}
        for preset_id, item in self.custom_presets_list_items.items():
            if item.has_changes:
                current_changes[preset_id] = True
        
        self.custom_presets_list.blockSignals(True)
        self.custom_presets_list.clear()
        self.custom_presets_list_items.clear()
        self.custom_presets_list.blockSignals(False)
        
        custom_presets = presets_meta.get('custom', [])
        for preset in builtin_presets:
            self.template_combo.addItem(preset.name, preset.id)
        for preset in custom_presets:
            has_changes = current_changes.get(preset.id, False)
            item = CustomPresetListItem(preset.id, preset.name, has_changes)
            self.custom_presets_list.addItem(item)
            self.custom_presets_list_items[preset.id] = item
            logger.info(f"Added custom preset to list: {preset.name} (ID: {preset.id})")
        
        saved_id = self.settings.get("LAST_API_PRESET_ID", 0)
        if saved_id and saved_id in self.custom_presets_list_items:
            _select_custom_preset(saved_id)
        elif self.custom_presets_list.count() == 0:
            if self.api_settings_container:
                self.api_settings_container.setVisible(False)

    def _save_current_state():
        if self.current_preset_id and self.current_preset_id > 0:
            state = {
                'url': self.api_url_entry.text(),
                'model': self.api_model_entry.text(),
                'key': self.api_key_entry.text()
            }
            if self.gemini_case_checkbox and self.current_preset_data.get('gemini_case') is None:
                state['gemini_case'] = self.gemini_case_checkbox.isChecked()
            self.event_bus.emit(Events.ApiPresets.SAVE_PRESET_STATE, {
                'id': self.current_preset_id,
                'state': state
            })
            
    def _on_key_changed():
        if self.is_loading_preset:
            return
        _save_current_state()
        _check_changes()
        if self.current_preset_data and self.current_preset_data.get('add_key'):
            _on_field_changed()
    
    def _on_gemini_case_changed():
        if self.is_loading_preset:
            return
        _check_changes()
    
    def _on_test_result(event):
        data = event.data
        if data.get('id') != self.current_preset_id:
            return
        logger.info(f"Received test result in UI for {self.current_preset_id}: {data}")
        self.test_result_received.emit(data)

    def _process_test_result(data):
        self.test_button.setEnabled(True)
        self.test_button.setText(_("Тест подключения", "Test connection"))
        logger.info(f"Handling test result in UI: success={data.get('success')}, message={data.get('message')}")
        
        if data.get('success'):
            models = data.get('models', [])
            current_template = self.template_combo.currentText().lower()
            current_url = self.api_url_entry.text().lower()

            # Определяем провайдера
            is_ai_io = "ai.io" in current_template or "intelligence.io" in current_url
            is_openrouter = 'openrouter' in current_template
        
            # Для AI.IO и OpenRouter обрабатываем модели
            if is_ai_io or is_openrouter:
                logger.info(f"Logic: {'AI.IO' if is_ai_io else 'OpenRouter'} detected. Processing models...")
            
                # Карта префиксов (общая для обоих провайдеров)
                prefix_map = {
                    "trinity": "arcee-ai/",
                    "tng-": "tngtech/",
                    "kimi-k2": "moonshotai/",
                    "deepseek": "deepseek-ai/",
                    "glm-4": "zai-org/",
                    "llama-3": "meta-llama/",
                    "llama-4": "meta-llama/",
                    "gpt-oss": "openai/",
                    "qwen2": "Qwen/",
                    "qwen3": "Qwen/",
                    "qwen-2.5": "Qwen/",
                    "mistral": "mistralai/",
                    "devstral": "mistralai/",
                    "magistral": "mistralai/",
                    "olmo-": "allenai/",
                    "nemotron": "nvidia/",
                    "mimo-": "xiaomi/",
                    "kat-coder": "kwaipilot/",
                    "tongyi": "alibaba/",
                    "dolphin-": "cognitivecomputations/",
                    "gemma": "google/",
                    "gemini": "google/",
                    "claude": "anthropic/",
                    "command": "cohere/",
                    "dbrx": "databricks/",
                    "amazon": "amazon/",
                    "jamba": "ai21/",
                    "bert": "openrouter/"
                }

                fixed_models = []
                for m in models:
                    # Извлекаем ID модели в зависимости от формата
                    m_id = ''
                    if isinstance(m, dict):
                        # Для словарей берем 'id' или 'name'
                        m_id = m.get('id', m.get('name', ''))
                    else:
                        # Для строк просто используем значение
                        m_id = str(m).strip()
                    
                    if not m_id:
                        continue
                    
                    # Добавляем префикс, если его нет
                    if "/" not in m_id:
                        m_lower = m_id.lower()
                        for key, prefix in prefix_map.items():
                            if key in m_lower:
                                m_id = prefix + m_id
                                break
                    
                    fixed_models.append(m_id)
                
                # Подменяем список на исправленный
                models = fixed_models
                # Сохраняем обратно в data, чтобы при сохранении пресета записалось полное имя
                data['models'] = fixed_models

            # РАБОТА С ПРОБЛЕМНЫМИ МОДЕЛЯМИ
            is_openrouter_temp = False
            if 'openrouter' in current_template:
                is_openrouter_temp = True
            elif models and len(models) > 0:
                first_model = str(models[0]).lower()
                if ":free" in first_model:
                    is_openrouter_temp = True
            
            if is_openrouter_temp:
                logger.info("Logic: OpenRouter detected. Applying specific fixes...")
                fixed_models = []
                for m in models:
                    # Извлекаем строку из словаря или просто берём строку
                    m_str = m.get('id', '') if isinstance(m, dict) else str(m)
                    m_str = m_str.strip()
                    
                    # Конкретные замены для проблемных моделей OpenRouter (Можно добавить другие замены здесь)
                    if "deepseek-v3.1-nex-n1" in m_str:
                        # Заменяем ЛЮБОЙ префикс перед моделью на правильный
                        m_str = "nex-agi/deepseek-v3.1-nex-n1" + m_str.split("deepseek-v3.1-nex-n1")[-1]
                    elif "hermes-3-llama-3.1-405b" in m_str:
                        m_str = "nousresearch/hermes-3-llama-3.1-405b" + m_str.split("hermes-3-llama-3.1-405b")[-1]
                    elif "glm-4.5-air" in m_str:
                        m_str = "z-ai/glm-4.5-air" + m_str.split("glm-4.5-air")[-1]
                    elif "deepseek-r1t2-chimera" in m_str:
                        m_str = "tngtech/deepseek-r1t2-chimera" + m_str.split("deepseek-r1t2-chimera")[-1]
                    elif "deepseek-r1-0528" in m_str:
                        m_str = "deepseek/deepseek-r1-0528" + m_str.split("deepseek-r1-0528")[-1]
                    elif "deepseek-r1t-chimera" in m_str:
                        m_str = "tngtech/deepseek-r1t-chimera" + m_str.split("deepseek-r1t-chimera")[-1]
                    elif "dolphin-mistral-24b-venice-edition" in m_str:
                        m_str = "cognitivecomputations/dolphin-mistral-24b-venice-edition" + m_str.split("dolphin-mistral-24b-venice-edition")[-1]
                    
                    fixed_models.append(m_str)
                
                models = fixed_models
                data['models'] = fixed_models

            # Формируем текст для окошка
            model_texts = []
            for i, model_name in enumerate(models[:150], 1):
                model_texts.append(f"{i}. {model_name}")
            
            model_text = '\n'.join(model_texts)
            if len(models) > 150:
                model_text += f"\n... и еще {len(models) - 150} моделей"
            
            # Заголовок сообщения
            if is_openrouter:
                message = f"✅ Подключение успешно\n\n"
                message += f"📊 Найдено бесплатных моделей OpenRouter: {len(models)}"
                message += f"\n\n💡 Бесплатные модели имеют лимиты (~50 запросов в день)."
            else:
                message = f"✅ Подключение успешно\nНайдено моделей: {len(models)}"
            
            # Создаем диалог для отображения списка моделей
            dialog = QDialog(self)
            dialog.setWindowTitle(_("Результат тестирования", "Test Result"))
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            # Сообщение об успехе
            success_label = QLabel(message)
            success_label.setStyleSheet("font-weight: bold; color: #27ae60;")
            success_label.setWordWrap(True)
            layout.addWidget(success_label)
            
            # Поле со списком моделей для копирования
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(model_text)
            text_edit.setMinimumHeight(400)
            text_edit.setMinimumWidth(500)
            layout.addWidget(text_edit)
            
            # Кнопки
            button_box = QDialogButtonBox()
            copy_button = QPushButton(_("Копировать список", "Copy list"))
            ok_button = QPushButton("OK")
            ok_button.setDefault(True)
            
            button_box.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
            button_box.addButton(ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
            layout.addWidget(button_box)
            
            # Сигналы
            def copy_to_clipboard():
                clipboard = QApplication.clipboard()
                clipboard.setText(model_text)
                copy_button.setText(_("Скопировано!", "Copied!"))
                QTimer.singleShot(1500, lambda: copy_button.setText(_("Копировать список", "Copy list")))
            
            copy_button.clicked.connect(copy_to_clipboard)
            ok_button.clicked.connect(dialog.accept)
            
            dialog.exec()
        else:
            error_message = data.get('message', _('Неизвестная ошибка', 'Unknown error'))
            detailed_message = _("Не удалось подключиться к API", "Failed to connect to API")
            detailed_message += f"\n\n{_('Причина:', 'Reason:')} {error_message}"
            
            # Диалог для ошибок тоже с возможностью копирования
            dialog = QDialog(self)
            dialog.setWindowTitle(_("Ошибка подключения", "Connection Error"))
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            error_label = QLabel(f"❌ {detailed_message}")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)
            
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(detailed_message)
            text_edit.setMaximumHeight(150)
            layout.addWidget(text_edit)
            
            button_box = QDialogButtonBox()
            copy_button = QPushButton(_("Копировать текст", "Copy text"))
            ok_button = QPushButton("OK")
            ok_button.setDefault(True)
            
            button_box.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
            button_box.addButton(ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
            layout.addWidget(button_box)
            
            def copy_error_to_clipboard():
                clipboard = QApplication.clipboard()
                clipboard.setText(detailed_message)
                copy_button.setText(_("Скопировано!", "Copied!"))
                QTimer.singleShot(1500, lambda: copy_button.setText(_("Копировать текст", "Copy text")))
            
            copy_button.clicked.connect(copy_error_to_clipboard)
            ok_button.clicked.connect(dialog.accept)
            
            dialog.exec()

    def _on_test_failed(event):
        data = event.data
        self.test_result_failed.emit(data)

    def _process_test_failed(data):
        self.test_button.setEnabled(True)
        self.test_button.setText(_("Тест подключения", "Test connection"))
        error_type = data.get('error')
        message = data.get('message', _('Неизвестная ошибка', 'Unknown error'))
        if error_type == 'no_test_url':
            QMessageBox.warning(self, _("Предупреждение", "Warning"), message)
        else:
            detailed_message = _("Не удалось выполнить тестирование", "Failed to perform test")
            detailed_message += f"\n\n{_('Причина:', 'Reason:')} {message}"
            QMessageBox.critical(self, _("Ошибка тестирования", "Test Error"), detailed_message)

    # Подключаем UI к логике
    self.custom_presets_list.itemSelectionChanged.connect(_on_custom_preset_selection_changed)
    self.add_preset_btn.clicked.connect(_add_custom_preset)
    self.remove_preset_btn.clicked.connect(_remove_custom_preset)
    self.move_up_btn.clicked.connect(_move_preset_up)
    self.move_down_btn.clicked.connect(_move_preset_down)
    self.export_button.clicked.connect(_export_preset)
    self.save_preset_button.clicked.connect(_save_preset)
    self.cancel_button.clicked.connect(_cancel_changes)
    self.test_button.clicked.connect(_test_connection)
    self.key_visibility_button.clicked.connect(_toggle_key_visibility)
    self.template_combo.currentIndexChanged.connect(_on_template_changed)

    self.api_model_entry.textChanged.connect(_on_field_changed)
    self.api_key_entry.textChanged.connect(_on_key_changed)
    self.api_url_entry.textChanged.connect(_on_field_changed)
    if hasattr(self, 'nm_api_key_res_label'):
        self.nm_api_key_res_label.textChanged.connect(_on_field_changed)
    if self.gemini_case_checkbox:
        self.gemini_case_checkbox.stateChanged.connect(_on_gemini_case_changed)

    # События шины
    self.event_bus.subscribe(Events.ApiPresets.TEST_RESULT, _on_test_result, weak=False)
    self.event_bus.subscribe(Events.ApiPresets.TEST_FAILED, _on_test_failed, weak=False)
    self.event_bus.subscribe(Events.ApiPresets.PRESET_SAVED, lambda e: (_load_presets(), _select_custom_preset(e.data.get('id')) if e.data.get('id') in self.custom_presets_list_items else None), weak=False)
    self.event_bus.subscribe(Events.ApiPresets.PRESET_DELETED, lambda e: (_load_presets(), self.custom_presets_list.setCurrentRow(0) if self.custom_presets_list.count() > 0 else self.api_settings_container.setVisible(False)), weak=False)

    # Сигналы главного окна
    self.test_result_failed.connect(_process_test_failed)
    self.test_result_received.connect(_process_test_result)

    # Первичная загрузка
    QTimer.singleShot(100, _load_presets)