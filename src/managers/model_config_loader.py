# src/managers/model_config_loader.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from main_logger import logger


def _to_int(v: Any, default: int) -> int:
    try:
        if v == "" or v is None:
            return int(default)
        return int(v)
    except Exception:
        return int(default)


def _to_float(v: Any, default: float) -> float:
    try:
        if v == "" or v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _to_bool(v: Any, default: bool) -> bool:
    try:
        return bool(v)
    except Exception:
        return bool(default)


@dataclass
class ModelRuntimeConfig:
    # generation params
    max_response_tokens: int = 3200
    temperature: float = 0.5
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    top_k: int = 0
    top_p: float = 1.0
    thinking_budget: float = 0.0
    log_probability: float = 0.0
    enable_thinking: bool | None = None  # None = не передавать параметр
    gemini_thinking_budget: int | None = None  # -1=dynamic, 0=off, >0=token limit

    # costs/limits
    token_cost_input: float = 0.0432
    token_cost_output: float = 0.1728
    max_model_tokens: int = 128000

    # context/history
    memory_limit: int = 40

    # retry policy
    max_request_attempts: int = 5
    request_delay: float = 0.20

    # image reduction (используется Prompt/History controller’ами)
    image_quality_reduction_enabled: bool = False
    image_quality_reduction_start_index: int = 25
    image_quality_reduction_use_percentage: bool = False
    image_quality_reduction_min_quality: int = 30
    image_quality_reduction_decrease_rate: int = 5

    # tracks which params were forced by a preset override (bypasses USE_MODEL_* global flags)
    preset_forced_params: frozenset = frozenset()

    def apply_setting(self, key: str, value: Any) -> None:
        """
        Централизованно обновляем runtime-конфиг при Events.Core.SETTING_CHANGED.
        Это уменьшает ModelController и не раздувает ChatModel.
        """
        try:
            if key == "MODEL_MAX_RESPONSE_TOKENS":
                self.max_response_tokens = _to_int(value, self.max_response_tokens)
            elif key == "MODEL_TEMPERATURE":
                self.temperature = _to_float(value, self.temperature)
            elif key == "MODEL_PRESENCE_PENALTY":
                self.presence_penalty = _to_float(value, self.presence_penalty)
            elif key == "MODEL_FREQUENCY_PENALTY":
                self.frequency_penalty = _to_float(value, self.frequency_penalty)
            elif key == "MODEL_LOG_PROBABILITY":
                self.log_probability = _to_float(value, self.log_probability)
            elif key == "MODEL_TOP_K":
                self.top_k = _to_int(value, self.top_k)
            elif key == "MODEL_TOP_P":
                self.top_p = _to_float(value, self.top_p)
            elif key == "MODEL_THOUGHT_PROCESS" or key == "MODEL_THINKING_BUDGET":
                self.thinking_budget = _to_float(value, self.thinking_budget)
            elif key == "ENABLE_THINKING":
                self.enable_thinking = _to_bool(value, True) if value != "" and value is not None else None
            elif key == "GEMINI_THINKING_BUDGET":
                self.gemini_thinking_budget = _to_int(value, 8192) if value != "" and value is not None else None

            elif key == "MODEL_MESSAGE_LIMIT":
                self.memory_limit = _to_int(value, self.memory_limit)
            elif key == "MODEL_MESSAGE_ATTEMPTS_COUNT":
                self.max_request_attempts = _to_int(value, self.max_request_attempts)
            elif key == "MODEL_MESSAGE_ATTEMPTS_TIME":
                self.request_delay = _to_float(value, self.request_delay)

            elif key == "IMAGE_QUALITY_REDUCTION_ENABLED":
                self.image_quality_reduction_enabled = _to_bool(value, self.image_quality_reduction_enabled)
            elif key == "IMAGE_QUALITY_REDUCTION_START_INDEX":
                self.image_quality_reduction_start_index = _to_int(value, self.image_quality_reduction_start_index)
            elif key == "IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE":
                self.image_quality_reduction_use_percentage = _to_bool(value, self.image_quality_reduction_use_percentage)
            elif key == "IMAGE_QUALITY_REDUCTION_MIN_QUALITY":
                self.image_quality_reduction_min_quality = _to_int(value, self.image_quality_reduction_min_quality)
            elif key == "IMAGE_QUALITY_REDUCTION_DECREASE_RATE":
                self.image_quality_reduction_decrease_rate = _to_int(value, self.image_quality_reduction_decrease_rate)

            elif key == "TOKEN_COST_INPUT":
                self.token_cost_input = _to_float(value, self.token_cost_input)
            elif key == "TOKEN_COST_OUTPUT":
                self.token_cost_output = _to_float(value, self.token_cost_output)
            elif key == "MAX_MODEL_TOKENS":
                self.max_model_tokens = _to_int(value, self.max_model_tokens)

        except Exception as e:
            logger.warning(f"[ModelRuntimeConfig] Failed to apply setting {key}={value}: {e}")


class ModelConfigLoader:
    """
    Грузит runtime-конфиг из Settings.

    ВАЖНО: тут же закладываем “крючок” для будущих overrides параметров из пресетов.
    Сейчас overrides не реализуем (как ты просил), но точка расширения уже есть.
    """

    def __init__(self, settings: Any):
        self.settings = settings

    def load(self) -> ModelRuntimeConfig:
        s = self.settings
        cfg = ModelRuntimeConfig(
            max_response_tokens=_to_int(s.get("MODEL_MAX_RESPONSE_TOKENS", 3200), 3200),
            temperature=_to_float(s.get("MODEL_TEMPERATURE", 0.5), 0.5),
            presence_penalty=_to_float(s.get("MODEL_PRESENCE_PENALTY", 0.0), 0.0),
            frequency_penalty=_to_float(s.get("MODEL_FREQUENCY_PENALTY", 0.0), 0.0),
            top_k=_to_int(s.get("MODEL_TOP_K", 0), 0),
            top_p=_to_float(s.get("MODEL_TOP_P", 1.0), 1.0),
            thinking_budget=_to_float(s.get("MODEL_THINKING_BUDGET", 0.0), 0.0),
            log_probability=_to_float(s.get("MODEL_LOG_PROBABILITY", 0.0), 0.0),
            enable_thinking=_to_bool(s.get("ENABLE_THINKING"), True) if s.get("ENABLE_THINKING") is not None else None,
            gemini_thinking_budget=_to_int(s.get("GEMINI_THINKING_BUDGET", 8192), 8192) if s.get("GEMINI_THINKING_BUDGET") is not None else None,

            token_cost_input=_to_float(s.get("TOKEN_COST_INPUT", 0.0432), 0.0432),
            token_cost_output=_to_float(s.get("TOKEN_COST_OUTPUT", 0.1728), 0.1728),
            max_model_tokens=_to_int(s.get("MAX_MODEL_TOKENS", 128000), 128000),

            memory_limit=_to_int(s.get("MODEL_MESSAGE_LIMIT", 40), 40),

            max_request_attempts=_to_int(s.get("MODEL_MESSAGE_ATTEMPTS_COUNT", 5), 5),
            request_delay=_to_float(s.get("MODEL_MESSAGE_ATTEMPTS_TIME", 0.20), 0.20),

            image_quality_reduction_enabled=_to_bool(s.get("IMAGE_QUALITY_REDUCTION_ENABLED", False), False),
            image_quality_reduction_start_index=_to_int(s.get("IMAGE_QUALITY_REDUCTION_START_INDEX", 25), 25),
            image_quality_reduction_use_percentage=_to_bool(s.get("IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE", False), False),
            image_quality_reduction_min_quality=_to_int(s.get("IMAGE_QUALITY_REDUCTION_MIN_QUALITY", 30), 30),
            image_quality_reduction_decrease_rate=_to_int(s.get("IMAGE_QUALITY_REDUCTION_DECREASE_RATE", 5), 5),
        )
        return cfg

    def effective_for_preset(self, base: ModelRuntimeConfig, preset_settings: Any, model: str) -> ModelRuntimeConfig:
        """
        Apply per-preset generation parameter overrides on top of the global config.
        Each override entry: {param: {"enabled": bool, "value": Any}}
        """
        import copy
        overrides = getattr(preset_settings, "generation_overrides", None) or {}
        if not overrides:
            return base

        cfg = copy.copy(base)
        forced = set()
        mapping = {
            "temperature":      ("temperature",        _to_float),
            "max_tokens":       ("max_response_tokens", _to_int),
            "top_p":            ("top_p",              _to_float),
            "top_k":            ("top_k",              _to_int),
            "presence_penalty": ("presence_penalty",   _to_float),
            "frequency_penalty":("frequency_penalty",  _to_float),
            "thinking_budget":  ("thinking_budget",    _to_float),
        }
        applied = []
        for key, (attr, cast) in mapping.items():
            spec = overrides.get(key) or {}
            if spec.get("enabled") and "value" in spec:
                try:
                    new_val = cast(spec["value"], getattr(cfg, attr))
                    setattr(cfg, attr, new_val)
                    forced.add(key)
                    applied.append(f"{key}={new_val}")
                except Exception as e:
                    logger.warning(f"[ModelConfigLoader] Failed to apply preset override {key}={spec['value']}: {e}")

        # enable_thinking: boolean or None (None = don't send the param)
        et_spec = overrides.get("enable_thinking") or {}
        if et_spec.get("enabled"):
            val = et_spec.get("value")
            cfg.enable_thinking = _to_bool(val, True) if val is not None else None
            forced.add("enable_thinking")
            applied.append(f"enable_thinking={cfg.enable_thinking}")

        if applied:
            preset_name = getattr(preset_settings, "preset_name", "?")
            logger.info(f"[ModelConfigLoader] Preset '{preset_name}' overrides applied: {', '.join(applied)}")
            logger.info(
                f"[ModelConfigLoader] Effective config — temperature={cfg.temperature}, "
                f"max_response_tokens={cfg.max_response_tokens}, top_p={cfg.top_p}, "
                f"top_k={cfg.top_k}, presence_penalty={cfg.presence_penalty}, "
                f"frequency_penalty={cfg.frequency_penalty}, enable_thinking={cfg.enable_thinking}"
            )

        cfg.preset_forced_params = frozenset(forced)
        return cfg