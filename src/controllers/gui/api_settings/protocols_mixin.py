from __future__ import annotations

from typing import Any
from utils import _
from PyQt6.QtCore import Qt
from localization.live import register


def _render_capabilities(label):
    pairs = label.property("capabilityLabels") or []
    label.setText(" · ".join(str(_(ru, en)) for ru, en in pairs))


def _render_processing_summary(label):
    count = int(label.property("transformCount") or 0)
    text = _("Стандартная обработка сообщений", "Standard message processing")
    if count:
        text = _(
            "Шагов обработки сообщений: {count}", "Message processing steps: {count}"
        ).format(count=count)
    label.setText(str(text))


class ProtocolsMixin:
    def _load_protocol_catalog(self) -> dict[str, dict]:
        try:
            from presets.api_protocols import API_PROTOCOLS_DATA

            out: dict[str, dict] = {}
            for p in API_PROTOCOLS_DATA or []:
                pid = str(p.get("id") or "").strip()
                if not pid:
                    continue
                out[pid] = dict(p)
            return out
        except Exception:
            return {}

    def _pick_default_protocol_id(self) -> str:
        if "openai_compatible_default" in self._protocols:
            return "openai_compatible_default"
        if self._protocols:
            return sorted(self._protocols.keys())[0]
        return ""

    def _current_protocol_id_ui(self) -> str:
        v = self.view
        pid = v.protocol_row.current_data()
        return str(pid or "").strip()

    def _populate_protocol_combo(self) -> None:
        v = self.view
        if not getattr(self, "_protocol_labels_registered", False):
            register(v.protocol_info_label, _render_capabilities)
            register(v.protocol_transforms_view, _render_processing_summary)
            self._protocol_labels_registered = True
        items: list[tuple[str, object]] = []

        def sort_key(pid: str):
            proto = self._protocols.get(pid) or {}
            name = str(proto.get("display_name") or proto.get("name") or pid)
            return (0 if pid == self._protocol_default_id else 1, name.lower())

        for pid in sorted(self._protocols.keys(), key=sort_key):
            proto = self._protocols[pid]
            name = str(proto.get("display_name") or proto.get("name") or pid)
            items.append((name, pid))

        if not items:
            items = [("OpenAI-compatible API", "openai_compatible_default")]

        v.protocol_row.set_items(items)
        for index in range(v.protocol_row.combo.count()):
            pid = str(v.protocol_row.combo.itemData(index) or "")
            proto = self._protocols.get(pid) or {}
            v.protocol_row.combo.setItemData(
                index, str(proto.get("name") or ""), Qt.ItemDataRole.ToolTipRole
            )
        v.protocol_row.set_current_by_data(self._protocol_default_id)
        self._apply_protocol_details(self._current_protocol_id_ui())

    def _apply_protocol_details(self, protocol_id: str) -> None:
        v = self.view
        pid = str(protocol_id or "").strip()
        proto = self._protocols.get(pid) or {}
        from ui.provider_icons import provider_icon, protocol_provider

        icon = (
            v.template_combo.itemIcon(v.template_combo.currentIndex())
            if v.template_combo.currentData() is not None
            else provider_icon(protocol_provider(pid))
        )
        v.preset_provider_icon.setPixmap(icon.pixmap(38, 38))
        v.api_type_label.setText(
            str(proto.get("display_name") or proto.get("name") or "")
        )
        if hasattr(v, "openrouter_routing_section"):
            v.openrouter_routing_section.setVisible(pid == "openrouter_default")
        if hasattr(self, "_apply_provider_ui"):
            self._apply_provider_ui(pid)

        caps = proto.get("capabilities") or {}
        labels = [
            ("streaming", "Потоковые ответы", "Streaming responses"),
            ("tools_native", "Вызов инструментов", "Tool calling"),
            ("structured_output", "Структурированные ответы", "Structured responses"),
        ]
        pairs = [(ru, en) for key, ru, en in labels if caps.get(key)]
        v.protocol_info_label.setProperty("capabilityLabels", pairs)
        _render_capabilities(v.protocol_info_label)
        v.protocol_info_label.setVisible(bool(pairs))
        self._refresh_protocol_transforms()

    def _refresh_protocol_transforms(self) -> None:
        proto = self._protocols.get(self._current_protocol_id_ui()) or {}
        overrides = getattr(self, "_protocol_overrides", {}) or {}
        transforms = overrides.get("transforms", proto.get("transforms")) or []
        self.view.protocol_transforms_view.setProperty(
            "transformCount", len(transforms)
        )
        _render_processing_summary(self.view.protocol_transforms_view)

    def _on_protocol_changed(self, *_: Any) -> None:
        if self._is_loading_ui:
            return
        self._apply_protocol_details(self._current_protocol_id_ui())
        protocol = self._protocols.get(self._current_protocol_id_ui()) or {}
        self.model_settings_controller.set_dialect(
            str(protocol.get("dialect") or "openai_chat_completions"),
            str(protocol.get("settings_schema_id") or ""),
        )
        self._on_field_changed()
