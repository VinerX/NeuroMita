from __future__ import annotations

from typing import Any, Dict


def _strip_nuls_in_strings(obj: Any) -> Any:
    """
    Убираем '\x00' из строк рекурсивно (раньше это делалось clear_endline_sim в разных местах).
    """
    if isinstance(obj, str):
        return obj.replace("'\x00", "").replace("\x00", "")
    if isinstance(obj, list):
        return [_strip_nuls_in_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_nuls_in_strings(v) for k, v in obj.items()}
    return obj


def filter_jsonable_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Оставляем только значения, которые нормально уходят в json/SDK.
    """
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
    Унифицированные параметры (canonical), НЕ зависящие от провайдера.
    Провайдеры сами маппят на свои названия/структуры.
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
    """
    Перевод canonical params -> Gemini generationConfig.

    Gemini ожидает:
      maxOutputTokens, presencePenalty, frequencyPenalty, topP, topK, temperature, ...
    """
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

    # logprobs/thinking_budget — прямого аналога в текущем Gemini payload тут не добавляем

    # Поведение как было в ChatModel.remove_unsupported_params()
    if model in ("gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17"):
        cfg.pop("presencePenalty", None)

    cfg = filter_jsonable_params(cfg)
    cfg = _strip_nuls_in_strings(cfg)
    return cfg