from __future__ import annotations

from typing import Any


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
        items: list[tuple[str, object]] = []

        def sort_key(pid: str):
            proto = self._protocols.get(pid) or {}
            name = str(proto.get("name") or pid)
            return (0 if pid == self._protocol_default_id else 1, name.lower())

        for pid in sorted(self._protocols.keys(), key=sort_key):
            proto = self._protocols[pid]
            name = str(proto.get("name") or pid)
            dialect = str(proto.get("dialect") or "")
            provider = str(proto.get("provider") or "")
            label = f"{name}  [{dialect}/{provider}]"
            items.append((label, pid))

        if not items:
            items = [("openai_compatible_default", "openai_compatible_default")]

        v.protocol_row.set_items(items)
        v.protocol_row.set_current_by_data(self._protocol_default_id)
        self._apply_protocol_details(self._current_protocol_id_ui())

    def _apply_protocol_details(self, protocol_id: str) -> None:
        v = self.view
        pid = str(protocol_id or "").strip()
        proto = self._protocols.get(pid) or {}

        dialect = str(proto.get("dialect") or "")
        provider = str(proto.get("provider") or "")
        caps = proto.get("capabilities") or {}
        transforms = proto.get("transforms") or []

        caps_s = ""
        if isinstance(caps, dict) and caps:
            caps_s = ", ".join([f"{k}={v}" for k, v in caps.items()])

        from utils import _
        v.protocol_info_label.setText(
            f"{_('Dialect', 'Dialect')}: {dialect} | "
            f"{_('Provider', 'Provider')}: {provider}"
            + (f" | {_('Caps', 'Caps')}: {caps_s}" if caps_s else "")
        )

        lines: list[str] = []
        if isinstance(transforms, list):
            for t in transforms:
                if isinstance(t, dict):
                    tid = str(t.get("id") or "").strip()
                    params = t.get("params")
                    lines.append(f"- {tid}" + (f"  params={params}" if params else ""))
                else:
                    lines.append(f"- {str(t)}")

        v.protocol_transforms_view.setPlainText(
            "\n".join(lines) if lines else _("(нет transforms)", "(no transforms)")
        )

    def _on_protocol_changed(self, *_: Any) -> None:
        if self._is_loading_ui:
            return
        self._apply_protocol_details(self._current_protocol_id_ui())
        self._on_field_changed()