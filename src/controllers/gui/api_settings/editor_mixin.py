from __future__ import annotations

import json
from typing import Optional, Any

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QInputDialog

from ui.settings.api_settings.widgets import CustomPresetListItem
import qtawesome as qta

from utils import _
from styles.theme import THEME
from core.events import Events
from core.services import use
from services.contracts import ApiPresetService
from main_logger import logger
from .state import PresetSnapshot


class EditorMixin:
    def _parse_base(self, value: Any) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _refresh_model_settings_dialect(self) -> None:
        protocol = self._protocols.get(self._current_protocol_id_ui()) or {}
        dialect = str(protocol.get("dialect") or "openai_chat_completions")
        self.model_settings_controller.set_dialect(dialect)

    def _read_openrouter_routing(self) -> dict:
        v = self.view
        return {
            "enabled": bool(getattr(v, "or_enable_cb", None).isChecked()) if getattr(v, "or_enable_cb", None) is not None else False,
            "tail_system_to_user": bool(getattr(v, "or_tail_system_to_user_cb", None).isChecked()) if getattr(v, "or_tail_system_to_user_cb", None) is not None else True,
            "order": str(getattr(v, "or_order_row", None).text() or "") if getattr(v, "or_order_row", None) is not None else "",
            "only": str(getattr(v, "or_only_row", None).text() or "") if getattr(v, "or_only_row", None) is not None else "",
            "ignore": str(getattr(v, "or_ignore_row", None).text() or "") if getattr(v, "or_ignore_row", None) is not None else "",
            "quantizations": str(getattr(v, "or_quantizations_row", None).text() or "") if getattr(v, "or_quantizations_row", None) is not None else "",
            "sort": str(getattr(v, "or_sort_row", None).current_data() or "") if getattr(v, "or_sort_row", None) is not None else "",
            "data_collection": str(getattr(v, "or_data_collection_row", None).current_data() or "") if getattr(v, "or_data_collection_row", None) is not None else "",
            "allow_fallbacks": bool(getattr(v, "or_allow_fallbacks_cb", None).isChecked()) if getattr(v, "or_allow_fallbacks_cb", None) is not None else False,
            "require_parameters": bool(getattr(v, "or_require_parameters_cb", None).isChecked()) if getattr(v, "or_require_parameters_cb", None) is not None else False,
            "zdr": bool(getattr(v, "or_zdr_cb", None).isChecked()) if getattr(v, "or_zdr_cb", None) is not None else False,
            "max_price": {
                "prompt": str(getattr(v, "or_max_price_prompt", None).text() or "") if getattr(v, "or_max_price_prompt", None) is not None else "",
                "completion": str(getattr(v, "or_max_price_completion", None).text() or "") if getattr(v, "or_max_price_completion", None) is not None else "",
                "request": str(getattr(v, "or_max_price_request", None).text() or "") if getattr(v, "or_max_price_request", None) is not None else "",
                "image": str(getattr(v, "or_max_price_image", None).text() or "") if getattr(v, "or_max_price_image", None) is not None else "",
            },
        }

    def _write_openrouter_routing(self, routing: dict) -> None:
        v = self.view
        routing = routing or {}
        max_price = routing.get("max_price") if isinstance(routing.get("max_price"), dict) else {}

        if getattr(v, "or_enable_cb", None) is not None:
            v.or_enable_cb.setChecked(bool(routing.get("enabled", False)))
        if getattr(v, "or_tail_system_to_user_cb", None) is not None:
            v.or_tail_system_to_user_cb.setChecked(bool(routing.get("tail_system_to_user", True)))
        if getattr(v, "or_order_row", None) is not None:
            v.or_order_row.set_text(", ".join(routing.get("order", [])) if isinstance(routing.get("order"), list) else str(routing.get("order") or ""))
        if getattr(v, "or_only_row", None) is not None:
            v.or_only_row.set_text(", ".join(routing.get("only", [])) if isinstance(routing.get("only"), list) else str(routing.get("only") or ""))
        if getattr(v, "or_ignore_row", None) is not None:
            v.or_ignore_row.set_text(", ".join(routing.get("ignore", [])) if isinstance(routing.get("ignore"), list) else str(routing.get("ignore") or ""))
        if getattr(v, "or_quantizations_row", None) is not None:
            v.or_quantizations_row.set_text(", ".join(routing.get("quantizations", [])) if isinstance(routing.get("quantizations"), list) else str(routing.get("quantizations") or ""))
        if getattr(v, "or_sort_row", None) is not None:
            v.or_sort_row.set_current_by_data(str(routing.get("sort") or ""))
        if getattr(v, "or_data_collection_row", None) is not None:
            v.or_data_collection_row.set_current_by_data(str(routing.get("data_collection") or ""))
        if getattr(v, "or_allow_fallbacks_cb", None) is not None:
            v.or_allow_fallbacks_cb.setChecked(bool(routing.get("allow_fallbacks", False)))
        if getattr(v, "or_require_parameters_cb", None) is not None:
            v.or_require_parameters_cb.setChecked(bool(routing.get("require_parameters", False)))
        if getattr(v, "or_zdr_cb", None) is not None:
            v.or_zdr_cb.setChecked(bool(routing.get("zdr", False)))
        if getattr(v, "or_max_price_prompt", None) is not None:
            v.or_max_price_prompt.setText(str(max_price.get("prompt") or ""))
        if getattr(v, "or_max_price_completion", None) is not None:
            v.or_max_price_completion.setText(str(max_price.get("completion") or ""))
        if getattr(v, "or_max_price_request", None) is not None:
            v.or_max_price_request.setText(str(max_price.get("request") or ""))
        if getattr(v, "or_max_price_image", None) is not None:
            v.or_max_price_image.setText(str(max_price.get("image") or ""))

    def _get_snapshot(self) -> PresetSnapshot:
        v = self.view
        base = self._parse_base(v.template_combo.currentData())
        fb_tuple = tuple(
            (int(fb.get("preset_id") or 0), str(fb.get("model") or ""))
            for fb in (getattr(v, "fallback_editor", None).get_value() if getattr(v, "fallback_editor", None) else [])
        )
        return PresetSnapshot(
            name=v.preset_name_row.text(),
            url=str(v.api_url_row.text() or ""),
            model=str(v.api_model_row.text() or ""),
            key=str(v.api_key_row.text() or ""),
            base=base,
            reserve_keys_text=str(v.reserve_keys_row.text() or "").strip(),
            reserve_keys_distribute=bool(v.reserve_keys_row.is_distribute()),
            protocol_id=self._current_protocol_id_ui(),
            model_settings=v.model_settings_form.document() or {},
            openrouter_routing=self._read_openrouter_routing(),
            fallbacks=fb_tuple,
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
            v.preset_name_row.set_dirty(cur.name != self._snapshot.name)
            v.api_url_row.set_dirty(cur.url != self._snapshot.url)
            v.api_model_row.set_dirty(cur.model != self._snapshot.model)
            v.api_key_row.set_dirty(cur.key != self._snapshot.key)
            v.reserve_keys_row.set_dirty(
                cur.reserve_keys_text != self._snapshot.reserve_keys_text
                or cur.reserve_keys_distribute != self._snapshot.reserve_keys_distribute)

            if cur.base is None:
                v.protocol_row.set_dirty(cur.protocol_id != self._snapshot.protocol_id)
            else:
                v.protocol_row.set_dirty(False)

        item = self.custom_presets_list_items.get(self.current_preset_id)
        if item:
            item.update_changes_indicator(dirty)

        v.save_preset_button.setVisible(True)
        v.save_preset_button.setEnabled(dirty and v.model_settings_form.validate())
        v.cancel_button.setVisible(dirty)

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

        self._refresh_model_settings_dialect()

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
            self._apply_help_links({})

            self._on_field_changed()
            return

        self._set_protocol_config_visible(False)

        def _call():
            return use(ApiPresetService).get_full(int(template_id))

        def _apply(tpl: dict | None):
            if not tpl:
                return

            self._is_loading_ui = True

            self._active_template = dict(tpl)
            dialect = str((self._protocols.get(str(tpl.get("protocol_id") or "")) or {}).get("dialect") or "openai_chat_completions")
            self.model_settings_controller.set_dialect(dialect, str(tpl.get("settings_schema_id") or ""))

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
            self._refresh_model_settings_dialect()

            self._is_loading_ui = False
            self._on_field_changed()

        self._bus_call_async(_call, _apply, name="load_template")

    def _emit_save_state(self) -> None:
        if not self.view.model_settings_form.validate():
            return
        if self._is_loading_ui:
            return
        if not self.current_preset_id:
            return

        state = self._build_preset_state()

        self.event_bus.emit(Events.ApiPresets.SAVE_PRESET_STATE, {"id": int(self.current_preset_id), "state": state})

    def _build_preset_state(self) -> dict:
        v = self.view
        state = {
            "url": v.api_url_row.text(),
            "model": v.api_model_row.text(),
            "key": v.api_key_row.text(),
            "reserve_keys": [k.strip() for k in v.reserve_keys_row.text().splitlines() if k.strip()],
            "reserve_keys_distribute": bool(v.reserve_keys_row.is_distribute()),
            "fallbacks": v.fallback_editor.get_value() if hasattr(v, "fallback_editor") else [],
        }

        base = self._parse_base(v.template_combo.currentData())
        if base is None:
            state["protocol_id"] = self._current_protocol_id_ui() or self._protocol_default_id

        return state

    def _build_current_preset_payload(self, *, preset_id: int | None, name: str | None = None) -> dict:
        v = self.view
        data = dict(self.current_preset_data or {})
        data["id"] = preset_id
        data["name"] = str(name if name is not None else v.preset_name_row.text()).strip()
        if not data["name"]:
            raise ValueError(str(_("Укажите название пресета", "Enter a preset name")))
        data["url"] = v.api_url_row.text()
        data["default_model"] = v.api_model_row.text()
        data["key"] = v.api_key_row.text()
        data["reserve_keys"] = [k.strip() for k in v.reserve_keys_row.text().splitlines() if k.strip()]
        data["reserve_keys_distribute"] = bool(v.reserve_keys_row.is_distribute())

        base = self._parse_base(v.template_combo.currentData())
        data["base"] = base

        if base is None:
            data["protocol_id"] = self._current_protocol_id_ui() or self._protocol_default_id
            data["protocol_overrides"] = dict(self._protocol_overrides or {})
        else:
            data.pop("protocol_id", None)
            data.pop("protocol_overrides", None)
            data["url"] = ""

        data["generation_overrides"] = {}
        data["model_settings"] = v.model_settings_form.document()
        data.pop("model_profile_overrides", None)
        data["openrouter_routing"] = self._read_openrouter_routing()
        data["fallbacks"] = v.fallback_editor.get_value() if hasattr(v, "fallback_editor") else []
        return data

    def _toggle_key_visibility(self) -> None:
        v = self.view
        if v.api_key_row.edit.echoMode() == v.api_key_row.edit.EchoMode.Password:
            v.api_key_row.edit.setEchoMode(v.api_key_row.edit.EchoMode.Normal)
            v.key_visibility_button.setIcon(qta.icon('fa5s.eye-slash', color='#b6bbce'))
        else:
            v.api_key_row.edit.setEchoMode(v.api_key_row.edit.EchoMode.Password)
            v.key_visibility_button.setIcon(qta.icon('fa5s.eye', color='#b6bbce'))

    def _apply_help_links(self, preset: dict) -> None:
        # Запоминаем последний пресет и подписываемся (один раз) на смену языка:
        # ссылки-подписи ставятся через setText и не в реестре tr_set, поэтому при
        # живой смене языка их надо переустановить вручную.
        self._last_help_preset = preset
        if not getattr(self, "_help_links_lang_hook_bound", False):
            self._help_links_lang_hook_bound = True
            try:
                from localization.live import language_changed_signal
                language_changed_signal().connect(
                    lambda *_a: self._apply_help_links(getattr(self, "_last_help_preset", {}) or {})
                )
            except Exception:
                pass

        v = self.view
        doc_url = str(preset.get("documentation_url") or "")
        models_url = str(preset.get("models_url") or "")
        key_url = str(preset.get("key_url") or "")
        test_url = str(preset.get("test_url") or "").strip()

        v.test_button.setVisible(bool(test_url))

        v.url_help_label.setVisible(bool(doc_url))
        v.url_help_label.setText(f'<a href="{doc_url}" style="color: {THEME["link"]}; text-decoration: underline;">{_("Документация", "Documentation")}</a>' if doc_url else "")

        v.model_help_label.setVisible(bool(models_url))
        v.model_help_label.setText(f'<a href="{models_url}" style="color: {THEME["link"]}; text-decoration: underline;">{_("Список моделей", "Models list")}</a>' if models_url else "")

        v.key_help_label.setVisible(bool(key_url))
        v.key_help_label.setText(f'<a href="{key_url}" style="color: {THEME["link"]}; text-decoration: underline;">{_("Получить ключ", "Get API key")}</a>' if key_url else "")

    def _set_protocol_config_visible(self, visible: bool) -> None:
        v = self.view
        v.protocol_row.set_enabled(visible)
        sec = getattr(v, "protocol_section", None)
        if sec is not None:
            sec.setVisible(bool(visible))


    def _cancel_changes(self) -> None:
        if not self._snapshot:
            return
        self._is_loading_ui = True
        v = self.view

        v.preset_name_row.set_text(self._snapshot.name)
        v.api_url_row.set_text(self._snapshot.url)
        v.api_model_row.set_text(self._snapshot.model)
        v.api_key_row.set_text(self._snapshot.key)
        v.reserve_keys_row.set_text(self._snapshot.reserve_keys_text)
        v.reserve_keys_row.set_distribute(self._snapshot.reserve_keys_distribute)

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

        dialect = str((self._protocols.get(self._snapshot.protocol_id) or {}).get("dialect") or "openai_chat_completions")
        self.model_settings_controller.restore(self._snapshot.model_settings, dialect)
        self._active_template = dict(self.current_preset_data) if self._snapshot.base is not None else None
        self._set_protocol_config_visible(self._snapshot.base is None)
        self._apply_help_links(self.current_preset_data)
        self._write_openrouter_routing(self._snapshot.openrouter_routing)
        self._refresh_model_settings_dialect()

        if hasattr(v, "fallback_editor"):
            v.fallback_editor.blockSignals(True)
            v.fallback_editor.set_value([
                {"preset_id": pid, "model": m} for pid, m in (self._snapshot.fallbacks or ())
            ])
            v.fallback_editor.blockSignals(False)

        self._is_loading_ui = False
        self._set_dirty(False)

    def _save_preset_async(self) -> None:
        if not self.view.model_settings_form.validate():
            return
        if not self.current_preset_id or self.current_preset_id not in self.custom_presets_list_items:
            return

        pid = int(self.current_preset_id)
        try:
            data = self._build_current_preset_payload(preset_id=pid)
        except ValueError as exc:
            QMessageBox.warning(
                self.view,
                _("Ошибка профиля модели", "Model profile error"),
                str(exc),
            )
            return

        def _call():
            return use(ApiPresetService).save_custom(data)

        def _apply(new_id):
            if not isinstance(new_id, int):
                return
            self.current_preset_data = dict(data)
            item = self.custom_presets_list_items.get(pid)
            if item is not None:
                item.base_name = data["name"]
                item.model = data["default_model"]
                item.update_display()
            self._snapshot = self._get_snapshot()
            self._set_dirty(False)

            if self._pending_select_id and self._pending_select_id != pid:
                nxt = int(self._pending_select_id)
                self._pending_select_id = None
                QTimer.singleShot(0, lambda: self._select_custom_preset(nxt))

        self._bus_call_async(_call, _apply, name="save_preset")

    def _copy_custom_preset_async(self) -> None:
        v = self.view
        cur_item = v.custom_presets_list.currentItem()
        if not isinstance(cur_item, CustomPresetListItem):
            return

        old_name = str(cur_item.base_name or "").strip()
        suggested_name = f"{old_name} Copy" if old_name else "Preset Copy"
        new_name, ok = QInputDialog.getText(
            v,
            _("Скопировать пресет", "Copy preset"),
            _("Название копии:", "Copy name:"),
            text=suggested_name,
        )
        if not ok or not str(new_name or "").strip():
            return

        try:
            payload = self._build_current_preset_payload(
                preset_id=None,
                name=str(new_name).strip(),
            )
        except ValueError as exc:
            QMessageBox.warning(
                v,
                _("Ошибка профиля модели", "Model profile error"),
                str(exc),
            )
            return
        state = self._build_preset_state()

        def _call():
            service = use(ApiPresetService)
            new_id = service.save_custom(payload)
            if isinstance(new_id, int):
                service.save_state(int(new_id), state)
            return new_id

        def _apply(new_id):
            if not isinstance(new_id, int):
                QMessageBox.warning(
                    v,
                    _("Ошибка", "Error"),
                    _("Не удалось скопировать пресет.", "Failed to copy preset."),
                )
                return
            self._pending_select_id = int(new_id)
            self._selection_retry_count = 0
            self.reload_presets_async()

        self._bus_call_async(_call, _apply, name="copy_preset")

    def _add_custom_preset_async(self) -> None:
        logger.info("[API UI] add preset clicked")
        v = self.view
        existing = {item.base_name for item in self.custom_presets_list_items.values()}
        number = 1
        while str(_("Пустой пресет", "Empty preset")) + f" {number}" in existing:
            number += 1
        name = str(_("Пустой пресет", "Empty preset")) + f" {number}"
        selected_base = None

        payload = {
            "name": str(name).strip(),
            "id": None,
            "pricing": "mixed",
            "base": selected_base,
            "url": "",
            "default_model": "",
            "key": "",
            "reserve_keys": [],
            "protocol_id": "" if selected_base is not None else (getattr(self, "_protocol_default_id", "") or ""),
        }

        logger.info(f"[API UI] Creating preset name='{payload['name']}', base={payload['base']}")

        def _call():
            logger.info("[API UI] saving custom preset through ApiPresetService...")
            result = use(ApiPresetService).save_custom(payload)
            logger.info(f"[API UI] save_custom result={result}")
            return result

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
            self._pending_select_id = int(new_id)
            self._selection_retry_count = 0
            self.reload_presets_async()

        self._bus_call_async(_call, _apply, name="add_preset")

    def _on_preset_action(self, action: str, preset_id: int) -> None:
        if action == "default":
            self.event_bus.emit(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": preset_id})
            for pid, item in self.custom_presets_list_items.items():
                item.is_default = pid == preset_id
            self.view.custom_presets_list.viewport().update()
            self.view.preset_active_tag.setVisible(preset_id == self.current_preset_id)
            return
        selected = self.view.custom_presets_list.currentItem()
        if self.current_preset_id != preset_id or getattr(selected, "preset_id", None) != preset_id:
            self._pending_preset_action = (action, preset_id)
            self._select_custom_preset(preset_id)
            return
        callbacks = {
            "rename": self._rename_custom_preset_async,
            "copy": self._copy_custom_preset_async,
            "remove": self._remove_custom_preset_async,
        }
        callback = callbacks.get(action)
        if callback is not None:
            callback()

    def _rename_custom_preset_async(self) -> None:
        v = self.view
        cur_item = v.custom_presets_list.currentItem()
        if not isinstance(cur_item, CustomPresetListItem):
            return

        old_name = cur_item.base_name
        new_name, ok = QInputDialog.getText(
            v,
            _("Переименовать пресет", "Rename preset"),
            _("Новое название:", "New name:"),
            text=old_name,
        )
        if not ok or not str(new_name or "").strip():
            return

        new_name = str(new_name).strip()
        if new_name == old_name:
            return

        pid = int(cur_item.preset_id)
        data = dict(self.current_preset_data or {})
        data["id"] = pid
        data["name"] = new_name

        def _call():
            return use(ApiPresetService).save_custom(data)

        def _apply(saved_id):
            if not isinstance(saved_id, int):
                return
            cur_item.base_name = new_name
            cur_item.update_display()
            if self.current_preset_data is not None:
                self.current_preset_data["name"] = new_name
            v.provider_label.setText(new_name)
            v.preset_name_row.set_text(new_name)
            if self._snapshot is not None:
                self._snapshot.name = new_name

        self._bus_call_async(_call, _apply, name="rename_preset")

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
