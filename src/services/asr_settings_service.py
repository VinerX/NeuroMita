from __future__ import annotations

import copy
import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable

from core.app_paths import settings_path
from core.services import ServiceAlreadyRegistered, services
from services.contracts import ASRSettingsService


@dataclass(frozen=True, slots=True)
class ASRSettingsChange:
    revision: int
    engine_id: str
    kind: str


class FileASRSettingsService(ASRSettingsService):
    def __init__(self, path: str | None = None) -> None:
        self._path = str(path or settings_path("asr_settings.json", create_parent=True))
        self._lock = threading.RLock()
        self._revision = 0
        self._subscribers: list[Callable[[ASRSettingsChange], None]] = []
        self._data: dict[str, Any] = {
            "engine": "google",
            "models": {
                "google": {},
                "gigaam": {"device": "auto"},
            },
        }
        self._load()

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def selected_engine(self) -> str:
        with self._lock:
            return str(self._data.get("engine") or "google")

    def model_settings(self, engine_id: str) -> dict[str, Any]:
        normalized = str(engine_id or "").strip()
        with self._lock:
            models = self._data.get("models")
            value = models.get(normalized, {}) if isinstance(models, dict) else {}
            return copy.deepcopy(value) if isinstance(value, dict) else {}

    def set_selected_engine(self, engine_id: str) -> None:
        normalized = str(engine_id or "google").strip() or "google"
        with self._lock:
            if self._data.get("engine") == normalized:
                return
            updated = copy.deepcopy(self._data)
            updated["engine"] = normalized
            change = self._commit_locked(updated, normalized, "engine")
        self._notify(change)

    def set_model_settings(self, engine_id: str, values: dict[str, Any]) -> None:
        normalized = str(engine_id or "").strip()
        if not normalized:
            raise ValueError("engine_id is required")
        replacement = copy.deepcopy(dict(values or {}))
        with self._lock:
            updated = copy.deepcopy(self._data)
            models = updated.setdefault("models", {})
            if not isinstance(models, dict):
                models = {}
                updated["models"] = models
            if models.get(normalized) == replacement:
                return
            models[normalized] = replacement
            change = self._commit_locked(updated, normalized, "model")
        self._notify(change)

    def set_model_option(self, engine_id: str, key: str, value: Any) -> None:
        normalized = str(engine_id or "").strip()
        option = str(key or "").strip()
        if not normalized or not option:
            raise ValueError("engine_id and key are required")
        with self._lock:
            updated = copy.deepcopy(self._data)
            models = updated.setdefault("models", {})
            if not isinstance(models, dict):
                models = {}
                updated["models"] = models
            current = models.setdefault(normalized, {})
            if not isinstance(current, dict):
                current = {}
                models[normalized] = current
            if current.get(option) == value:
                return
            current[option] = copy.deepcopy(value)
            change = self._commit_locked(updated, normalized, "option")
        self._notify(change)

    def subscribe(self, callback, *, replay: bool = False):
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._subscribers.append(callback)
            revision = self._revision

        if replay:
            callback(ASRSettingsChange(revision, self.selected_engine(), "snapshot"))

        service = self

        class Subscription:
            def close(self) -> None:
                with service._lock:
                    try:
                        service._subscribers.remove(callback)
                    except ValueError:
                        pass

        return Subscription()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        with self._lock:
            engine = str(payload.get("engine") or self._data["engine"]).strip()
            models = payload.get("models")
            self._data["engine"] = engine or "google"
            if isinstance(models, dict):
                merged = copy.deepcopy(self._data["models"])
                for key, value in models.items():
                    if isinstance(value, dict):
                        merged[str(key)] = copy.deepcopy(value)
                self._data["models"] = merged

    def _commit_locked(
        self,
        updated: dict[str, Any],
        engine_id: str,
        kind: str,
    ) -> ASRSettingsChange:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(updated, stream, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)
        self._data = updated
        self._revision += 1
        return ASRSettingsChange(self._revision, engine_id, kind)

    def _notify(self, change: ASRSettingsChange) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(change)
            except Exception:
                pass


def ensure_asr_settings_service() -> ASRSettingsService:
    registry = services()
    current = registry.get_optional(ASRSettingsService)
    if current is not None:
        return current
    created = FileASRSettingsService()
    try:
        registry.register(ASRSettingsService, created)
        return created
    except ServiceAlreadyRegistered:
        return registry.get(ASRSettingsService)
