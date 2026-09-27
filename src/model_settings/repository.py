from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from core.app_paths import settings_path
from .schema import SchemaError, SettingsSchema


class SchemaRepository:
    """Versioned JSON catalog; bundled resources also work inside a zipapp."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory if directory is not None else settings_path("APIModelSchemas")
        self._lock = RLock()
        self._signature = None
        self._cached = {}
        self._defaults = None

    def catalog(self) -> dict[str, SettingsSchema]:
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self._defaults is None:
                bundled = files("model_settings").joinpath("defaults")
                self._defaults = {}
                for resource in sorted(bundled.iterdir(), key=lambda item: item.name):
                    if resource.name.endswith(".json"):
                        schema = SettingsSchema.from_dict(json.loads(resource.read_text(encoding="utf-8")))
                        self._defaults[schema.data["id"]] = schema
                        destination = self.directory / resource.name
                        if not destination.exists():
                            self._write(destination, schema.data)
            paths = sorted(self.directory.glob("*.json"))
            signature = tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in paths)
            if signature == self._signature:
                return deepcopy(self._cached)
            result = dict(self._defaults)
            external = {}
            for path in paths:
                try:
                    schema = SettingsSchema.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))
                except (ValueError, OSError) as exc:
                    raise SchemaError(f"{path.name}: {exc}") from exc
                identifier = schema.data["id"]
                if identifier in external:
                    raise SchemaError(f"Duplicate external schema id: {identifier}")
                external[identifier] = schema
                if identifier not in result or schema.data["revision"] >= result[identifier].data["revision"]:
                    result[identifier] = schema
            self._signature = signature
            self._cached = deepcopy(result)
            return result

    def get(self, identifier: str) -> SettingsSchema:
        result = self.catalog().get(identifier)
        if result is None:
            raise SchemaError(f"Settings schema not found: {identifier}")
        return result

    def import_file(self, source: str | Path) -> SettingsSchema:
        schema = SettingsSchema.from_dict(json.loads(Path(source).read_text(encoding="utf-8-sig")))
        return self.install(schema)

    def install(self, schema: SettingsSchema) -> SettingsSchema:
        with self._lock:
            current = self.catalog().get(schema.data["id"])
            if current and current.data["dialect"] != schema.data["dialect"]:
                raise SchemaError("A schema update cannot change its dialect")
            if current and schema.data["revision"] < current.data["revision"]:
                raise SchemaError("A schema update cannot downgrade its revision")
            destination = self.directory / (schema.data["id"] + ".json")
            for path in self.directory.glob("*.json"):
                if json.loads(path.read_text(encoding="utf-8-sig")).get("id") == schema.data["id"]:
                    destination = path
                    break
            self._write(destination, schema.data)
            self._signature = None
        return schema

    def export(self, schema: SettingsSchema, path: str | Path) -> None:
        self._write(Path(path), schema.data)

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(deepcopy(data), stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
