from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


_TYPE_MAP: dict[str, type] = {
    "float": float,
    "double": float,
    "number": float,
    "int": int,
    "integer": int,
    "bool": bool,
    "boolean": bool,
    "str": str,
    "string": str,
}


def _infer_default(py_t: type) -> Any:
    if py_t is float:
        return 0.0
    if py_t is int:
        return 0
    if py_t is bool:
        return False
    return ""


class CustomParamSpec(BaseModel):
    name: str = Field(...)
    type: str = Field(default="string")
    description: str = Field(default="")

    min: Optional[float] = Field(default=None)
    max: Optional[float] = Field(default=None)

    required: bool = Field(default=True)
    nullable: bool = Field(default=False)

    default: Any = Field(default=None)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = str(v or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
            raise ValueError("custom param name must be a valid identifier [A-Za-z_][A-Za-z0-9_]*")
        return s

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        s = str(v or "string").strip().lower()
        if s not in _TYPE_MAP:
            raise ValueError(f"unsupported custom param type: {s!r}")
        return s

    @model_validator(mode="after")
    def _validate_minmax_and_default(self) -> "CustomParamSpec":
        py_t = _TYPE_MAP.get(self.type, str)

        if self.min is not None and self.max is not None and float(self.max) < float(self.min):
            raise ValueError(f"custom param {self.name}: max < min")

        if self.default is None:
            self.default = _infer_default(py_t)

        if self.default is not None and self.default is not ...:
            try:
                if py_t is bool:
                    if isinstance(self.default, str):
                        dl = self.default.strip().lower()
                        if dl in ("true", "1", "yes", "y", "on"):
                            self.default = True
                        elif dl in ("false", "0", "no", "n", "off"):
                            self.default = False
                    else:
                        self.default = bool(self.default)
                elif py_t is int:
                    self.default = int(self.default)
                elif py_t is float:
                    self.default = float(self.default)
                elif py_t is str:
                    self.default = str(self.default)
            except Exception as e:
                raise ValueError(f"custom param {self.name}: default type mismatch: {e}")

        return self


@dataclass
class CharacterConfigData:
    variables: Dict[str, Any]
    custom_params: List[Dict[str, Any]]


class CharacterConfigManager:
    def __init__(self, *, character_id: str, base_data_path: str, logger):
        self.character_id = str(character_id or "").strip()
        self.base_data_path = str(base_data_path or "").strip()
        self.logger = logger

    def config_path(self) -> str:
        return os.path.join(self.base_data_path, "config.json")

    def load_or_create(self) -> CharacterConfigData:
        path = self.config_path()

        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {
                "attitude_min": 0.0,
                "attitude_max": 100.0,
                "boredom_min": 0.0,
                "boredom_max": 100.0,
                "stress_min": 0.0,
                "stress_max": 100.0,
                "custom_params": [],
            }
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=4, ensure_ascii=False)
            except Exception as e:
                self.logger.error(f"[{self.character_id}] Failed to create config.json: {e}", exc_info=True)

        return self.load()

    def load(self) -> CharacterConfigData:
        path = self.config_path()
        raw: Dict[str, Any] = {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except FileNotFoundError:
            return CharacterConfigData(variables={}, custom_params=[])
        except Exception as e:
            self.logger.error(f"[{self.character_id}] Failed to read config.json: {e}", exc_info=True)
            return CharacterConfigData(variables={}, custom_params=[])

        custom_params_raw = raw.get("custom_params", []) or []
        custom_params: List[Dict[str, Any]] = []
        if isinstance(custom_params_raw, list):
            for item in custom_params_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    spec = CustomParamSpec.model_validate(item)
                    custom_params.append(spec.model_dump())
                except Exception as e:
                    self.logger.error(f"[{self.character_id}] Invalid custom_param ignored: {e}")

        self._validate_bounds(raw)

        variables = dict(raw)
        variables.pop("custom_params", None)

        return CharacterConfigData(variables=variables, custom_params=custom_params)

    def _validate_bounds(self, cfg: Dict[str, Any]) -> None:
        def _pair(min_key: str, max_key: str, label: str) -> None:
            vmin = cfg.get(min_key)
            vmax = cfg.get(max_key)
            try:
                if vmin is None or vmax is None:
                    return
                vmin_f = float(vmin)
                vmax_f = float(vmax)
                if vmax_f < vmin_f:
                    self.logger.error(f"[{self.character_id}] Config error: {label} max ({vmax_f}) < min ({vmin_f}).")
            except Exception:
                return

        _pair("attitude_min", "attitude_max", "attitude")
        _pair("boredom_min", "boredom_max", "boredom")
        _pair("stress_min", "stress_max", "stress")