from __future__ import annotations

from typing import Optional, Any

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QInputDialog

from ui.settings.api_settings.widgets import CustomPresetListItem
import qtawesome as qta

from utils import _
from core.events import Events
from main_logger import logger
from .state import PresetSnapshot


class EditorMixin:
    def _parse_base(self, value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _get_snapshot(self) -> PresetSnapshot:
        v = self.view
        base = self._parse_base(v.template_combo.currentData())
        return PresetSnapshot(
            url=str(v.api_url_row.text() or ""),
            model=str(v.api_model_row.text() or ""),
            key=str(v.api_key_row.text() or ""),
            base=base,
            reserve_keys_text=str(v.reserve_keys_row.text() or "").strip(),
            protocol_id=self._current_protocol_id_ui(),
        )

    def _set_dirty(self, dirty: bool) -> None:
        v = self.view

        if self.current_preset_id is None or self.current_preset_id not in self.custom_presets_list_items:
            v.save_preset_button.setVisible(False)
            v.cancel_button.setVisible(False)
            return

        dirty = bool(dirty)

        if self._snapshot:
            cur = self._get_snapshot()
            v.api_url_row.set_dirty(cur.url != self._snapshot.url)
            v.api_model_row.set_dirty(cur.model != self._snapshot.model)
            v.api_key_row.set_dirty(cur.key != self._snapshot.key)
            v.reserve_keys_row.set_dirty(cur.reserve_keys_text != self._snapshot.reserve_keys_text)

            if cur.base is None:
                v.protocol_row.set_dirty(cur.protocol_id != self._snapshot.protocol_id)
            else:
                v.protocol_row.set_dirty(False)

        item = self.custom_presets_list_items.get(self.current_preset_id)
        if item:
            item.update_changes_indicator(dirty)

        v.save_preset_button.setVisible(True)
        v.save_preset_button.setEnabled(dirty)
        v.cancel_button.setVisible(dirty)

        if dirty:
            v.save_preset_button.setStyleSheet("""
                QPushButton { background-color: #27ae60; color: white; font-weight: bold; border: none; padding: 8px; border-radius: 4px; }
                QPushButton:hover { background-color: #229954; }
                QPushButton:pressed { background-color: #1e8449; }
            """)
        else:
            v.save_preset_button.setStyleSheet("""
                QPushButton { background-color: #95a5a6; color: #ecf0f1; font-weight: normal; border: none; padding: 8px; border-radius: 4px; }
                QPushButton:disabled { background-color: #7f8c8d; color: #bdc3c7; }
            """)

    def _on_field_changed(self, *_args) -> None:
        if self._is_loading_ui:
            return

        v = self.view

        # NEW: if template is selected and it has url_tpl with {model}, update API URL display
        try:
            base = self._parse_base(v.template_combo.currentData())
        except Exception:
            base = None

        if base is not None:
            url_tpl = ""
            # prefer last loaded template snapshot if present
            tpl = getattr(self, "_active_template", None)
            if isinstance(tpl, dict):
                url_tpl = str(tpl.get("url_tpl") or "")
                if not url_tpl:
                    url_tpl = str(tpl.get("url") or "")
            else:
                # fallback: effective preset dict may include url_tpl
                url_tpl = str((self.current_preset_data or {}).get("url_tpl") or "")

            if url_tpl:
                model = str(v.api_model_row.text() or "")
                try:
                    new_url = url_tpl.format(model=model) if "{model}" in url_tpl else url_tpl
                except Exception:
                    new_url = url_tpl

                # avoid recursion storms
                if v.api_url_row.text() != new_url:
                    self._is_loading_ui = True
                    v.api_url_row.set_text(new_url)
                    self._is_loading_ui = False

        # normal dirty + debounce state
        self._set_dirty(self._snapshot is not None and (self._get_snapshot() != self._snapshot))
        self._state_save_timer.start(350)


    def _on_template_changed_async(self, *_args) -> None:
        if self._is_loading_ui or not self.current_preset_id:
            return

        v = self.view
        template_id = self._parse_base(v.template_combo.currentData())

        if template_id is None:
            v.api_url_row.set_enabled(True)
            v.protocol_row.set_enabled(True)
            self._set_protocol_config_visible(True)

            self._active_template = None

            pid = self._current_protocol_id_ui() or self._protocol_default_id
            v.protocol_row.set_current_by_data(pid)
            self._apply_protocol_details(pid)

            self._on_field_changed()
            return

        self._set_protocol_config_visible(False)

        def _call():
            res = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL,
                {"id": int(template_id)},
                timeout=1.0
            )
            return res[0] if res and res[0] else None

        def _apply(tpl: dict | None):
            if not tpl:
                return

            self._is_loading_ui = True

            self._active_template = dict(tpl)

            pid = str(tpl.get("protocol_id") or "").strip() or self._protocol_default_id
            v.protocol_row.set_current_by_data(pid)
            v.protocol_row.set_enabled(False)
            self._apply_protocol_details(pid)

            default_model = str(tpl.get("default_model") or "").strip()

            saved_model = str((self.current_preset_data or {}).get("default_model") or "").strip()
            if not saved_model and default_model:
                v.api_model_row.set_text(default_model)

            url_tpl = str(tpl.get("url_tpl") or "")
            if url_tpl:
                try:
                    url = url_tpl.format(model=v.api_model_row.text().strip() or default_model) if "{model}" in url_tpl else url_tpl
                except Exception:
                    url = url_tpl
            else:
                url = str(tpl.get("url") or "")

            v.api_url_row.set_text(url)
            v.api_url_row.set_enabled(False)

            known_models = tpl.get("known_models", []) or []
            if isinstance(known_models, list) and known_models:
                v.api_model_list_model.setStringList([str(x) for x in known_models if str(x).strip()])

            self._apply_help_links(tpl)

            self._is_loading_ui = False
            self._on_field_changed()

        self._bus_call_async(_call, _apply, name="load_template")

    def _emit_save_state(self) -> None:
        if self._is_loading_ui:
            return
        if not self.current_preset_id:
            return

        v = self.view
        state = {
            "url": v.api_url_row.text(),
            "model": v.api_model_row.text(),
            "key": v.api_key_row.text(),
            "reserve_keys": [k.strip() for k in v.reserve_keys_row.text().splitlines() if k.strip()],
        }

        base = self._parse_base(v.template_combo.currentData())
        if base is None:
            pid = self._current_protocol_id_ui() or self._protocol_default_id
            state["protocol_id"] = pid

        self.event_bus.emit(Events.ApiPresets.SAVE_PRESET_STATE, {"id": int(self.current_preset_id), "state": state})

    def _toggle_key_visibility(self) -> None:
        v = self.view
        if v.api_key_row.edit.echoMode() == v.api_key_row.edit.EchoMode.Password:
            v.api_key_row.edit.setEchoMode(v.api_key_row.edit.EchoMode.Normal)
            v.key_visibility_button.setIcon(qta.icon('fa5s.eye-slash'))
        else:
            v.api_key_row.edit.setEchoMode(v.api_key_row.edit.EchoMode.Password)
            v.key_visibility_button.setIcon(qta.icon('fa5s.eye'))

    def _apply_help_links(self, preset: dict) -> None:
        v = self.view
        doc_url = str(preset.get("documentation_url") or "")
        models_url = str(preset.get("models_url") or "")
        key_url = str(preset.get("key_url") or "")

        v.url_help_label.setVisible(bool(doc_url))
        v.url_help_label.setText(f'<a href="{doc_url}" style="color: #ab5df5; text-decoration: underline;">{_("Документация", "Documentation")}</a>' if doc_url else "")

        v.model_help_label.setVisible(bool(models_url))
        v.model_help_label.setText(f'<a href="{models_url}" style="color: #ab5df5; text-decoration: underline;">{_("Список моделей", "Models list")}</a>' if models_url else "")

        v.key_help_label.setVisible(bool(key_url))
        v.key_help_label.setText(f'<a href="{key_url}" style="color: #ab5df5; text-decoration: underline;">{_("Получить ключ", "Get API key")}</a>' if key_url else "")

    def _set_protocol_config_visible(self, visible: bool) -> None:
        v = self.view
        sec = getattr(v, "protocol_section", None)
        if sec is not None:
            sec.setVisible(bool(visible))


    def _cancel_changes(self) -> None:
        if not self._snapshot:
            return
        self._is_loading_ui = True
        v = self.view

        v.api_url_row.set_text(self._snapshot.url)
        v.api_model_row.set_text(self._snapshot.model)
        v.api_key_row.set_text(self._snapshot.key)
        v.reserve_keys_row.set_text(self._snapshot.reserve_keys_text)

        v.template_combo.blockSignals(True)
        if self._snapshot.base is None:
            v.template_combo.setCurrentIndex(0)
        else:
            for i in range(v.template_combo.count()):
                if v.template_combo.itemData(i) == self._snapshot.base:
                    v.template_combo.setCurrentIndex(i)
                    break
        v.template_combo.blockSignals(False)

        v.protocol_row.set_current_by_data(self._snapshot.protocol_id or self._protocol_default_id)
        self._apply_protocol_details(self._current_protocol_id_ui())

        self._is_loading_ui = False
        self._set_dirty(False)

    def _save_preset_async(self) -> None:
        if not self.current_preset_id or self.current_preset_id not in self.custom_presets_list_items:
            return

        v = self.view
        pid = int(self.current_preset_id)

        data = dict(self.current_preset_data or {})
        data["id"] = pid
        data["url"] = v.api_url_row.text()
        data["default_model"] = v.api_model_row.text()
        data["key"] = v.api_key_row.text()
        data["reserve_keys"] = [k.strip() for k in v.reserve_keys_row.text().splitlines() if k.strip()]

        base = self._parse_base(v.template_combo.currentData())
        data["base"] = base

        if base is None:
            data["protocol_id"] = self._current_protocol_id_ui() or self._protocol_default_id
            data["protocol_overrides"] = dict(self._protocol_overrides or {})
        else:
            if "protocol_id" in data:
                del data["protocol_id"]
            if "protocol_overrides" in data:
                del data["protocol_overrides"]
            data["url"] = ""

        def _call():
            res = self.event_bus.emit_and_wait(Events.ApiPresets.SAVE_CUSTOM_PRESET, {"data": data}, timeout=2.0)
            return res[0] if res else None

        def _apply(new_id):
            if not isinstance(new_id, int):
                return
            self._snapshot = self._get_snapshot()
            self._set_dirty(False)

            if self._pending_select_id and self._pending_select_id != pid:
                nxt = int(self._pending_select_id)
                self._pending_select_id = None
                QTimer.singleShot(0, lambda: self._select_custom_preset(nxt))

        self._bus_call_async(_call, _apply, name="save_preset")

    def _add_custom_preset_async(self) -> None:
        logger.info("[API UI] add preset clicked")
        v = self.view
        name, ok = QInputDialog.getText(v, _("Новый пресет", "New preset"), _("Название пресета:", "Preset name:"))
        if not ok or not str(name or "").strip():
            logger.info("[API UI] add preset cancelled/empty")
            return

        payload = {
            "name": str(name).strip(),
            "id": None,
            "pricing": "mixed",
            "base": None,
            "url": "",
            "default_model": "",
            "key": "",
            "reserve_keys": [],
            "protocol_id": getattr(self, "_protocol_default_id", "") or "",
        }

        logger.info(f"[API UI] Creating preset name='{payload['name']}'")

        def _call():
            logger.info("[API UI] calling SAVE_CUSTOM_PRESET via emit_and_wait...")
            res = self.event_bus.emit_and_wait(Events.ApiPresets.SAVE_CUSTOM_PRESET, {"data": payload}, timeout=2.0)
            logger.info(f"[API UI] SAVE_CUSTOM_PRESET result={res}")
            return res[0] if res else None

        def _apply(new_id):
            logger.info(f"[API UI] Created preset new_id={new_id} type={type(new_id)}")
            if not isinstance(new_id, int):
                QMessageBox.warning(
                    v,
                    _("Ошибка", "Error"),
                    _("Не удалось создать пресет. Проверь логи (SAVE_CUSTOM_PRESET).",
                    "Failed to create preset. Check logs (SAVE_CUSTOM_PRESET).")
                )
                return
            self.reload_presets_async()
            QTimer.singleShot(200, lambda: self._select_custom_preset(int(new_id)))

        self._bus_call_async(_call, _apply, name="add_preset")

    def _remove_custom_preset_async(self) -> None:
        v = self.view
        cur_item = v.custom_presets_list.currentItem()
        if not isinstance(cur_item, CustomPresetListItem):
            return

        if cur_item.has_changes:
            reply = QMessageBox.question(
                v, _("Несохраненные изменения", "Unsaved changes"),
                _("Есть несохраненные изменения. Удалить пресет?", "There are unsaved changes. Delete preset?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        reply = QMessageBox.question(
            v, _("Удалить пресет", "Delete preset"),
            _("Удалить выбранный пресет?", "Delete selected preset?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        pid = int(cur_item.preset_id)
        self.event_bus.emit(Events.ApiPresets.DELETE_CUSTOM_PRESET, {"id": pid})
        self.current_preset_id = None
        v.api_settings_container.setVisible(False)
        self.reload_presets_async()

    def _move_preset_up(self) -> None:
        v = self.view
        row = v.custom_presets_list.currentRow()
        if row <= 0:
            return
        item = v.custom_presets_list.takeItem(row)
        v.custom_presets_list.insertItem(row - 1, item)
        v.custom_presets_list.setCurrentItem(item)
        self._save_presets_order()

    def _move_preset_down(self) -> None:
        v = self.view
        row = v.custom_presets_list.currentRow()
        if row < 0 or row >= v.custom_presets_list.count() - 1:
            return
        item = v.custom_presets_list.takeItem(row)
        v.custom_presets_list.insertItem(row + 1, item)
        v.custom_presets_list.setCurrentItem(item)
        self._save_presets_order()

    def _save_presets_order(self) -> None:
        v = self.view
        order: list[int] = []
        for i in range(v.custom_presets_list.count()):
            it = v.custom_presets_list.item(i)
            if isinstance(it, CustomPresetListItem):
                order.append(int(it.preset_id))
        self.event_bus.emit(Events.ApiPresets.SAVE_PRESETS_ORDER, {"order": order})