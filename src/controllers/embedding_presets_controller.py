# src/controllers/embedding_presets_controller.py
"""Controller for embedding provider presets.

Manages built-in presets (defined in code) and user-defined custom presets
(persisted in Settings/embedding_presets.json).

Read API is exposed through ``EmbeddingPresetService``. EventBus carries only
mutation commands and resulting facts:
    EmbeddingPresets.SAVE_CUSTOM_PRESET → int | None   (saved preset id)
    EmbeddingPresets.DELETE_CUSTOM_PRESET → bool
    EmbeddingPresets.RENAME_CUSTOM_PRESET → bool
    EmbeddingPresets.REORDER_PRESETS    → bool
    EmbeddingPresets.TEST_PRESET        → fires TEST_RESULT async
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.app_paths import settings_path
from core.events import Event, Events, get_event_bus
from core.task_supervisor import task_supervisor
from services.contracts import EmbeddingPresetService
from main_logger import logger


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class UserEmbedPreset:
    id: int
    name: str
    base: Optional[str] = None          # builtin preset id (None = fully custom)
    provider_name: str = "local"
    model: str = ""                     # HF id / path / API model name
    url: str = ""                       # API endpoint URL (empty for local)
    key: str = ""
    reserve_keys: List[str] = field(default_factory=list)
    query_prefix: str = ""
    dimensions: int = 0
    headers: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


# ── Controller ─────────────────────────────────────────────────────────────────

class EmbeddingPresetsController(EmbeddingPresetService):
    _CUSTOM_ID_START = 1001

    def __init__(self) -> None:
        self.event_bus = get_event_bus()
        self.presets_path = settings_path("embedding_presets.json", create_parent=True)
        self._io_lock = threading.RLock()

        self.custom_presets: Dict[int, UserEmbedPreset] = {}
        self.custom_order: List[int] = []
        self.builtin_overrides: Dict[str, Dict[str, Any]] = {}

        self._load()
        self._subscribe()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.presets_path.exists():
            return
        try:
            with self._io_lock:
                with open(self.presets_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            raw_presets = data.get("presets") or {}
            raw_order = data.get("order") or []
            raw_builtin_overrides = data.get("builtin_overrides") or {}

            for k, v in raw_presets.items():
                p = self._from_dict(v, fallback_id=k)
                if p:
                    self.custom_presets[p.id] = p

            self.custom_order = self._normalize_order(raw_order)
            if isinstance(raw_builtin_overrides, dict):
                for k, v in raw_builtin_overrides.items():
                    if isinstance(v, dict):
                        self.builtin_overrides[str(k)] = dict(v)
            logger.info(f"[EmbedPresets] Loaded {len(self.custom_presets)} custom presets")
        except Exception as e:
            logger.error(f"[EmbedPresets] Failed to load: {e}", exc_info=True)

    def _save(self) -> bool:
        try:
            with self._io_lock:
                self.presets_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.presets_path.with_suffix(".json.tmp")
                data = {
                    "presets": {str(p.id): asdict(p) for p in self.custom_presets.values()},
                    "order": self.custom_order,
                    "builtin_overrides": self.builtin_overrides,
                }
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(tmp, self.presets_path)
            return True
        except Exception as e:
            logger.error(f"[EmbedPresets] Failed to save: {e}", exc_info=True)
            return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _from_dict(self, raw: Any, fallback_id: Any = None) -> Optional[UserEmbedPreset]:
        if not isinstance(raw, dict):
            return None
        pid = raw.get("id", fallback_id)
        try:
            pid = int(pid)
        except Exception:
            return None
        rk = raw.get("reserve_keys") or []
        return UserEmbedPreset(
            id=pid,
            name=str(raw.get("name") or f"Preset {pid}"),
            base=raw.get("base") or None,
            provider_name=str(raw.get("provider_name") or "local"),
            model=str(raw.get("model") or ""),
            url=str(raw.get("url") or ""),
            key=str(raw.get("key") or ""),
            reserve_keys=[str(k) for k in rk if str(k).strip()],
            query_prefix=str(raw.get("query_prefix") or ""),
            dimensions=int(raw.get("dimensions") or 0),
            headers=dict(raw.get("headers") or {}),
            extra=dict(raw.get("extra") or {}),
        )

    def _normalize_order(self, order: Any) -> List[int]:
        seen: set = set()
        result: List[int] = []
        for x in (order if isinstance(order, list) else []):
            try:
                i = int(x)
            except Exception:
                continue
            if i in self.custom_presets and i not in seen:
                result.append(i)
                seen.add(i)
        for pid in sorted(self.custom_presets.keys()):
            if pid not in seen:
                result.append(pid)
        return result

    def _new_id(self) -> int:
        used = set(self.custom_presets.keys())
        nid = max(used | {self._CUSTOM_ID_START - 1}) + 1
        return nid

    def _build_full_config(self, preset_id: Any) -> Optional[Dict[str, Any]]:
        """Return resolved config dict for a preset id (builtin or custom)."""
        from presets.embedding_provider_presets import get_builtin_preset

        # Try builtin first (string ids like "google_gemini_embed")
        if isinstance(preset_id, str):
            bp = get_builtin_preset(preset_id)
            if bp:
                return self._expand_builtin(bp)

        # Try numeric custom
        try:
            pid = int(preset_id)
        except Exception:
            return None

        up = self.custom_presets.get(pid)
        if not up:
            return None
        return self._expand_custom(up)

    @staticmethod
    def _resolve_local_model_name(model: str) -> str:
        if not model:
            return ""
        try:
            from handlers.embedding_presets import get_preset
            preset = get_preset(str(model))
            if preset:
                return str(preset.get("hf_name") or model)
        except Exception:
            pass
        return str(model)

    def _expand_builtin(self, bp: Dict[str, Any]) -> Dict[str, Any]:
        """Expand a built-in preset into a full config."""
        override = self.builtin_overrides.get(str(bp.get("id"))) or {}
        model = bp.get("default_model") or ""
        url = bp.get("default_url") or ""
        provider = bp.get("provider") or "local"
        model = str(override.get("model") or model)
        url = str(override.get("url") or url)
        query_prefix = str(override.get("query_prefix") or "")
        reserve_keys = list(override.get("reserve_keys") or [])
        api_key = override.get("key") or None
        dimensions = int(override.get("dimensions") or bp.get("default_dimensions") or 0)
        headers = dict(bp.get("default_headers") or {})
        extra_headers = override.get("headers")
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)
        extra_cfg = dict(bp.get("default_extra") or {})
        ov_extra = override.get("extra")
        if isinstance(ov_extra, dict):
            extra_cfg.update(ov_extra)
        resolved_model = self._resolve_local_model_name(model) if provider == "local" else model
        return {
            "id": bp["id"],
            "name": bp["name"],
            "provider_name": provider,
            "model": model,
            "hf_name": resolved_model if provider == "local" else "",
            "api_url": url if provider != "local" else resolved_model,
            "api_key": api_key,
            "reserve_keys": reserve_keys,
            "headers": headers,
            "query_prefix": query_prefix,
            "dimensions": dimensions,
            "extra": extra_cfg,
            "key_url": bp.get("key_url") or "",
            "known_models": list(bp.get("known_models") or []),
            "is_builtin": True,
            "db_model_key": f"{provider}:{model}" if provider != "local" else resolved_model,
        }

    def _expand_custom(self, up: UserEmbedPreset) -> Dict[str, Any]:
        """Expand a user preset into a full config, merging defaults from base."""
        from presets.embedding_provider_presets import get_builtin_preset

        bp = get_builtin_preset(up.base) if up.base else None
        provider = up.provider_name or (bp["provider"] if bp else "local")
        model = up.model or (bp.get("default_model") or "" if bp else "")
        url = up.url or (bp.get("default_url") or "" if bp else "")
        headers = dict(bp.get("default_headers") or {}) if bp else {}
        headers.update(up.headers)
        extra_cfg = dict(bp.get("default_extra") or {}) if bp else {}
        extra_cfg.update(dict(up.extra or {}))

        resolved_model = self._resolve_local_model_name(model) if provider == "local" else model
        db_key = f"{provider}:{model}" if provider != "local" else resolved_model

        return {
            "id": up.id,
            "name": up.name,
            "base": up.base,
            "provider_name": provider,
            "model": model,
            "hf_name": resolved_model if provider == "local" else "",
            "api_url": url if provider != "local" else resolved_model,
            "api_key": up.key or None,
            "reserve_keys": list(up.reserve_keys),
            "headers": headers,
            "query_prefix": up.query_prefix,
            "dimensions": up.dimensions,
            "extra": extra_cfg,
            "key_url": bp.get("key_url") if bp else "",
            "known_models": list(bp.get("known_models") or []) if bp else [],
            "is_builtin": False,
            "db_model_key": db_key,
        }

    # ── Event subscriptions ───────────────────────────────────────────────────

    def _subscribe(self) -> None:
        E = Events.EmbeddingPresets
        sub = self.event_bus.subscribe
        sub(E.SAVE_CUSTOM_PRESET, self._on_save, weak=False)
        sub(E.DELETE_CUSTOM_PRESET, self._on_delete, weak=False)
        sub(E.RENAME_CUSTOM_PRESET, self._on_rename, weak=False)
        sub(E.REORDER_PRESETS, self._on_reorder, weak=False)
        sub(E.TEST_PRESET, self._on_test, weak=False)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def list_meta(self) -> Dict[str, Any]:
        from presets.embedding_provider_presets import list_builtin_presets

        builtins = [
            {
                "id": preset["id"],
                "name": preset["name"],
                "is_builtin": True,
                "provider": preset["provider"],
                "is_local": preset.get("is_local", False),
            }
            for preset in list_builtin_presets()
        ]
        custom = []
        for preset_id in self.custom_order:
            preset = self.custom_presets.get(preset_id)
            if preset:
                custom.append(
                    {
                        "id": preset.id,
                        "name": preset.name,
                        "is_builtin": False,
                        "provider": preset.provider_name,
                        "is_local": preset.provider_name == "local",
                    }
                )
        return {"builtin": builtins, "custom": custom}

    def get_full(self, preset_id: Any) -> Optional[Dict[str, Any]]:
        return self._build_full_config(preset_id)

    def _on_save(self, event: Event):
        data = (event.data or {}).get("data") or {}
        pid = data.get("id")
        if isinstance(pid, str):
            from presets.embedding_provider_presets import get_builtin_preset
            bp = get_builtin_preset(pid)
            if not bp:
                logger.error(f"[EmbedPresets] SAVE: invalid builtin id={pid}")
                return None

            ov = dict(self.builtin_overrides.get(pid) or {})
            for src, dst in (
                ("model", "model"),
                ("url", "url"),
                ("key", "key"),
                ("query_prefix", "query_prefix"),
                ("dimensions", "dimensions"),
                ("headers", "headers"),
                ("extra", "extra"),
            ):
                if src in data:
                    ov[dst] = data.get(src)
            if "reserve_keys" in data:
                rk = data.get("reserve_keys") or []
                ov["reserve_keys"] = [str(k) for k in rk if str(k).strip()]
            self.builtin_overrides[pid] = ov
            if not self._save():
                return None
            self.event_bus.emit(Events.EmbeddingPresets.PRESET_SAVED, {"id": pid})
            logger.info(f"[EmbedPresets] Saved builtin override id='{pid}'")
            return pid

        if pid is None:
            pid = self._new_id()
        try:
            pid = int(pid)
        except Exception:
            logger.error(f"[EmbedPresets] SAVE: invalid id={pid}")
            return None

        up = self.custom_presets.get(pid) or UserEmbedPreset(id=pid, name=f"Preset {pid}")
        up.id = pid
        if "name" in data:
            up.name = str(data["name"] or up.name)
        if "base" in data:
            up.base = data["base"] or None
        if "provider_name" in data:
            up.provider_name = str(data["provider_name"] or "local")
        if "model" in data:
            up.model = str(data["model"] or "")
        if "url" in data:
            up.url = str(data["url"] or "")
        if "key" in data:
            up.key = str(data["key"] or "")
        if "reserve_keys" in data:
            rk = data["reserve_keys"] or []
            up.reserve_keys = [str(k) for k in rk if str(k).strip()]
        if "query_prefix" in data:
            up.query_prefix = str(data["query_prefix"] or "")
        if "dimensions" in data:
            try:
                up.dimensions = int(data["dimensions"] or 0)
            except Exception:
                up.dimensions = 0
        if "headers" in data and isinstance(data["headers"], dict):
            up.headers = dict(data["headers"])
        if "extra" in data and isinstance(data["extra"], dict):
            up.extra = dict(data["extra"])

        self.custom_presets[pid] = up
        if pid not in self.custom_order:
            self.custom_order.append(pid)

        ok = self._save()
        if not ok:
            return None
        self.event_bus.emit(Events.EmbeddingPresets.PRESET_SAVED, {"id": pid})
        logger.info(f"[EmbedPresets] Saved custom preset id={pid} name='{up.name}'")
        return pid

    def save(self, data: Dict[str, Any]) -> Any:
        return self._on_save(
            Event(Events.EmbeddingPresets.SAVE_CUSTOM_PRESET, {"data": dict(data or {})})
        )

    def _on_delete(self, event: Event):
        pid = (event.data or {}).get("id")
        if isinstance(pid, str):
            if pid in self.builtin_overrides:
                del self.builtin_overrides[pid]
                self._save()
                self.event_bus.emit(Events.EmbeddingPresets.PRESET_DELETED, {"id": pid})
                return True
            return False
        try:
            pid = int(pid)
        except Exception:
            return False
        if pid in self.custom_presets:
            del self.custom_presets[pid]
            if pid in self.custom_order:
                self.custom_order.remove(pid)
            self._save()
            self.event_bus.emit(Events.EmbeddingPresets.PRESET_DELETED, {"id": pid})
            return True
        return False

    def delete(self, preset_id: Any) -> bool:
        return bool(
            self._on_delete(
                Event(Events.EmbeddingPresets.DELETE_CUSTOM_PRESET, {"id": preset_id})
            )
        )

    def _on_rename(self, event: Event):
        pid = (event.data or {}).get("id")
        new_name = str((event.data or {}).get("name") or "")
        try:
            pid = int(pid)
        except Exception:
            return False
        up = self.custom_presets.get(pid)
        if not up or not new_name:
            return False
        up.name = new_name
        self._save()
        return True

    def rename(self, preset_id: Any, name: str) -> bool:
        return bool(
            self._on_rename(
                Event(
                    Events.EmbeddingPresets.RENAME_CUSTOM_PRESET,
                    {"id": preset_id, "name": name},
                )
            )
        )

    def _on_reorder(self, event: Event):
        order = (event.data or {}).get("order") or []
        self.custom_order = self._normalize_order(order)
        self._save()
        return True

    def reorder(self, order) -> bool:
        return bool(
            self._on_reorder(
                Event(Events.EmbeddingPresets.REORDER_PRESETS, {"order": list(order or [])})
            )
        )

    def _on_test(self, event: Event):
        preset_id = (event.data or {}).get("id")
        task_supervisor().start_thread(
            self,
            "embedding-preset-test",
            self._sync_test,
            args=(preset_id,),
            replace=True,
        )

    def _sync_test(self, preset_id: Any) -> None:
        cfg = self._build_full_config(preset_id)
        if not cfg:
            self.event_bus.emit(Events.EmbeddingPresets.TEST_RESULT, {
                "id": preset_id, "success": False, "message": "Пресет не найден",
            })
            return

        try:
            from handlers.embedding_providers.registry import get_provider_for, build_request
            provider = get_provider_for(cfg)
            req = build_request(cfg, texts=["test"], is_query=True)
            results = provider.embed(req)
            vec = results[0] if results else None
            if vec is None:
                raise RuntimeError("Provider returned None")
            import numpy as np
            dim = int(vec.shape[0])
            self.event_bus.emit(Events.EmbeddingPresets.TEST_RESULT, {
                "id": preset_id, "success": True,
                "message": f"OK — dim={dim}",
                "dimensions": dim,
            })
        except Exception as e:
            self.event_bus.emit(Events.EmbeddingPresets.TEST_RESULT, {
                "id": preset_id, "success": False, "message": str(e),
            })
