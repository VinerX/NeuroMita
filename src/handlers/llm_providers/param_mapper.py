# src/handlers/llm_providers/param_mapper.py
from __future__ import annotations

from typing import Any, Dict


def _strip_nuls_in_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj.replace("'\x00", "").replace("\x00", "")
    if isinstance(obj, list):
        return [_strip_nuls_in_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_nuls_in_strings(v) for k, v in obj.items()}
    return obj


def filter_jsonable_params(params: Dict[str, Any]) -> Dict[str, Any]:
    allowed = (str, int, float, bool, list, dict, type(None))
    return {k: v for k, v in (params or {}).items() if isinstance(v, allowed)}


def build_unified_generation_params(
    *,
    settings: Any,
    temperature: float | None,
    max_response_tokens: int | None,
    presence_penalty: float | None,
    frequency_penalty: float | None,
    log_probability: float | None,
    top_k: int | None,
    top_p: float | None,
    thinking_budget: float | None,
    enable_thinking: bool | None = None,
) -> Dict[str, Any]:
    """
    Canonical/unified параметры. Никакого провайдер-специфичного маппинга здесь нет.
    """
    params: Dict[str, Any] = {}

    if temperature is not None:
        params["temperature"] = float(temperature)

    if bool(settings.get("USE_MODEL_MAX_RESPONSE_TOKENS")) and max_response_tokens is not None:
        params["max_tokens"] = int(max_response_tokens)

    if bool(settings.get("USE_MODEL_PRESENCE_PENALTY")) and presence_penalty is not None:
        params["presence_penalty"] = float(presence_penalty)

    if bool(settings.get("USE_MODEL_FREQUENCY_PENALTY")) and frequency_penalty is not None:
        params["frequency_penalty"] = float(frequency_penalty)

    # Canonical ключ (как OpenAI-style), провайдер сам решит, поддерживает ли.
    if bool(settings.get("USE_MODEL_LOG_PROBABILITY")) and log_probability is not None:
        params["logprobs"] = log_probability

    if bool(settings.get("USE_MODEL_TOP_K")) and top_k is not None and int(top_k) > 0:
        params["top_k"] = int(top_k)

    if bool(settings.get("USE_MODEL_TOP_P")) and top_p is not None:
        params["top_p"] = float(top_p)

    # Canonical ключ
    if bool(settings.get("USE_MODEL_THINKING_BUDGET")) and thinking_budget is not None:
        params["thinking_budget"] = float(thinking_budget)

    if enable_thinking is not None:
        params["enable_thinking"] = enable_thinking

    params = filter_jsonable_params(params)
    params = _strip_nuls_in_strings(params)
    return params