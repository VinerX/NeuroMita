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
        """
        Безопасный для логов словарь (без ключей).
        """
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
    """
    Единственная ответственность:
    - получить пресет из ApiPresetsController через EventBus
    - собрать url/model/key/gemini_case
    - дать удобные методы для ротации ключей и резолва id по имени
    """

    def __init__(self, settings: Any, event_bus: Any):
        self.settings = settings
        self.event_bus = event_bus

    def resolve(self, preset_id: Optional[int] = None) -> PresetSettings:
        """
        Загружает настройки из пресета по ID.
        Если preset_id не указан — берёт текущий из LAST_API_PRESET_ID.
        Полностью повторяет старую логику ChatModel.load_preset_settings().
        """
        if preset_id is None:
            preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        try:
            preset_data = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL,
                {"id": preset_id},
                timeout=1.0
            )
        except Exception as e:
            logger.error(f"[ApiPresetResolver] Failed to load preset via bus: {e}", exc_info=True)
            preset_data = None

        if preset_data and preset_data[0]:
            preset = preset_data[0]

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
                try:
                    state = self.event_bus.emit_and_wait(
                        Events.ApiPresets.LOAD_PRESET_STATE,
                        {"id": preset_id},
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

        # --- fallback (как раньше) ---
        reserve_keys_str = self.settings.get("NM_API_KEY_RES", "")
        reserve_keys = (
            [key.strip() for key in str(reserve_keys_str).split() if key.strip()]
            if reserve_keys_str else []
        )

        return PresetSettings(
            api_key=str(self.settings.get("NM_API_KEY", "") or ""),
            api_url=str(self.settings.get("NM_API_URL", "") or ""),
            api_model=str(self.settings.get("NM_API_MODEL", "") or ""),
            make_request=bool(self.settings.get("NM_API_REQ", False)),
            gemini_case=bool(self.settings.get("GEMINI_CASE", False)),
            is_g4f=bool(self.settings.get("gpt4free", False)),
            g4f_model=str(self.settings.get("gpt4free_model", "") or ""),
            preset_name="Fallback",
            reserve_keys=reserve_keys,
        )

    def resolve_preset_id_by_name(self, display_name: str) -> Optional[int]:
        """
        Возвращает ID пользовательского пресета по его отображаемому имени.
        Полный перенос логики ChatModel._get_preset_id_by_name().
        """
        if not display_name:
            return None
        try:
            meta_res = self.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = meta_res[0] if meta_res else None
            if not meta:
                return None
            custom_list = meta.get("custom", []) or []
            for pm in custom_list:
                if getattr(pm, "name", None) == display_name:
                    return getattr(pm, "id", None)
        except Exception as e:
            logger.error(f"[ApiPresetResolver] Failed to resolve preset id by name '{display_name}': {e}", exc_info=True)
        return None

    def select_key_for_attempt(
        self,
        current_key: str,
        reserve_keys: List[str],
        attempt_index: int
    ) -> Optional[str]:
        """
        Поведение = старый ChatModel.GetReserveKey().
        attempt_index — 0-based (в старом коде передавали attempt-1).
        """
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
        """
        Если attempt > 1 и есть reserve_keys — выбираем новый ключ циклически.
        Поведение сохраняет старый код: на 1й попытке не меняем ключ.
        """
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
        # В старом коде URL обновлялся только когда там уже есть key=...
        if preset.make_request and "key=" in (new_url or ""):
            new_url = re.sub(r"key=[^&]*", f"key={new_key}", new_url)

        return replace(preset, api_key=new_key, api_url=new_url)