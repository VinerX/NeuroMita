from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import re
from typing import Any, Mapping


class SchemaError(ValueError):
    """A settings definition cannot be interpreted by this schema version."""


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    minimum: Any = None
    maximum: Any = None


def localized_text(value: Any, language: str) -> str:
    if isinstance(value, Mapping):
        translations = {str(key).lower(): text for key, text in value.items()}
        return str(translations.get(str(language).lower()) or translations.get("en") or translations.get("ru") or "")
    return str(value or "")


def parse_value(field: Mapping[str, Any], value: Any) -> tuple[Any, ValidationIssue | None]:
    kind = field["type"]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, ValidationIssue("required")
    try:
        if kind == "boolean":
            if type(value) is not bool:
                return None, ValidationIssue("boolean")
            parsed = value
        elif kind == "integer":
            if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value).strip()):
                return None, ValidationIssue("integer")
            parsed = int(value)
        elif kind == "number":
            if isinstance(value, bool):
                return None, ValidationIssue("number")
            parsed = float(value)
            if not math.isfinite(parsed):
                return None, ValidationIssue("finite")
        elif kind == "string":
            if not isinstance(value, str):
                return None, ValidationIssue("string")
            parsed = value
        else:
            parsed = deepcopy(value)
            import json
            json.dumps(parsed, allow_nan=False)
            if kind == "array" and not isinstance(parsed, list):
                return None, ValidationIssue("array")
            if kind == "object" and not isinstance(parsed, dict):
                return None, ValidationIssue("object")
    except (ValueError, TypeError, OverflowError):
        return None, ValidationIssue("number" if kind == "number" else kind)
    if "enum" in field and parsed not in field["enum"]:
        return None, ValidationIssue("enum")
    if kind in {"number", "integer"} and parsed not in field.get("special_values", []):
        low, high = field.get("minimum"), field.get("maximum")
        if (low is not None and parsed < low) or (high is not None and parsed > high):
            return None, ValidationIssue("range", low, high)
    if kind in {"string", "array"}:
        low, high = field.get("min_length"), field.get("max_length")
        if (low is not None and len(parsed) < low) or (high is not None and len(parsed) > high):
            return None, ValidationIssue("length", low, high)
    return parsed, None


_PROTECTED_ROOTS = {
    "model", "messages", "contents", "systemInstruction", "tools", "tool_choice",
    "toolConfig", "stream", "stream_options", "response_format", "provider",
    "session_id", "api_key", "headers", "options",
}
_PROTECTED_GENERATION = {"responseMimeType", "responseSchema", "responseJsonSchema"}


def validate_path(path: Any, dialect: str) -> None:
    if not isinstance(path, list) or not path or not all(
        isinstance(part, str) and bool(part.strip()) for part in path
    ):
        raise SchemaError("Parameter path must be a nonempty array of object keys")
    if path[0] in _PROTECTED_ROOTS:
        raise SchemaError(f"Request behavior is not a model parameter: {path[0]}")
    if dialect == "gemini_generate_content":
        if len(path) < 2 or path[0] != "generationConfig" or path[1] in _PROTECTED_GENERATION:
            raise SchemaError("Gemini parameters must belong to generationConfig, excluding response schemas")
    elif path[0] == "generationConfig":
        raise SchemaError("generationConfig requires the Gemini dialect")


@dataclass(frozen=True)
class SettingsSchema:
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, source: Any) -> "SettingsSchema":
        if not isinstance(source, dict) or type(source.get("schema_version")) is not int or source["schema_version"] != 1:
            raise SchemaError("Expected a settings schema with schema_version: 1")
        data = deepcopy(source)
        allowed = {"schema_version", "id", "revision", "title", "description", "dialect", "fields", "documentation_url", "supports"}
        if set(data) - allowed:
            raise SchemaError(f"Unknown schema keys: {sorted(set(data) - allowed)}")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", str(data.get("id", ""))):
            raise SchemaError("Invalid schema id")
        if type(data.get("revision")) is not int or data["revision"] < 1:
            raise SchemaError("Schema revision must be a positive integer")
        for label in ("title", "description"):
            if label in data and not isinstance(data[label], (str, dict)):
                raise SchemaError(f"Invalid localized schema text: {label}")
            if isinstance(data.get(label), dict) and not all(isinstance(key, str) and isinstance(value, str) for key, value in data[label].items()):
                raise SchemaError("Localized schema text must contain language codes and strings")
        if data.get("dialect") not in {"openai_chat_completions", "gemini_generate_content", "g4f"}:
            raise SchemaError("Unsupported settings dialect")
        supports = data.get("supports", {})
        if not isinstance(supports, dict) or set(supports) - {"structured_output", "tools_native", "streaming"} or not all(type(value) is bool for value in supports.values()):
            raise SchemaError("Model supports must contain boolean structured_output, tools_native or streaming flags")
        if not isinstance(data.get("fields"), list):
            raise SchemaError("Schema fields must be an array")
        ids, paths = set(), []
        field_keys = {"id", "path", "type", "title", "description", "default", "enabled_by_default", "minimum", "maximum", "enum", "special_values", "exclusive_group", "min_length", "max_length"}
        for item in data["fields"]:
            if not isinstance(item, dict) or set(item) - field_keys:
                raise SchemaError("Invalid field definition or unknown field keys")
            identifier = item.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", identifier) or identifier in ids:
                raise SchemaError("Field ids must be unique identifiers")
            ids.add(identifier)
            if item.get("type") not in {"number", "integer", "boolean", "string", "array", "object"}:
                raise SchemaError(f"Unsupported parameter type: {identifier}")
            validate_path(item.get("path"), data["dialect"])
            path = tuple(item["path"])
            if any(path[:len(other)] == other or other[:len(path)] == path for other in paths):
                raise SchemaError("Parameter paths overlap")
            paths.append(path)
            if "enabled_by_default" in item and type(item["enabled_by_default"]) is not bool:
                raise SchemaError("enabled_by_default must be boolean")
            if item["type"] not in {"number", "integer"} and any(key in item for key in ("minimum", "maximum", "special_values")):
                raise SchemaError("Numeric constraints require a numeric parameter")
            if item["type"] not in {"string", "array"} and any(key in item for key in ("min_length", "max_length")):
                raise SchemaError("Length constraints require a string or array parameter")
            for bound in ("minimum", "maximum", "min_length", "max_length"):
                if bound in item and (isinstance(item[bound], bool) or not isinstance(item[bound], (int, float)) or not math.isfinite(item[bound])):
                    raise SchemaError(f"Invalid field bound: {identifier}.{bound}")
            if "minimum" in item and "maximum" in item and item["minimum"] > item["maximum"]:
                raise SchemaError("Field minimum exceeds maximum")
            for bound in ("min_length", "max_length"):
                if bound in item and (type(item[bound]) is not int or item[bound] < 0):
                    raise SchemaError("Length constraints must be nonnegative integers")
            if "min_length" in item and "max_length" in item and item["min_length"] > item["max_length"]:
                raise SchemaError("Field minimum length exceeds maximum length")
            if "special_values" in item and (not isinstance(item["special_values"], list) or not all(type(value) in {int, float} and math.isfinite(value) for value in item["special_values"])):
                raise SchemaError("special_values must contain finite numbers")
            if "exclusive_group" in item and (not isinstance(item["exclusive_group"], str) or not item["exclusive_group"]):
                raise SchemaError("exclusive_group must be a nonempty string")
            if "enum" in item and (not isinstance(item["enum"], list) or not item["enum"]):
                raise SchemaError("Field enum must be a nonempty array")
            if "enum" in item:
                without_enum = {key: value for key, value in item.items() if key != "enum"}
                if any(parse_value(without_enum, option)[1] is not None for option in item["enum"]):
                    raise SchemaError("Field enum values do not satisfy its type and constraints")
            for label in ("title", "description"):
                if label in item and not isinstance(item[label], (str, dict)):
                    raise SchemaError(f"Invalid localized field text: {identifier}.{label}")
                if isinstance(item.get(label), dict) and not all(isinstance(key, str) and isinstance(value, str) for key, value in item[label].items()):
                    raise SchemaError("Localized text must contain language codes and strings")
            _, issue = parse_value(item, item.get("default"))
            if issue:
                raise SchemaError(f"Invalid field default: {identifier} ({issue.code})")
        schema = cls(data)
        default_enabled = [f["id"] for f in schema.fields if f.get("enabled_by_default", False)]
        if schema.validate({}, default_enabled):
            raise SchemaError("Default fields contain conflicting parameters")
        return schema

    @property
    def fields(self) -> list[dict[str, Any]]:
        return self.data["fields"]

    def validate(self, values: Mapping[str, Any], enabled: list[str]) -> dict[str, ValidationIssue]:
        issues = {}
        by_id = {item["id"]: item for item in self.fields}
        groups: dict[str, list[str]] = {}
        for identifier in enabled:
            item = by_id.get(identifier)
            if item is None:
                issues[identifier] = ValidationIssue("unknown")
                continue
            _, issue = parse_value(item, values.get(identifier, item["default"]))
            if issue:
                issues[identifier] = issue
            group = item.get("exclusive_group")
            if group:
                groups.setdefault(group, []).append(identifier)
        for members in groups.values():
            if len(members) > 1:
                issues.update({identifier: ValidationIssue("exclusive") for identifier in members})
        return issues

    def compile(self, values: Mapping[str, Any], enabled: list[str]) -> dict[str, Any]:
        issues = self.validate(values, enabled)
        if issues:
            raise SchemaError("Invalid model settings: " + ", ".join(f"{key}: {issue.code}" for key, issue in issues.items()))
        result: dict[str, Any] = {}
        for item in self.fields:
            if item["id"] not in enabled:
                continue
            value, _ = parse_value(item, values.get(item["id"], item["default"]))
            parent = result
            for key in item["path"][:-1]:
                parent = parent.setdefault(key, {})
            parent[item["path"][-1]] = value
        return result
