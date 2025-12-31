# src/managers/api_preset_resolver.py
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional
import re

from core.events import Events
from main_logger import logger


@dataclass(frozen=True)
class PresetSettings:
    api_key: str
    api_url: str
    api_model: str
    make_request: bool
    gemini_case: bool
    is_g4f: bool
    g4f_model: str
    preset_name: str
    reserve_keys: List[str]

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "preset_name": self.preset_name,
            "api_url": self.api_url,
            "api_model": self.api_model,
            "make_request": self.make_request,
            "gemini_case": self.gemini_case,
            "is_g4f": self.is_g4f,
            "g4f_model": self.g4f_model,
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

        if preset:
            url = preset.get("url", "") or ""
            if preset.get("url_tpl"):
                model = preset.get("default_model", "") or ""
                tpl = preset.get("url_tpl") or ""
                url = tpl.format(model=model) if "{model}" in tpl else tpl

                if preset.get("add_key") and preset.get("key"):
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}key={preset['key']}"

            effective_gemini = bool(preset.get("gemini_case", False))
            if preset.get("gemini_case") is None:
                if preset.get("gemini_case_override") is not None:
                    effective_gemini = bool(preset.get("gemini_case_override"))
                else:
                    try:
                        state = self.event_bus.emit_and_wait(
                            Events.ApiPresets.LOAD_PRESET_STATE,
                            {"id": preset.get("id")},
                            timeout=1.0
                        )
                        if state and state[0]:
                            effective_gemini = bool(state[0].get("gemini_case", False))
                    except Exception as e:
                        logger.warning(f"[ApiPresetResolver] Failed to load preset state: {e}")

            reserve_keys = preset.get("reserve_keys", []) or []
            if not isinstance(reserve_keys, list):
                reserve_keys = []

            return PresetSettings(
                api_key=str(preset.get("key", "") or ""),
                api_url=str(url or ""),
                api_model=str(preset.get("default_model", "") or ""),
                make_request=bool(preset.get("use_request", False)),
                gemini_case=bool(effective_gemini),
                is_g4f=bool(preset.get("is_g4f", False)),
                g4f_model=str(preset.get("default_model", "") or "") if preset.get("is_g4f", False) else "",
                preset_name=str(preset.get("name", "Unknown") or "Unknown"),
                reserve_keys=[str(k) for k in reserve_keys if str(k).strip()],
            )

        return PresetSettings(
            api_key="",
            api_url="",
            api_model="",
            make_request=False,
            gemini_case=False,
            is_g4f=False,
            g4f_model="",
            preset_name="Fallback",
            reserve_keys=[],
        )

    def _load_preset_full(self, preset_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if not preset_id:
            return None
        try:
            preset_data = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL,
                {"id": int(preset_id)},
                timeout=1.0
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
            attempt_index=attempt - 1
        )
        if not new_key or new_key == preset.api_key:
            return preset

        new_url = preset.api_url
        if preset.make_request and "key=" in (new_url or ""):
            new_url = re.sub(r"key=[^&]*", f"key={new_key}", new_url)

        return replace(preset, api_key=new_key, api_url=new_url)