# src/controllers/api_presets_controller.py
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field

from core.events import get_event_bus, Events, Event
from main_logger import logger

from utils import _
import threading
import requests


@dataclass
class PresetMeta:
    id: int
    name: str
    pricing: str
    protocol_id: str = ""
    dialect_id: str = ""
    provider_name: str = ""


@dataclass
class ApiTemplate:
    id: int
    name: str
    pricing: str = "mixed"
    url: str = ""
    url_tpl: str = ""
    default_model: str = ""
    known_models: List[str] = field(default_factory=list)

    protocol_id: str = ""

    test_url: str = ""
    filter_fn: str = ""
    documentation_url: str = ""
    models_url: str = ""
    key_url: str = ""


@dataclass
class UserPreset:
    id: int
    name: str
    base: Optional[int] = None
    pricing: str = "mixed"
    default_model: str = ""
    url: str = ""
    key: str = ""
    reserve_keys: List[str] = field(default_factory=list)
    protocol_id: str = ""
    protocol_overrides: Dict[str, Any] = field(default_factory=dict)


class ApiPresetsController:
    def __init__(self):
        self.event_bus = get_event_bus()

        self.templates_path = Path("Settings/api_templates.json")
        self.presets_path = Path("Settings/api_presets.json")
        self.legacy_path = Path("Settings/presets.json")

        self.templates: Dict[int, ApiTemplate] = {}
        self.presets: Dict[int, UserPreset] = {}
        self.presets_order: List[int] = []

        self.current_preset_id: Optional[int] = None
        self.preset_states: Dict[int, Dict[str, Any]] = {}

        self._io_lock = threading.RLock()

        self._load_data()
        self._subscribe_to_events()

        self._migrate_old_api_keys()

    def _mask_key(self, s: str) -> str:
        s = str(s or "")
        if len(s) <= 8:
            return "***"
        return s[:3] + "***" + s[-3:]

    def _atomic_write_json(self, path: Path, data: Dict[str, Any]) -> bool:
        try:
            with self._io_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(tmp, path)
            return True
        except Exception as e:
            logger.error(f"Failed to write json atomically: {path}: {e}", exc_info=True)
            return False

    def _normalize_presets_order(self, order: Any) -> List[int]:
        result: List[int] = []
        seen = set()

        if not isinstance(order, list):
            order = []

        for x in order:
            try:
                pid = int(x)
            except Exception:
                continue
            if pid in self.presets and pid not in seen:
                result.append(pid)
                seen.add(pid)

        for pid in sorted(self.presets.keys()):
            if pid not in seen:
                result.append(pid)
                seen.add(pid)

        return result

    def _find_template_id_by_url(self, url: str) -> Optional[int]:
        u = (url or "").strip().lower()
        if not u:
            return None

        if "api.mistral.ai" in u or "mistral.ai" in u:
            for tid, tpl in self.templates.items():
                if "mistral" in (tpl.name or "").lower():
                    return int(tid)

        if "openrouter.ai" in u:
            for tid, tpl in self.templates.items():
                if "openrouter" in (tpl.name or "").lower():
                    return int(tid)

        if "generativelanguage.googleapis.com" in u:
            for tid, tpl in self.templates.items():
                if "google" in (tpl.name or "").lower() or "ai studio" in (tpl.name or "").lower():
                    return int(tid)

        if "intelligence.io.solutions" in u:
            for tid, tpl in self.templates.items():
                if "ai.i" in (tpl.name or "").lower() or "ai.io" in (tpl.name or "").lower():
                    return int(tid)

        for tid, tpl in self.templates.items():
            if tpl.url and tpl.url.strip().lower() == u:
                return int(tid)
            if tpl.url_tpl and tpl.url_tpl.strip().lower() in u:
                return int(tid)

        return None

    def _find_existing_custom_preset_by_name(self, name: str) -> Optional[int]:
        target = str(name or "")
        for pid, up in self.presets.items():
            if str(up.name or "") == target:
                return int(pid)
        return None

    def _migrate_old_api_keys(self):
        """
        Безопасная миграция NM_API_*:
        - создаём/обновляем кастомный пресет из старых ключей
        - НЕ удаляем LAST_API_PRESET_ID и прочее
        - удаляем NM_API_* только если миграция успешна
        """
        try:
            from managers.settings_manager import SettingsManager
            sm = SettingsManager.instance
            if not sm:
                logger.warning("SettingsManager не инициализирован, миграция пропущена")
                return

            settings = sm.settings

            if settings.get("_API_MIGRATION_DONE", False):
                return

            legacy_url = str(settings.get("NM_API_URL", "") or "").strip()
            legacy_model = str(settings.get("NM_API_MODEL", "") or "").strip()
            legacy_key = str(settings.get("NM_API_KEY", "") or "").strip()
            legacy_res = str(settings.get("NM_API_KEY_RES", "") or "").strip()

            has_any_legacy = any([
                bool(legacy_url),
                bool(legacy_model),
                bool(legacy_key),
                bool(legacy_res),
                "NM_API_REQ" in settings,
                "GEMINI_CASE" in settings,
            ])

            if not has_any_legacy:
                settings["_API_MIGRATION_DONE"] = True
                sm.save_settings()
                return

            base_id = self._find_template_id_by_url(legacy_url)
            if base_id is None:
                logger.warning("Legacy NM_API_URL не соответствует известным шаблонам; миграция пропущена (ключи не удалены)")
                return

            reserve_keys: List[str] = []
            if legacy_res:
                reserve_keys = [k.strip() for k in legacy_res.split() if k.strip()]

            migrated_name = "Migrated Legacy API"
            existing_id = self._find_existing_custom_preset_by_name(migrated_name)

            payload = {
                "id": existing_id,
                "name": migrated_name,
                "base": int(base_id),
                "default_model": legacy_model,
                "key": legacy_key,
                "reserve_keys": reserve_keys,
            }

            saved_id = self._on_save_custom_preset(Event(
                name=Events.ApiPresets.SAVE_CUSTOM_PRESET,
                data={"data": payload}
            ))

            if not isinstance(saved_id, int) or saved_id <= 0:
                logger.warning("Миграция не смогла создать пресет; ключи не удалены")
                return

            last_id = settings.get("LAST_API_PRESET_ID", None)
            last_id_valid = isinstance(last_id, int) and (last_id in self.presets or last_id in self.templates)

            if not last_id_valid:
                settings["LAST_API_PRESET_ID"] = int(saved_id)
                self.current_preset_id = int(saved_id)

            keys_to_delete = [
                "API_PROVIDER",
                "NM_API_URL",
                "NM_API_MODEL",
                "NM_API_KEY",
                "NM_API_REQ",
                "GEMINI_CASE",
                "NM_API_KEY_RES",
                "API_PROVIDER_DATA",
                "CUSTOM_API_PRESETS",
                "GEMINI_CASE_UI",
            ]

            for k in keys_to_delete:
                if k in settings:
                    try:
                        del settings[k]
                    except Exception:
                        pass

            settings["_API_MIGRATION_DONE"] = True
            sm.save_settings()

            logger.info(
                f"Legacy API migrated to preset '{migrated_name}' (ID={saved_id}), "
                f"base={base_id}, key={self._mask_key(legacy_key)}"
            )

        except Exception as e:
            logger.error(f"Ошибка при миграции старых ключей API: {e}", exc_info=True)

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.ApiPresets.GET_PRESET_LIST, self._on_get_preset_list, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.GET_PRESET_FULL, self._on_get_preset_full, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.SAVE_CUSTOM_PRESET, self._on_save_custom_preset, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.DELETE_CUSTOM_PRESET, self._on_delete_custom_preset, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.EXPORT_PRESET, self._on_export_preset, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.IMPORT_PRESET, self._on_import_preset, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.TEST_CONNECTION, self._on_test_connection, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.SAVE_PRESET_STATE, self._on_save_preset_state, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.LOAD_PRESET_STATE, self._on_load_preset_state, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.GET_CURRENT_PRESET_ID, self._on_get_current_preset_id, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.SET_CURRENT_PRESET_ID, self._on_set_current_preset_id, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.UPDATE_PRESET_MODELS, self._on_update_preset_models, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.SAVE_PRESETS_ORDER, self._on_save_presets_order, weak=False)

    # ---------- Загрузка/сохранение ----------

    def _load_data(self):
        try:
            self._refresh_templates_from_code()

            if self.presets_path.exists():
                self._load_presets_only()
                logger.info(f"Loaded {len(self.templates)} templates (refreshed from code) and {len(self.presets)} user presets")
                return

            if self.legacy_path.exists():
                self._migrate_presets_from_legacy()
                logger.info(f"Migrated legacy user presets. Templates: {len(self.templates)}, Presets: {len(self.presets)}")
                return

            self._create_default_presets()
            logger.info(f"Created default user presets. Templates: {len(self.templates)}, Presets: {len(self.presets)}")
        except Exception as e:
            logger.error(f"Failed to load preset data, fallback to full defaults: {e}", exc_info=True)
            self._create_default_data()

    def _refresh_templates_from_code(self):
        from presets.api_templates import API_TEMPLATES_DATA

        code_templates: Dict[int, ApiTemplate] = {p["id"]: ApiTemplate(**p) for p in API_TEMPLATES_DATA}

        file_templates_raw: Dict[int, Dict[str, Any]] = {}
        if self.templates_path.exists():
            try:
                with open(self.templates_path, "r", encoding="utf-8") as f:
                    tdata = json.load(f)
                file_templates_raw = {int(k): v for k, v in tdata.get("templates", {}).items()}
            except Exception as e:
                logger.warning(f"Failed to read existing api_templates.json for merge: {e}")

        for tid, tpl in code_templates.items():
            merged_models = set(tpl.known_models or [])
            existing_tpl = file_templates_raw.get(tid)
            if isinstance(existing_tpl, dict):
                km = existing_tpl.get("known_models", []) or []
                if km:
                    merged_models.update(km)
            tpl.known_models = sorted(list(merged_models), reverse=True)

        self.templates = code_templates
        self._save_templates()
        logger.info(f"Refreshed templates from code and saved. Total templates: {len(self.templates)}")

    def _user_preset_from_dict(self, raw: Any, fallback_id: Optional[int] = None) -> Optional[UserPreset]:
        if not isinstance(raw, dict):
            return None

        pid = raw.get("id", fallback_id)
        if pid is None:
            return None
        try:
            pid = int(pid)
        except Exception:
            return None

        base = raw.get("base", None)
        if base is not None:
            try:
                base = int(base)
            except Exception:
                base = None

        name = str(raw.get("name") or f"Preset {pid}")

        rk = raw.get("reserve_keys", []) or []
        if not isinstance(rk, list):
            rk = []
        reserve_keys = [str(k) for k in rk if str(k).strip()]

        protocol_id = str(raw.get("protocol_id", "") or "").strip()

        url = str(raw.get("url", "") or "")
        if base is not None:
            url = ""

        po = raw.get("protocol_overrides", {}) or {}
        if not isinstance(po, dict):
            po = {}

        return UserPreset(
            id=pid,
            name=name,
            base=base,
            pricing=str(raw.get("pricing", "mixed") or "mixed"),
            default_model=str(raw.get("default_model", "") or ""),
            url=url,
            key=str(raw.get("key", "") or ""),
            reserve_keys=reserve_keys,
            protocol_id=protocol_id,
            protocol_overrides=dict(po),
        )

    def _load_presets_only(self):
        """
        Загружает Settings/api_presets.json.
        Поддерживает несколько форматов:
        - новый: {"presets": { "1001": {...}, ... }, "order": [...]}
        - полу-старый: {"presets": [ {...}, {...} ], "order": [...]}
        - legacy-like: {"custom": {..}, "custom_order": [...]}
        Автоматически:
        - отфильтровывает/нормализует данные
        - ремапит id, если они конфликтуют с template id
        """
        try:
            with self._io_lock:
                with open(self.presets_path, "r", encoding="utf-8") as f:
                    pdata = json.load(f)

            presets: Dict[int, UserPreset] = {}

            raw_order = None

            # --- detect format ---
            if isinstance(pdata, dict) and "presets" in pdata:
                raw_presets = pdata.get("presets") or {}
                raw_order = pdata.get("order", None)

                if isinstance(raw_presets, dict):
                    for k, v in raw_presets.items():
                        fid = None
                        try:
                            fid = int(k)
                        except Exception:
                            fid = None
                        up = self._user_preset_from_dict(v, fallback_id=fid)
                        if up:
                            presets[up.id] = up

                elif isinstance(raw_presets, list):
                    for v in raw_presets:
                        up = self._user_preset_from_dict(v)
                        if up:
                            presets[up.id] = up

            elif isinstance(pdata, dict) and "custom" in pdata:
                # legacy-like but stored in api_presets.json
                raw_presets = pdata.get("custom") or {}
                raw_order = pdata.get("custom_order", None)

                if isinstance(raw_presets, dict):
                    for _k, v in raw_presets.items():
                        up = self._user_preset_from_dict(v)
                        if up:
                            presets[up.id] = up

            elif isinstance(pdata, list):
                # very old: list of presets
                for v in pdata:
                    up = self._user_preset_from_dict(v)
                    if up:
                        presets[up.id] = up
            else:
                presets = {}

            self.presets = presets

            if raw_order is None:
                raw_order = list(self.presets.keys())

            self.presets_order = self._normalize_presets_order(raw_order)

            # --- NEW: if protocol_id is missing on custom base=None, try infer from url ---
            self._infer_missing_protocol_ids()

            # --- NEW: remap conflicting ids (custom id collides with template id) ---
            changed = self._remap_conflicting_preset_ids()
            if changed:
                logger.warning("Conflicting preset IDs were remapped to avoid template collisions.")
                self._save_presets()

        except Exception as e:
            logger.error(f"Failed to load presets file: {e}", exc_info=True)
            self.presets = {}
            self.presets_order = []

    def _infer_missing_protocol_ids(self) -> None:
        """
        Для кастомных пресетов без base, у которых нет protocol_id:
        пытаемся вывести protocol_id по url через match шаблона.
        """
        for pid, up in list(self.presets.items()):
            try:
                if up.base is not None:
                    continue
                if str(getattr(up, "protocol_id", "") or "").strip():
                    continue

                tid = self._find_template_id_by_url(up.url or "")
                if tid and tid in self.templates:
                    tpl = self.templates[tid]
                    if getattr(tpl, "protocol_id", ""):
                        up.protocol_id = str(tpl.protocol_id or "").strip()
            except Exception:
                continue


    def _remap_conflicting_preset_ids(self) -> bool:
        """
        Если у user preset id совпадает с template id, это приводит к тому,
        что GET_PRESET_FULL по этому id вернёт template, а не user preset.
        Ремапим такие id на новые.
        """
        conflicts = [pid for pid in self.presets.keys() if pid in self.templates]
        if not conflicts:
            return False

        # prepare new ids
        used = set(self.templates.keys()) | set(self.presets.keys())
        next_id = max(used, default=1000) + 1

        mapping: Dict[int, int] = {}
        for old_id in sorted(conflicts):
            while next_id in used:
                next_id += 1
            mapping[old_id] = next_id
            used.add(next_id)
            next_id += 1

        # apply mapping
        new_presets: Dict[int, UserPreset] = {}
        for old_id, up in self.presets.items():
            if old_id in mapping:
                new_id = mapping[old_id]
                up.id = new_id
                new_presets[new_id] = up
            else:
                new_presets[old_id] = up

        self.presets = new_presets

        # update order
        new_order: List[int] = []
        for x in self.presets_order:
            try:
                xi = int(x)
            except Exception:
                continue
            new_order.append(mapping.get(xi, xi))
        self.presets_order = self._normalize_presets_order(new_order)

        # update current_preset_id if needed
        if self.current_preset_id in mapping:
            self.current_preset_id = mapping[self.current_preset_id]

        return True

    def _migrate_presets_from_legacy(self):
        try:
            with open(self.legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.presets = {}
            for _, preset_data in (data.get("custom", {}) or {}).items():
                up = self._user_preset_from_dict(preset_data)
                if up:
                    self.presets[up.id] = up

            raw_order = data.get("custom_order", list(self.presets.keys()))
            self.presets_order = self._normalize_presets_order(raw_order)

            self._save_templates()
            self._save_presets()
            logger.info(f"Migrated legacy custom presets only. Presets: {len(self.presets)}")
        except Exception as e:
            logger.error(f"Failed to migrate legacy presets: {e}", exc_info=True)
            self._create_default_presets()

    def _create_default_presets(self):
        from presets.api_presets import DEFAULT_USER_PRESETS
        self.presets = {}
        for p in DEFAULT_USER_PRESETS:
            up = self._user_preset_from_dict(p)
            if up:
                self.presets[up.id] = up
        self.presets_order = list(self.presets.keys())
        self._save_presets()

    def _create_default_data(self):
        from presets.api_templates import API_TEMPLATES_DATA
        from presets.api_presets import DEFAULT_USER_PRESETS

        self.templates = {p["id"]: ApiTemplate(**p) for p in API_TEMPLATES_DATA}

        self.presets = {}
        for p in DEFAULT_USER_PRESETS:
            up = self._user_preset_from_dict(p)
            if up:
                self.presets[up.id] = up

        self.presets_order = list(self.presets.keys())

        self._save_templates()
        self._save_presets()
        logger.info("Created default templates and presets (fallback)")

    def _save_templates(self) -> bool:
        data = {"templates": {str(t.id): asdict(t) for t in self.templates.values()}}
        return self._atomic_write_json(self.templates_path, data)

    def _save_presets(self) -> bool:
        data = {
            "presets": {str(p.id): asdict(p) for p in self.presets.values()},
            "order": self.presets_order,
        }
        return self._atomic_write_json(self.presets_path, data)

    def _generate_new_id(self) -> int:
        all_ids = set(self.templates.keys()) | set(self.presets.keys())
        return max(all_ids, default=1000) + 1

    # ---------- Хелперы ----------

    def _effective_protocol_id_for(self, up: UserPreset, tpl: Optional[ApiTemplate]) -> str:
        pid = ""
        if tpl and getattr(tpl, "protocol_id", ""):
            pid = str(tpl.protocol_id or "").strip()
        if not pid:
            pid = str(getattr(up, "protocol_id", "") or "").strip()
        if not pid:
            from managers.protocol_registry import get_protocol_registry
            reg = get_protocol_registry()
            d = reg.pick_default()
            pid = d.id if d else ""
        return pid

    def _build_effective_preset_dict(self, preset_id: int) -> Optional[Dict[str, Any]]:
        if preset_id in self.templates:
            return asdict(self.templates[preset_id])

        p = self.presets.get(preset_id)
        if not p:
            return None

        tpl = self.templates.get(p.base) if p.base else None
        protocol_id = self._effective_protocol_id_for(p, tpl)

        result = {
            "id": p.id,
            "name": p.name,
            "pricing": (tpl.pricing if tpl else p.pricing),
            "base": p.base,
            "protocol_id": protocol_id,

            "url": p.url if not tpl else (tpl.url if tpl and tpl.url else ""),
            "url_tpl": tpl.url_tpl if tpl else "",

            "default_model": p.default_model or (tpl.default_model if tpl else ""),
            "known_models": (tpl.known_models if tpl else []),

            "test_url": tpl.test_url if tpl else "",
            "filter_fn": tpl.filter_fn if tpl else "",
            "documentation_url": tpl.documentation_url if tpl else "",
            "models_url": tpl.models_url if tpl else "",
            "key_url": tpl.key_url if tpl else "",

            "key": p.key,
            "reserve_keys": p.reserve_keys or [],
        }
        return result

    # ---------- Обработчики событий ----------

    def _on_get_preset_list(self, event: Event):
        from managers.protocol_registry import get_protocol_registry
        reg = get_protocol_registry()

        meta = {"builtin": [], "custom": []}

        for tpl in sorted(self.templates.values(), key=lambda t: t.id):
            proto = reg.get(tpl.protocol_id) if tpl.protocol_id else None
            meta["builtin"].append(PresetMeta(
                id=tpl.id,
                name=tpl.name,
                pricing=tpl.pricing,
                protocol_id=str(tpl.protocol_id or ""),
                dialect_id=str(getattr(proto, "dialect", "") or ""),
                provider_name=str(getattr(proto, "provider", "") or ""),
            ))

        ordered_custom: List[UserPreset] = []
        for pid in self.presets_order:
            if pid in self.presets:
                ordered_custom.append(self.presets[pid])
        for pid, up in self.presets.items():
            if pid not in self.presets_order:
                ordered_custom.append(up)
                self.presets_order.append(pid)

        for up in ordered_custom:
            tpl = self.templates.get(up.base) if up.base else None
            protocol_id = self._effective_protocol_id_for(up, tpl)
            proto = reg.get(protocol_id) if protocol_id else None

            meta["custom"].append(PresetMeta(
                id=up.id,
                name=up.name,
                pricing=(tpl.pricing if tpl else up.pricing),
                protocol_id=protocol_id,
                dialect_id=str(getattr(proto, "dialect", "") or ""),
                provider_name=str(getattr(proto, "provider", "") or ""),
            ))
        return meta

    def _on_get_preset_full(self, event: Event):
        preset_id = (event.data or {}).get("id")
        try:
            preset_id = int(preset_id)
        except Exception:
            return None
        return self._build_effective_preset_dict(preset_id)

    def _on_save_custom_preset(self, event: Event):
        data = (event.data or {}).get("data") or {}
        logger.info(f"[ApiPresets] SAVE_CUSTOM_PRESET called, keys={list(data.keys())}")

        preset_id = data.get("id")
        if preset_id is None:
            preset_id = self._generate_new_id()
            data["id"] = preset_id

        try:
            preset_id = int(preset_id)
        except Exception:
            logger.error(f"[ApiPresets] SAVE_CUSTOM_PRESET invalid id={preset_id}")
            return None

        base = data.get("base", None)
        if base is not None:
            try:
                base = int(base)
            except Exception:
                base = None

        name = str(data.get("name") or f"Preset {preset_id}")

        up = self.presets.get(preset_id) or UserPreset(id=preset_id, name=name)
        up.name = name
        up.base = base
        up.pricing = str(data.get("pricing", up.pricing) or up.pricing)
        up.default_model = str(data.get("default_model", up.default_model) or up.default_model)
        up.url = str(data.get("url", up.url) or up.url) if not base else ""
        up.key = str(data.get("key", up.key) or up.key)

        if "protocol_id" in data:
            up.protocol_id = str(data.get("protocol_id") or "").strip()

        if "protocol_overrides" in data:
            po = data.get("protocol_overrides") or {}
            if not isinstance(po, dict):
                po = {}
            up.protocol_overrides = dict(po)

        if "reserve_keys" in data:
            rk = data.get("reserve_keys") or []
            if not isinstance(rk, list):
                rk = []
            up.reserve_keys = [str(k) for k in rk if str(k).strip()]

        self.presets[preset_id] = up
        if preset_id not in self.presets_order:
            self.presets_order.append(preset_id)
        self.presets_order = self._normalize_presets_order(self.presets_order)

        ok = self._save_presets()
        if not ok:
            logger.error(f"[ApiPresets] SAVE_CUSTOM_PRESET failed to save presets file for id={preset_id}")
            return None

        logger.info(f"[ApiPresets] Preset saved id={preset_id}, name='{up.name}', base={up.base}, protocol_id='{up.protocol_id}'")
        self.event_bus.emit(Events.ApiPresets.PRESET_SAVED, {"id": preset_id})
        return preset_id

    def _on_delete_custom_preset(self, event: Event):
        preset_id = (event.data or {}).get("id")
        try:
            preset_id = int(preset_id)
        except Exception:
            return False

        if preset_id in self.presets:
            del self.presets[preset_id]
            if preset_id in self.preset_states:
                del self.preset_states[preset_id]
            if preset_id in self.presets_order:
                self.presets_order.remove(preset_id)
            self._save_presets()
            self.event_bus.emit(Events.ApiPresets.PRESET_DELETED, {"id": preset_id})
            return True
        return False

    def _on_save_presets_order(self, event: Event):
        order = (event.data or {}).get("order", None)
        if order is None:
            return False
        self.presets_order = self._normalize_presets_order(order)
        self._save_presets()
        return True

    def _on_export_preset(self, event: Event):
        preset_id = (event.data or {}).get("id")
        path = (event.data or {}).get("path")
        try:
            preset_id = int(preset_id)
        except Exception:
            return False

        preset_dict = self._build_effective_preset_dict(preset_id)
        if not preset_dict:
            return False

        state = self.preset_states.get(preset_id, {})
        if state:
            preset_dict.update(state)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset_dict, f, indent=2, ensure_ascii=False)
        return True

    def _on_import_preset(self, event: Event):
        path = (event.data or {}).get("path")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            new_id = self._generate_new_id()

            base = data.get("base", None)
            if base is not None:
                try:
                    base = int(base)
                except Exception:
                    base = None

            up = UserPreset(
                id=new_id,
                name=str(data.get("name", f"Preset {new_id}")),
                base=base,
                pricing=str(data.get("pricing", "mixed") or "mixed"),
                default_model=str(data.get("default_model", "") or ""),
                url=str(data.get("url", "") or "") if not base else "",
                key=str(data.get("key", "") or ""),
                reserve_keys=[str(k) for k in (data.get("reserve_keys", []) or []) if str(k).strip()],
                protocol_id=str(data.get("protocol_id", "") or "").strip(),
            )

            self.presets[new_id] = up
            self.presets_order.append(new_id)
            self._save_presets()

            if "key" in data:
                self.preset_states[new_id] = {"key": data["key"]}

            self.event_bus.emit(Events.ApiPresets.PRESET_IMPORTED, {"id": new_id})
            return new_id
        except Exception as e:
            logger.error(f"Failed to import preset: {e}", exc_info=True)
            return None

    def _on_test_connection(self, event: Event):
        preset_id = (event.data or {}).get("id")
        base_id = (event.data or {}).get("base")
        key = str((event.data or {}).get("key", "") or "").strip()

        try:
            preset_id = int(preset_id) if preset_id else None
        except Exception:
            preset_id = None

        try:
            base_id = int(base_id) if base_id else None
        except Exception:
            base_id = None

        p_tpl: Optional[ApiTemplate] = None

        if base_id:
            p_tpl = self.templates.get(base_id)
        elif preset_id and preset_id in self.presets:
            up = self.presets[preset_id]
            if up.base and up.base in self.templates:
                p_tpl = self.templates[up.base]
        elif preset_id and preset_id in self.templates:
            p_tpl = self.templates[preset_id]

        if not p_tpl or not p_tpl.test_url:
            logger.warning(f"No test_url for preset {preset_id} and base {base_id}")
            self.event_bus.emit(Events.ApiPresets.TEST_FAILED, {
                "id": preset_id,
                "error": "no_test_url",
                "message": _("URL для тестирования не найден", "Test URL not found"),
            })
            return

        # если ключ не передали, попробуем взять из пресета
        if not key and preset_id and preset_id in self.presets:
            key = str(self.presets[preset_id].key or "").strip()

        threading.Thread(
            target=self._sync_test_connection,
            args=(preset_id or 0, p_tpl, key),
            daemon=True
        ).start()

    def _sync_test_connection(self, preset_id: int, tpl: ApiTemplate, key: str):

        protocol_id = str(getattr(tpl, "protocol_id", "") or "").strip()
        url = str(tpl.test_url or "")

        # через протокол-фабрику собираем url+headers
        res = self.event_bus.emit_and_wait(
            Events.Protocols.BUILD_HTTP_REQUEST,
            {
                "protocol_id": protocol_id,
                "url": url,
                "api_key": str(key or ""),
                "headers": {},  # можно потом доп.заголовки
            },
            timeout=1.0
        )

        built = res[0] if res else None
        if not isinstance(built, dict):
            self.event_bus.emit(Events.ApiPresets.TEST_RESULT, {
                "id": preset_id,
                "success": False,
                "message": "Protocol HTTP builder not available",
            })
            return

        final_url = str(built.get("url") or "")
        headers = built.get("headers") if isinstance(built.get("headers"), dict) else {}
        safe_url = str(built.get("safe_url") or final_url)

        logger.info(f"Testing connection to {safe_url} with headers: {list(headers.keys())}")

        timeout = 30 if "openrouter.ai" in final_url.lower() else 15

        try:
            resp = requests.get(final_url, headers=headers, timeout=timeout)
            status = resp.status_code
            text = resp.text

            success = False
            message = ""
            models: List[str] = []

            if status == 200:
                try:
                    data = json.loads(text)
                    if tpl.filter_fn:
                        from utils.api_filters import apply_filter
                        data = apply_filter(tpl.filter_fn, data)

                    if "models" in data:
                        models = [m.get("name", "").split("/")[-1] for m in data.get("models", []) if m.get("name")]
                        success = True
                        message = f"Found {len(models)} models"
                    elif "data" in data and isinstance(data["data"], list):
                        models = [m.get("id", "").split("/")[-1] for m in data.get("data", []) if m.get("id")]
                        success = True
                        message = f"Found {len(models)} models"
                    else:
                        success = True
                        message = "Connection successful"
                except Exception as e:
                    success = False
                    message = f"Parsing error: {str(e)}"
            elif status == 401:
                message = "Invalid API key (Unauthorized)"
            elif status == 403:
                message = "Access forbidden. Check API key permissions."
            elif status == 404:
                message = "Endpoint not found"
            elif status == 400:
                message = "Bad request. Check URL and parameters."
            elif status == 429:
                message = "Rate limit exceeded"
            else:
                message = f"HTTP {status}"

            self.event_bus.emit(Events.ApiPresets.TEST_RESULT, {
                "id": preset_id,
                "success": bool(success),
                "message": message,
                "models": models,
            })
        except requests.Timeout:
            self.event_bus.emit(Events.ApiPresets.TEST_RESULT, {
                "id": preset_id,
                "success": False,
                "message": f"Connection timeout ({timeout}s)",
            })
        except requests.ConnectionError:
            self.event_bus.emit(Events.ApiPresets.TEST_RESULT, {
                "id": preset_id,
                "success": False,
                "message": "Connection failed. Check internet connection.",
            })
        except Exception as e:
            logger.error(f"Test error for {preset_id}: {e}", exc_info=True)
            self.event_bus.emit(Events.ApiPresets.TEST_RESULT, {
                "id": preset_id,
                "success": False,
                "message": f"Error: {str(e)}",
            })

    def _on_update_preset_models(self, event: Event):
        preset_id = (event.data or {}).get("id")
        new_models = (event.data or {}).get("models", [])
        if not new_models:
            return False
        logger.info(f"Received model update request for preset {preset_id}, but not saving to template (feature disabled)")
        return False

    def _on_save_preset_state(self, event: Event):
        preset_id = (event.data or {}).get("id")
        state = (event.data or {}).get("state") or {}
        if not preset_id or not state:
            return False

        try:
            preset_id = int(preset_id)
        except Exception:
            return False

        if preset_id in self.presets:
            up = self.presets[preset_id]

            if "key" in state:
                up.key = str(state["key"] or "")
            if "model" in state:
                up.default_model = str(state["model"] or "")
            if "url" in state and not up.base:
                up.url = str(state["url"] or "")
            if "protocol_id" in state and not up.base:
                up.protocol_id = str(state["protocol_id"] or "").strip()
            if "reserve_keys" in state:
                rk = state.get("reserve_keys") or []
                if isinstance(rk, list):
                    up.reserve_keys = [str(k) for k in rk if str(k).strip()]

            ok = self._save_presets()
            if not ok:
                return False

        self.preset_states[preset_id] = state
        return True

    def _on_load_preset_state(self, event: Event):
        preset_id = (event.data or {}).get("id")
        try:
            preset_id = int(preset_id)
        except Exception:
            return {}

        state = self.preset_states.get(preset_id, {}) or {}

        # UI helpers: если модель не задана в state, подставим default_model
        if not state.get("model"):
            preset_dict = self._build_effective_preset_dict(preset_id)
            if preset_dict and preset_dict.get("default_model"):
                state = {**state, "model": preset_dict["default_model"]}

        # для кастомного пресета можно подсказать url
        if not state.get("url"):
            up = self.presets.get(preset_id)
            if up and not up.base and up.url:
                state = {**state, "url": up.url}

        return state

    def _on_get_current_preset_id(self, event: Event):
        return self.current_preset_id

    def _on_set_current_preset_id(self, event: Event):
        self.current_preset_id = (event.data or {}).get("id")
        return True
    