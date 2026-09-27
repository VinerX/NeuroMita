from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .repository import SchemaRepository
from .schema import SchemaError, SettingsSchema


class ModelSettingsService:
    """Resolve definitions and values; transports receive only a compiled object."""

    def __init__(self, repository: SchemaRepository | None = None):
        self.repository = repository if repository is not None else SchemaRepository()

    def default_id(self, dialect: str, suggested: str = "") -> str:
        identifier = suggested or {"gemini_generate_content": "google-level", "g4f": "g4f"}.get(dialect, "openai-compatible")
        schema = self.repository.get(identifier)
        self.check_dialect(schema, dialect)
        return identifier

    @staticmethod
    def check_dialect(schema: SettingsSchema, dialect: str) -> None:
        if schema.data["dialect"] != dialect:
            raise SchemaError(f"Settings dialect {schema.data['dialect']} does not match {dialect}")

    def create(self, identifier: str) -> dict[str, Any]:
        schema = self.repository.get(identifier)
        return {
            "version": 1,
            "schema_id": identifier,
            "values": {item["id"]: deepcopy(item["default"]) for item in schema.fields},
            "enabled": [item["id"] for item in schema.fields if item.get("enabled_by_default", False)],
        }

    def resolve(self, document: Any, dialect: str) -> tuple[SettingsSchema, dict[str, Any]]:
        if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
            raise SchemaError("Expected model settings with version: 1")
        if set(document) - {"version", "schema_id", "schema_override", "values", "enabled", "support_overrides"}:
            raise SchemaError("Unknown model settings keys")
        identifier = document.get("schema_id")
        if not isinstance(identifier, str) or not identifier:
            raise SchemaError("Model settings require schema_id")
        override = document.get("schema_override")
        schema = SettingsSchema.from_dict(override) if override is not None else self.repository.get(identifier)
        if schema.data["id"] != identifier:
            raise SchemaError("Preset schema id does not match its definition")
        self.check_dialect(schema, dialect)
        values, enabled = document.get("values", {}), document.get("enabled", [])
        supports = document.get("support_overrides", {})
        if not isinstance(supports, dict) or set(supports) - {"structured_output", "tools_native", "streaming"} or not all(type(value) is bool for value in supports.values()):
            raise SchemaError("Invalid preset model support flags")
        if not isinstance(values, dict) or not isinstance(enabled, list) or not all(isinstance(item, str) for item in enabled) or len(set(enabled)) != len(enabled):
            raise SchemaError("Settings values must be an object and enabled must contain unique field ids")
        normalized = deepcopy(document)
        normalized["values"] = deepcopy(values)
        normalized["values"].update({item["id"]: deepcopy(values.get(item["id"], item["default"])) for item in schema.fields})
        normalized["enabled"] = list(enabled)
        return schema, normalized

    def compile(self, document: Any, dialect: str) -> dict[str, Any]:
        schema, state = self.resolve(document, dialect)
        return schema.compile(state["values"], state["enabled"])

    def capabilities(self, document: dict, dialect: str, protocol_capabilities: dict) -> dict:
        schema, state = self.resolve(document, dialect)
        supported = {**schema.data.get("supports", {}), **state.get("support_overrides", {})}
        capabilities = deepcopy(protocol_capabilities)
        for name, allowed in supported.items():
            if name == "structured_output":
                capabilities["native_structured_output"] = allowed
            else:
                capabilities[name] = bool(capabilities.get(name, False)) and allowed
        return capabilities

    def import_definition(self, path, dialect: str) -> SettingsSchema:
        import json
        from pathlib import Path
        definition = SettingsSchema.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        self.check_dialect(definition, dialect)
        return self.repository.install(definition)

    def export_definition(self, document: dict, dialect: str, path) -> None:
        schema, _state = self.resolve(document, dialect)
        self.repository.export(schema, path)

    def for_preset(self, preset: Mapping[str, Any], dialect: str, settings: Any = None) -> dict[str, Any]:
        document = preset.get("model_settings")
        if document is not None:
            return self.resolve(document, dialect)[1]
        from .migration import migrate_generation_settings
        return migrate_generation_settings(self, preset, dialect, settings)

    def change_schema(self, document: dict, identifier: str, dialect: str) -> dict:
        schema = self.repository.get(identifier)
        self.check_dialect(schema, dialect)
        updated = self.create(identifier)
        old_values = document.get("values", {})
        old_enabled = document.get("enabled", [])
        for field in schema.fields:
            key = field["id"]
            if key in old_values:
                updated["values"][key] = deepcopy(old_values[key])
        updated["enabled"] = [key for key in old_enabled if key in updated["values"]]
        if document.get("support_overrides"):
            updated["support_overrides"] = deepcopy(document["support_overrides"])
        return updated

    def customize(self, document: dict, definition: dict, dialect: str) -> dict:
        schema = SettingsSchema.from_dict(definition)
        self.check_dialect(schema, dialect)
        updated = deepcopy(document)
        updated["schema_id"] = schema.data["id"]
        updated["schema_override"] = schema.data
        fields = {field["id"] for field in schema.fields}
        updated["enabled"] = [key for key in document["enabled"] if key in fields]
        return self.resolve(updated, dialect)[1]
