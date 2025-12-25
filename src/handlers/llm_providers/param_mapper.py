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
) -> Dict[str, Any]:
    """
    Canonical/unified параметры. Провайдеры сами решают, что реально поддерживают.
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

    if bool(settings.get("USE_MODEL_LOG_PROBABILITY")) and log_probability is not None:
        params["logprobs"] = log_probability

    if bool(settings.get("USE_MODEL_TOP_K")) and top_k is not None and int(top_k) > 0:
        params["top_k"] = int(top_k)

    if bool(settings.get("USE_MODEL_TOP_P")) and top_p is not None:
        params["top_p"] = float(top_p)

    if bool(settings.get("USE_MODEL_THINKING_BUDGET")) and thinking_budget is not None:
        params["thinking_budget"] = float(thinking_budget)

    params = filter_jsonable_params(params)
    params = _strip_nuls_in_strings(params)
    return params


def map_unified_params_to_gemini_generation_config(unified: Dict[str, Any], *, model: str) -> Dict[str, Any]:
    u = unified or {}
    cfg: Dict[str, Any] = {}

    if "temperature" in u:
        cfg["temperature"] = u["temperature"]
    if "max_tokens" in u:
        cfg["maxOutputTokens"] = u["max_tokens"]
    if "presence_penalty" in u:
        cfg["presencePenalty"] = u["presence_penalty"]
    if "frequency_penalty" in u:
        cfg["frequencyPenalty"] = u["frequency_penalty"]
    if "top_p" in u:
        cfg["topP"] = u["top_p"]
    if "top_k" in u:
        cfg["topK"] = u["top_k"]

    if model in ("gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17"):
        cfg.pop("presencePenalty", None)

    cfg = filter_jsonable_params(cfg)
    cfg = _strip_nuls_in_strings(cfg)
    return cfg


def map_unified_params_to_openai_kwargs(unified: Dict[str, Any], *, model: str) -> Dict[str, Any]:
    """
    Canonical -> kwargs для OpenAI SDK / OpenAI-compatible API.

    Важно: НЕ прокидываем то, что OpenAI не принимает (например top_k, thinking_budget),
    чтобы не ловить 400/validation errors.

    Исключение: deepseek-* часто принимает top_k в openai-совместимых прокси — оставляем
    только для моделей с 'deepseek' в имени.
    """
    u = unified or {}
    m = (model or "").lower()

    out: Dict[str, Any] = {}

    for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
        if k in u:
            out[k] = u[k]

    # top_k — только для deepseek-подобных openai-proxy
    if "top_k" in u and "deepseek" in m:
        out["top_k"] = u["top_k"]

    # logprobs: OpenAI ожидает bool, а раньше у вас там мог быть float.
    if "logprobs" in u:
        lp = u["logprobs"]
        if isinstance(lp, bool):
            out["logprobs"] = lp
        else:
            out["logprobs"] = bool(lp)

    # thinking_budget — не отправляем в OpenAI-compatible
    out = filter_jsonable_params(out)
    out = _strip_nuls_in_strings(out)
    return out