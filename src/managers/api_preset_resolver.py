# src/managers/api_preset_resolver.py
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from core.events import Events
from core.services import use
from services.contracts import ApiPresetService, ProtocolBuilderService
from main_logger import logger
from managers.protocol_registry import get_protocol_registry


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
    distribute_keys: bool = False
    generation_overrides: Dict[str, Any] = field(default_factory=dict)
    openrouter_routing: Dict[str, Any] = field(default_factory=dict)

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
        # Round-robin для режима «Всегда распределять» (ключ словарей — имя пресета).
        self._distribute_counter: Dict[str, int] = {}
        self._distribute_base: Dict[str, int] = {}

    # ---------------------------
    # Public API
    # ---------------------------

    def resolve(self, preset_id: Optional[int] = None, *, model_override: Optional[str] = None) -> PresetSettings:
        if preset_id is None:
            preset_id = self.settings.get("LAST_API_PRESET_ID", 0)

        preset = self._load_preset_full(preset_id)
        if not preset:
            preset_id = self._pick_fallback_preset_id()
            preset = self._load_preset_full(preset_id)

        reg = get_protocol_registry()

        # Resolve protocol
        protocol_id = str((preset or {}).get("protocol_id") or "").strip()
        proto = reg.get(protocol_id) if protocol_id else None
        if not proto:
            proto = reg.pick_default()
            protocol_id = proto.id if proto else ""

        dialect_id = str(getattr(proto, "dialect", "") or "")
        provider_name = str(getattr(proto, "provider", "") or "")

        # Core fields from preset
        preset_name = str((preset or {}).get("name", "Unknown") or "Unknown")
        api_model = str((preset or {}).get("default_model", "") or "")
        if model_override is not None:
            mo = str(model_override or "").strip()
            if mo:
                api_model = mo
        api_key = str((preset or {}).get("key", "") or "")

        reserve_keys = (preset or {}).get("reserve_keys", []) or []
        if not isinstance(reserve_keys, list):
            reserve_keys = []
        reserve_keys = [str(k) for k in reserve_keys if str(k).strip()]
        distribute_keys = bool((preset or {}).get("reserve_keys_distribute", False))

        # Build base URL (no auth logic here)
        base_url = self._compute_base_url(preset or {}, api_model)

        # Protocol overrides (only for custom presets with explicit base=None)
        base_present = isinstance(preset, dict) and ("base" in preset)
        base_is_none = bool(base_present and preset.get("base") is None)

        protocol_overrides = (preset or {}).get("protocol_overrides") if isinstance(preset, dict) else None
        if not isinstance(protocol_overrides, dict):
            protocol_overrides = {}

        # transforms/capabilities: apply overrides here (protocol-level semantics)
        transforms = list(getattr(proto, "transforms", []) or [])
        capabilities = dict(getattr(proto, "capabilities", {}) or {})

        if base_is_none and protocol_overrides:
            ot = protocol_overrides.get("transforms")
            if isinstance(ot, list):
                transforms = [t for t in ot if isinstance(t, dict) and t.get("id")]

            oc = protocol_overrides.get("capabilities")
            if isinstance(oc, dict):
                for k, v in oc.items():
                    capabilities[str(k)] = v

        # headers: let ProtocolsController build final headers/auth,
        # but allow preset overrides to contribute extra headers.
        extra_headers: Dict[str, str] = {}
        if base_is_none and isinstance(protocol_overrides.get("headers"), dict):
            extra_headers = {
                str(k): str(v)
                for k, v in (protocol_overrides.get("headers") or {}).items()
                if k and v is not None
            }

        final_url, final_headers = self._build_http_request_via_protocols_controller(
            protocol_id=protocol_id,
            url=base_url,
            api_key=api_key,
            extra_headers=extra_headers,
        )

        generation_overrides = (preset or {}).get("generation_overrides") if isinstance(preset, dict) else None
        if not isinstance(generation_overrides, dict):
            generation_overrides = {}

        openrouter_routing = (preset or {}).get("openrouter_routing") if isinstance(preset, dict) else None
        if not isinstance(openrouter_routing, dict):
            openrouter_routing = {}

        return PresetSettings(
            protocol_id=protocol_id,
            dialect_id=dialect_id,
            provider_name=provider_name,
            headers=final_headers,
            transforms=transforms,
            capabilities=capabilities,
            api_key=api_key,
            api_url=final_url,
            api_model=api_model,
            preset_name=preset_name,
            reserve_keys=reserve_keys,
            distribute_keys=distribute_keys,
            generation_overrides=generation_overrides,
            openrouter_routing=openrouter_routing,
        )

    def resolve_chain(self, preset_id: Optional[int] = None, *, max_depth: int = 6) -> List[PresetSettings]:
        """
        Resolve main preset followed by its configured fallbacks (in order).
        Each fallback may carry its own model override.
        Skips duplicates by (preset_id, model_override) pair.
        Stops at max_depth entries total to prevent runaway chains.
        """
        if preset_id is None:
            try:
                preset_id = int(self.settings.get("LAST_API_PRESET_ID", 0) or 0)
            except Exception:
                preset_id = 0

        chain: List[PresetSettings] = []
        seen_keys: set = set()

        # Main preset
        try:
            main = self.resolve(preset_id)
            chain.append(main)
            seen_keys.add((int(preset_id) if preset_id else 0, str(main.api_model or "")))
        except Exception as e:
            logger.error(f"[ApiPresetResolver] resolve_chain: main resolve failed: {e}", exc_info=True)

        # Fallback entries are stored in the main preset dict
        main_raw = self._load_preset_full(preset_id) or {}
        fallbacks_raw = main_raw.get("fallbacks") or []
        if not isinstance(fallbacks_raw, list):
            fallbacks_raw = []

        for fb in fallbacks_raw:
            if len(chain) >= max_depth:
                break
            try:
                if isinstance(fb, dict):
                    fb_pid = fb.get("preset_id", fb.get("id"))
                    fb_model = str(fb.get("model") or "").strip()
                else:
                    fb_pid = fb
                    fb_model = ""
                fb_pid = int(fb_pid)
            except Exception:
                continue
            if fb_pid <= 0:
                continue

            try:
                ps = self.resolve(fb_pid, model_override=fb_model or None)
            except Exception as e:
                logger.warning(f"[ApiPresetResolver] fallback resolve failed for {fb_pid}: {e}")
                continue

            key = (fb_pid, str(ps.api_model or ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            chain.append(ps)

        return chain

    def resolve_preset_id_by_name(self, display_name: str) -> Optional[int]:
        if not display_name:
            return None
        try:
            meta = use(ApiPresetService).list_meta()
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

    def apply_key_rotation(self, preset: PresetSettings, attempt: int) -> PresetSettings:
        """
        Rotates api_key across reserve_keys and rebuilds (url, headers) via protocol factory,
        so bearer/query auth stays consistent without dialect-specific logic.
        """
        if not preset.reserve_keys:
            return preset

        key_index = self._resolve_key_index(preset, attempt)
        if key_index <= 0 and not preset.distribute_keys:
            return preset

        new_key = self.select_key_for_attempt(
            current_key=preset.api_key,
            reserve_keys=preset.reserve_keys,
            attempt_index=key_index,
        )
        if not new_key or new_key == preset.api_key:
            return preset

        # Rebuild url+headers through protocol factory using *existing api_url* as base.
        # This lets query key get replaced and bearer header get updated.
        new_url, new_headers = self._build_http_request_via_protocols_controller(
            protocol_id=preset.protocol_id,
            url=preset.api_url,
            api_key=new_key,
            extra_headers=preset.headers or {},
        )

        return replace(preset, api_key=new_key, api_url=new_url, headers=new_headers)

    def _resolve_key_index(self, preset: PresetSettings, attempt: int) -> int:
        """Индекс ключа в списке [main, *reserve] для данной попытки."""
        if not preset.distribute_keys:
            return max(0, attempt - 1)

        key = preset.preset_name or ""
        if attempt <= 1:
            base = self._distribute_counter.get(key, 0)
            self._distribute_counter[key] = base + 1
            self._distribute_base[key] = base
        else:
            base = self._distribute_base.get(key, 0)
        return base + max(0, attempt - 1)

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

    # ---------------------------
    # Internal helpers
    # ---------------------------

    def _load_preset_full(self, preset_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if not preset_id:
            return None
        try:
            return use(ApiPresetService).get_full(int(preset_id))
        except Exception as e:
            logger.error(f"[ApiPresetResolver] Failed to load preset: {e}", exc_info=True)
        return None

    def _pick_fallback_preset_id(self) -> Optional[int]:
        try:
            meta = use(ApiPresetService).list_meta()
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

    def _compute_base_url(self, preset: Dict[str, Any], model: str) -> str:
        """
        Compute URL from preset dict without applying any auth logic.
        """
        url_tpl = str(preset.get("url_tpl", "") or "")
        if url_tpl:
            try:
                return url_tpl.format(model=str(model or "")) if "{model}" in url_tpl else url_tpl
            except Exception:
                return url_tpl
        return str(preset.get("url", "") or "")

    def _build_http_request_via_protocols_controller(
        self,
        *,
        protocol_id: str,
        url: str,
        api_key: str,
        extra_headers: Dict[str, str] | None,
    ) -> tuple[str, Dict[str, str]]:
        """
        Asks ProtocolBuilderService to produce final url+headers according to protocol auth rules.
        Falls back to registry-local minimal behavior if the service is unavailable.
        """
        try:
            built = use(ProtocolBuilderService).build_http_request(
                protocol_id=str(protocol_id or "").strip(),
                url=str(url or ""),
                api_key=str(api_key or ""),
                headers=dict(extra_headers or {}),
            )
            if isinstance(built, dict) and built.get("url") and isinstance(built.get("headers"), dict):
                return str(built["url"]), dict(built["headers"])
        except Exception as e:
            logger.warning(f"[ApiPresetResolver] build_http_request failed, fallback: {e}")

        # Fallback (should rarely happen): use protocol registry directly
        reg = get_protocol_registry()
        proto = reg.get(protocol_id) if protocol_id else reg.pick_default()

        headers: Dict[str, str] = {}
        if proto:
            headers.update(dict(getattr(proto, "headers", {}) or {}))
            auth = dict(getattr(proto, "auth", {}) or {})
            mode = str(auth.get("mode") or "").strip().lower()

            # conservative fallback: do not guess too much
            if mode == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers.pop("Authorization", None)

        headers.update({str(k): str(v) for k, v in (extra_headers or {}).items() if k and v is not None})
        return str(url or ""), headers
