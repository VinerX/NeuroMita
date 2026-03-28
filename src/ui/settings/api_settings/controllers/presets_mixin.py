from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QTimer

from core.events import Events
from main_logger import logger
from utils import _


class PresetsMixin:
    def _item_cls(self):
        # Lazy import to avoid import-time crashes / circular deps
        try:
            from ui.settings.api_settings.widgets import CustomPresetListItem
            return CustomPresetListItem
        except Exception as e:
            logger.error(f"Failed to import CustomPresetListItem: {e}", exc_info=True)
            return None

    def reload_presets_async(self) -> None:
        logger.info("[API UI] reload_presets_async called")
        def _call():
            res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            logger.info(f"[API UI] GET_PRESET_LIST raw={type(res)} len={len(res) if res else 0}")
            return res[0] if res else None

        def _apply(meta):
            logger.info(f"[API UI] GET_PRESET_LIST meta={type(meta)} keys={list(meta.keys()) if isinstance(meta, dict) else None}")
            v = self.view
            Item = self._item_cls()
            if Item is None:
                v.provider_label.setText(_("Ошибка UI: не удалось загрузить виджет списка пресетов", "UI error: failed to load presets list widget"))
                return

            if not meta:
                # Most likely: ApiPresetsController not running / no subscribers / exception in controller
                v.provider_label.setText(_("Пресеты не загрузились (нет ответа от контроллера API Presets).", "Presets not loaded (no response from API Presets controller)."))
                v.api_settings_container.setVisible(False)
                v.custom_presets_list.clear()
                self.custom_presets_list_items.clear()
                return

            builtin = meta.get("builtin", []) or []
            custom = meta.get("custom", []) or []

            try:
                v.provider_delegate.set_presets_meta(builtin + custom)
            except Exception:
                pass

            # templates combo
            v.template_combo.blockSignals(True)
            v.template_combo.clear()
            v.template_combo.addItem(_("Без шаблона", "No template"), None)
            for p in builtin:
                v.template_combo.addItem(getattr(p, "name", ""), getattr(p, "id", None))
            v.template_combo.blockSignals(False)

            # keep dirty markers
            current_changes = {pid: it.has_changes for pid, it in self.custom_presets_list_items.items()}

            # custom list
            v.custom_presets_list.blockSignals(True)
            v.custom_presets_list.clear()
            self.custom_presets_list_items.clear()

            for p in custom:
                pid = getattr(p, "id", None)
                name = getattr(p, "name", "")
                if not isinstance(pid, int):
                    continue
                item = Item(pid, str(name), has_changes=bool(current_changes.get(pid, False)))
                v.custom_presets_list.addItem(item)
                self.custom_presets_list_items[pid] = item

            v.custom_presets_list.blockSignals(False)

            # restore selection
            saved_id = int(v.settings.get("LAST_API_PRESET_ID", 0) or 0)
            logger.info(f"[API UI] built list: custom_count={len(custom)} widget_count={v.custom_presets_list.count()}")
            if saved_id and saved_id in self.custom_presets_list_items:
                self._select_custom_preset(saved_id)
            else:
                v.api_settings_container.setVisible(False)

        self._bus_call_async(_call, _apply, name="load_presets")

    def _select_custom_preset(self, preset_id: int) -> None:
        v = self.view
        Item = self._item_cls()
        if Item is None:
            return
        for i in range(v.custom_presets_list.count()):
            item = v.custom_presets_list.item(i)
            if isinstance(item, Item) and item.preset_id == preset_id:
                v.custom_presets_list.setCurrentItem(item)
                return

    def _on_selection_changed(self) -> None:
        if self._is_loading_ui:
            return

        v = self.view
        Item = self._item_cls()
        if Item is None:
            return

        cur_item = v.custom_presets_list.currentItem()
        if not isinstance(cur_item, Item):
            v.remove_preset_btn.setEnabled(False)
            v.move_up_btn.setEnabled(False)
            v.move_down_btn.setEnabled(False)
            v.api_settings_container.setVisible(False)
            return

        if self.current_preset_id and self.current_preset_id in self.custom_presets_list_items:
            prev_item = self.custom_presets_list_items[self.current_preset_id]
            if prev_item.has_changes:
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    v, _("Несохраненные изменения", "Unsaved changes"),
                    _("Сохранить изменения?", "Save changes?"),
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No |
                    QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    self._select_custom_preset(self.current_preset_id)
                    return
                if reply == QMessageBox.StandardButton.Yes:
                    self._pending_select_id = int(cur_item.preset_id)
                    self._select_custom_preset(self.current_preset_id)
                    self._save_preset_async()
                    return

        v.remove_preset_btn.setEnabled(True)
        v.move_up_btn.setEnabled(v.custom_presets_list.currentRow() > 0)
        v.move_down_btn.setEnabled(v.custom_presets_list.currentRow() < v.custom_presets_list.count() - 1)

        self.load_preset_async(int(cur_item.preset_id))

    def load_preset_async(self, preset_id: int) -> None:
        def _call():
            preset_res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL, {"id": int(preset_id)}, timeout=1.0)
            preset = preset_res[0] if preset_res and preset_res[0] else None

            state_res = self.event_bus.emit_and_wait(Events.ApiPresets.LOAD_PRESET_STATE, {"id": int(preset_id)}, timeout=1.0)
            state = state_res[0] if state_res and state_res[0] else {}

            return preset, state

        def _apply(payload):
            preset, state = payload
            if not preset:
                return

            v = self.view
            self._is_loading_ui = True

            self.current_preset_id = int(preset_id)
            self.current_preset_data = dict(preset)

            model = str(state.get("model") or preset.get("default_model") or "")
            key = str(state.get("key") or preset.get("key") or "")
            reserve_keys = state.get("reserve_keys", preset.get("reserve_keys", []))
            if not isinstance(reserve_keys, list):
                reserve_keys = []

            base = self._parse_base(preset.get("base", None))
            self._set_protocol_config_visible(base is None)

            v.template_combo.blockSignals(True)
            if base is None:
                v.template_combo.setCurrentIndex(0)
            else:
                for i in range(v.template_combo.count()):
                    if v.template_combo.itemData(i) == base:
                        v.template_combo.setCurrentIndex(i)
                        break
            v.template_combo.blockSignals(False)

            eff_pid = str(preset.get("protocol_id") or "").strip() or self._protocol_default_id
            if base is None:
                eff_pid = str(state.get("protocol_id") or eff_pid).strip() or self._protocol_default_id

            v.protocol_row.set_current_by_data(eff_pid)
            v.protocol_row.set_enabled(base is None)
            self._apply_protocol_details(eff_pid)

            url_tpl = str(preset.get("url_tpl") or "")
            if base is not None and url_tpl:
                try:
                    url = url_tpl.format(model=model) if "{model}" in url_tpl else url_tpl
                except Exception:
                    url = url_tpl
            elif base is not None:
                url = str(preset.get("url") or "")
            else:
                url = str(state.get("url") or preset.get("url") or "")

            v.api_url_row.set_text(url)
            v.api_model_row.set_text(model)
            v.api_key_row.set_text(key)
            v.reserve_keys_row.set_text("\n".join([str(k).strip() for k in reserve_keys if str(k).strip()]))

            gen_overrides = preset.get("generation_overrides") or {}
            if isinstance(gen_overrides, dict):
                self._write_generation_overrides(gen_overrides)

            v.api_url_row.set_enabled(base is None)

            self._apply_help_links(preset)

            known_models = preset.get("known_models", []) or []
            if isinstance(known_models, list) and known_models:
                v.api_model_list_model.setStringList([str(x) for x in known_models if str(x).strip()])

            v.provider_label.setText(f"{_('Пресет', 'Preset')}: {preset.get('name', '')}")
            v.api_settings_container.setVisible(True)

            self.event_bus.emit(Events.Settings.SAVE_SETTING, {"key": "LAST_API_PRESET_ID", "value": int(preset_id)})

            self._snapshot = self._get_snapshot()
            self._set_dirty(False)

            v.save_preset_button.setVisible(True)
            v.save_preset_button.setEnabled(False)
            v.cancel_button.setVisible(False)

            self._is_loading_ui = False

            if self._pending_select_id and self._pending_select_id != preset_id:
                pid = int(self._pending_select_id)
                self._pending_select_id = None
                self._select_custom_preset(pid)

        self._bus_call_async(_call, _apply, name="load_preset")