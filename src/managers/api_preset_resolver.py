# src/managers/api_preset_resolver.py
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional
import re

from core.events import Events
from main_logger import logger
from managers.protocol_registry import get_protocol_registry
from presets.api_protocols import Dialects


@dataclass(frozen=True)
class PresetSettings:
    protocol_id: str
    dialect_id: str
    provider_name: str
    headers: Dict[str, str]
    transforms: List[Dict[str, Any]]
    capabilities: Dict[str, Any]

    api_key: str
    api_url: str
    api_model: str

    preset_name: str
    reserve_keys: List[str]

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "preset_name": self.preset_name,
            "protocol_id": self.protocol_id,
            "dialect_id": self.dialect_id,
            "provider_name": self.provider_name,
            "api_url": self.api_url,
            "api_model": self.api_model,
            "reserve_keys_count": len(self.reserve_keys or []),
            "has_api_key": bool(self.api_key),
        }


class ApiPresetResolver:
    def __init__(self, settings: Any, event_bus: Any):
        self.settings = settings
        self.event_bus = event_bus

    def resolve(self, preset_id: Optional[int] = None) -> PresetSettings:
        if preset_id is None:
            preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        preset = self._load_preset_full(preset_id)
        if not preset:
            preset_id = self._pick_fallback_preset_id()
            preset = self._load_preset_full(preset_id)

        registry = get_protocol_registry()
        proto = None
        protocol_id = ""

        if preset:
            protocol_id = str(preset.get("protocol_id", "") or "").strip()
            proto = registry.get(protocol_id) if protocol_id else None

        if not proto:
            proto = registry.pick_default()
            protocol_id = proto.id if proto else ""

        url = ""
        api_model = ""
        api_key = ""
        preset_name = "Fallback"
        reserve_keys: List[str] = []

        if preset:
            preset_name = str(preset.get("name", "Unknown") or "Unknown")
            api_model = str(preset.get("default_model", "") or "")
            api_key = str(preset.get("key", "") or "")

            url = str(preset.get("url", "") or "")
            url_tpl = str(preset.get("url_tpl", "") or "")
            if url_tpl:
                try:
                    url = url_tpl.format(model=api_model) if "{model}" in url_tpl else url_tpl
                except Exception:
                    url = url_tpl

            rk = preset.get("reserve_keys", []) or []
            if isinstance(rk, list):
                reserve_keys = [str(k) for k in rk if str(k).strip()]

        dialect_id = str(getattr(proto, "dialect", "") or "")
        provider_name = str(getattr(proto, "provider", "") or "")

        headers = dict(getattr(proto, "headers", {}) or {})
        transforms = list(getattr(proto, "transforms", []) or [])
        capabilities = dict(getattr(proto, "capabilities", {}) or {})

        # Apply per-preset protocol_overrides ONLY when base is None (custom manual preset)
        base = preset.get("base") if isinstance(preset, dict) else None
        base_is_none = (base is None)

        po = preset.get("protocol_overrides") if isinstance(preset, dict) else None
        if base_is_none and isinstance(po, dict) and po:
            oh = po.get("headers")
            if isinstance(oh, dict) and oh:
                headers.update({str(k): str(v) for k, v in oh.items() if k and v is not None})

            oc = po.get("capabilities")
            if isinstance(oc, dict) and oc:
                for k, v in oc.items():
                    capabilities[str(k)] = v

            ot = po.get("transforms")
            if isinstance(ot, list):
                # replace transforms if provided
                transforms = [t for t in ot if isinstance(t, dict) and t.get("id")]

        if dialect_id == Dialects.GEMINI_GENERATE_CONTENT and url and api_key and "key=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={api_key}"

        return PresetSettings(
            protocol_id=protocol_id,
            dialect_id=dialect_id,
            provider_name=provider_name,
            headers=headers,
            transforms=transforms,
            capabilities=capabilities,
            api_key=api_key,
            api_url=str(url or ""),
            api_model=api_model,
            preset_name=preset_name,
            reserve_keys=reserve_keys,
        )

    def _load_preset_full(self, preset_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if not preset_id:
            return None
        try:
            preset_data = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL,
                {"id": int(preset_id)},
                timeout=1.0,
            )
            if preset_data and preset_data[0]:
                return preset_data[0]
        except Exception as e:
            logger.error(f"[ApiPresetResolver] Failed to load preset via bus: {e}", exc_info=True)
        return None

    def _pick_fallback_preset_id(self) -> Optional[int]:
        try:
            meta_res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = meta_res[0] if meta_res else None
            if not meta:
                return None

            builtin = meta.get("builtin", []) or []
            custom = meta.get("custom", []) or []

            candidates = list(custom) + list(builtin)
            for pm in candidates:
                pid = getattr(pm, "id", None)
                if isinstance(pid, int) and pid > 0:
                    return pid
        except Exception:
            return None
        return None

    def resolve_preset_id_by_name(self, display_name: str) -> Optional[int]:
        if not display_name:
            return None
        try:
            meta_res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = meta_res[0] if meta_res else None
            if not meta:
                return None

            for bucket in ("custom", "builtin"):
                items = meta.get(bucket, []) or []
                for pm in items:
                    if getattr(pm, "name", None) == display_name:
                        pid = getattr(pm, "id", None)
                        return pid if isinstance(pid, int) else None
        except Exception as e:
            logger.error(f"[ApiPresetResolver] Failed to resolve preset id by name '{display_name}': {e}", exc_info=True)
        return None

    def select_key_for_attempt(self, current_key: str, reserve_keys: List[str], attempt_index: int) -> Optional[str]:
        all_keys: List[str] = []
        if current_key:
            all_keys.append(current_key)
        if reserve_keys:
            all_keys.extend([k for k in reserve_keys if k])

        seen = set()
        unique_keys = [x for x in all_keys if not (x in seen or seen.add(x))]

        if not unique_keys:
            logger.error("[ApiPresetResolver] No API keys available")
            return None

        if len(unique_keys) == 1:
            return unique_keys[0]

        key_index = attempt_index % len(unique_keys)
        return unique_keys[key_index]

    def apply_key_rotation(self, preset: PresetSettings, attempt: int) -> PresetSettings:
        if attempt <= 1:
            return preset
        if not preset.reserve_keys:
            return preset

        new_key = self.select_key_for_attempt(
            current_key=preset.api_key,
            reserve_keys=preset.reserve_keys,
            attempt_index=attempt - 1,
        )
        if not new_key or new_key == preset.api_key:
            return preset

        new_url = preset.api_url
        if "key=" in (new_url or ""):
            new_url = re.sub(r"key=[^&]*", f"key={new_key}", new_url)

        return replace(preset, api_key=new_key, api_url=new_url)