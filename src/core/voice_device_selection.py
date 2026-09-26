from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from core.cuda_precision_policy import evaluate_rvc_half_precision


_HALF_PRECISION_SOURCES = {
    "is_half": "device",
    "silero_rvc_is_half": "silero_rvc_device",
    "fsprvc_is_half": "fsprvc_rvc_device",
    "f5rvc_is_half": "f5rvc_rvc_device",
    "half": "device",
    "fsprvc_fsp_half": "fsprvc_fsp_device",
}


@dataclass(frozen=True)
class DeviceChoice:
    value: str
    label: str
    runtime_device: str


def device_half_precision_behavior(device_key: str) -> dict[str, Any]:
    return {
        "kind": "source_allowlist",
        "source": str(device_key),
        "unsupported_value": "False",
    }


class VoiceDeviceCatalog:
    def __init__(self, hardware: dict[str, Any] | None) -> None:
        self.hardware = hardware if isinstance(hardware, dict) else {}
        cuda = self.hardware.get("cuda") or {}
        self.cuda: list[DeviceChoice] = []
        for record in cuda.get("devices") or []:
            if not isinstance(record, dict):
                continue
            try:
                ordinal = int(record["ordinal"])
            except (KeyError, TypeError, ValueError):
                continue
            value = f"cuda:{ordinal}"
            name = str(record.get("name") or "").strip()
            self.cuda.append(DeviceChoice(value, f"{value} ({name})" if name else value, value))

        adapters = self.hardware.get("adapters") or self.hardware.get("accelerators") or []
        self.dml: list[DeviceChoice] = []
        seen_values: set[str] = set()
        for adapter in adapters:
            if not isinstance(adapter, dict):
                continue
            try:
                index = int(adapter.get("dxgi_index", adapter.get("index")))
            except (TypeError, ValueError):
                continue
            luid = str(adapter.get("luid") or "").strip().lower()
            value = f"dml@{luid}" if re.fullmatch(r"[0-9a-f]{16}", luid) else f"dml:{index}"
            if value in seen_values:
                value = f"dml:{index}"
            if value in seen_values:
                continue
            seen_values.add(value)
            runtime_device = f"dml:{index}"
            name = str(adapter.get("name") or "GPU").strip()
            self.dml.append(DeviceChoice(value, f"{runtime_device} ({name})", runtime_device))

        self.vendor = str(self.hardware.get("vendor") or "").strip().lower()
        if not self.vendor and self.cuda:
            self.vendor = "nvidia"
        if not self.vendor:
            self.vendor = next(
                (
                    str(item.get("vendor") or "").lower()
                    for item in adapters
                    if isinstance(item, dict) and item.get("vendor")
                ),
                "",
            )

    def expand_schema(self, schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = copy.deepcopy(schema)
        for setting in result:
            if not _device_setting(setting):
                continue
            options = setting.get("options")
            if isinstance(options, (list, tuple)):
                options = {
                    "values": list(options),
                    "default": setting.get("default", ""),
                }
                setting["options"] = options
            elif not isinstance(options, dict):
                continue
            variant = options.get(f"values_{self.vendor}") if self.vendor else None
            original = [str(value) for value in (variant if variant is not None else options.get("values")) or []]
            if not original:
                continue
            choices: list[DeviceChoice] = []
            for value in original:
                if value == "cuda" or value.startswith("cuda:"):
                    choices.extend(
                        self.cuda
                        or (
                            [DeviceChoice(value, value, value)]
                            if not self.hardware or isinstance(self.hardware.get("cuda_default_record"), dict)
                            else []
                        )
                    )
                elif value == "dml":
                    choices.append(DeviceChoice("dml", "dml", "dml"))
                    choices.extend(self.dml)
                else:
                    choices.append(DeviceChoice(value, value, value))
            unique = list({choice.value: choice for choice in choices}.values())
            values = [choice.value for choice in unique]
            options["values"] = values
            options["display_labels"] = {
                **dict(options.get("display_labels") or {}),
                **{
                    choice.value: choice.label
                    for choice in unique
                    if choice.label != choice.value
                },
            }
            default = str(options.get(f"default_{self.vendor}") or options.get("default") or "")
            if default not in values:
                default = values[0] if values else ""
            options["default"] = default
        self._compile_behaviors(result)
        return result

    def _compile_behaviors(self, schema: list[dict[str, Any]]) -> None:
        cuda_by_value: dict[str, dict[str, Any]] = {}
        for index, record in enumerate((self.hardware.get("cuda") or {}).get("devices") or []):
            if not isinstance(record, dict):
                continue
            try:
                ordinal = int(record.get("ordinal", index))
            except (TypeError, ValueError):
                continue
            cuda_by_value[f"cuda:{ordinal}"] = record
        default_record = self.hardware.get("cuda_default_record")
        if isinstance(default_record, dict) and "cuda:0" not in cuda_by_value:
            cuda_by_value["cuda:0"] = default_record
        for setting in schema:
            key = str(setting.get("key") or "") if isinstance(setting, dict) else ""
            if isinstance(setting, dict) and not isinstance(setting.get("behavior"), dict):
                source = _HALF_PRECISION_SOURCES.get(key)
                if source:
                    setting["behavior"] = device_half_precision_behavior(source)
            behavior = setting.get("behavior") if isinstance(setting, dict) else None
            if not isinstance(behavior, dict) or behavior.get("kind") != "source_allowlist":
                continue
            compiled = dict(behavior)
            supported: list[str] = []
            for value, record in cuda_by_value.items():
                decision = evaluate_rvc_half_precision(
                    vendor="NVIDIA",
                    compute_capability=(record.get("compute_major"), record.get("compute_minor"))
                    if record.get("compute_major") is not None and record.get("compute_minor") is not None
                    else record.get("compute_capability"),
                    gpu_name=str(record.get("name") or ""),
                )
                if decision.allowed:
                    supported.append(value)
            compiled["supported_values"] = supported
            setting["behavior"] = compiled
            if not supported:
                setting["locked"] = True

            source_key = str(compiled.get("source") or "")
            source = next((item for item in schema if str(item.get("key") or "") == source_key), None)
            source_options = source.get("options") if isinstance(source, dict) else None
            selected_default = str((source_options or {}).get("default") or "")
            if selected_default not in supported:
                options = setting.get("options")
                if isinstance(options, dict):
                    options["default"] = str(compiled.get("unsupported_value", "False"))

    def resolve_runtime_device(self, selected: str) -> str:
        value = str(selected or "").strip().lower()
        if value.startswith("dml@"):
            choice = next((item for item in self.dml if item.value == value), None)
            if choice is None:
                raise ValueError(f"DirectML adapter {value} is no longer available")
            return choice.runtime_device
        if re.fullmatch(r"dml:\d+", value):
            if self.hardware and not any(item.value == value for item in self.dml):
                raise ValueError(f"DirectML adapter {value} is no longer available")
        return value


def _device_setting(setting: Any) -> bool:
    return (
        isinstance(setting, dict)
        and setting.get("type") == "combobox"
        and "device" in str(setting.get("key") or "").lower()
    )


def expand_voice_device_schema(
    schema: list[dict[str, Any]], hardware: dict[str, Any] | None
) -> list[dict[str, Any]]:
    return VoiceDeviceCatalog(hardware).expand_schema(schema)


def validate_voice_devices(
    schema: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    for setting in schema:
        if not _device_setting(setting):
            continue
        key = str(setting["key"])
        if key not in values:
            continue
        options = setting.get("options") or {}
        allowed = {str(value) for value in options.get("values") or []}
        if str(values[key]) not in allowed:
            errors[key] = "Устройство недоступно. Выберите его из актуального списка."
    return errors


def migrate_voice_device_values(
    schema: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, Any]:
    result = dict(values or {})
    for setting in schema:
        if not _device_setting(setting):
            continue
        key = str(setting.get("key") or "")
        current = str(result.get(key) or "").strip().lower()
        if current != "cuda":
            continue
        options = setting.get("options") or {}
        allowed = [str(value) for value in options.get("values") or []]
        if current in allowed:
            continue
        exact_cuda = next(
            (value for value in allowed if re.fullmatch(r"cuda:\d+", value)),
            None,
        )
        if exact_cuda:
            result[key] = exact_cuda
    return result
