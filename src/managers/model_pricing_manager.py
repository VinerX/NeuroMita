from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from main_logger import logger
from managers.api_preset_resolver import PresetSettings
from handlers.llm_providers.base import LLMUsage


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


@dataclass(frozen=True)
class ModelPricingInfo:
    model: str
    currency: str = "USD"
    context_length: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    prompt_cost_per_token: Optional[float] = None
    completion_cost_per_token: Optional[float] = None
    request_cost: Optional[float] = None
    internal_reasoning_cost_per_token: Optional[float] = None
    cache_read_cost_per_token: Optional[float] = None
    cache_write_cost_per_token: Optional[float] = None
    source: str = "provider_metadata"

    def estimate_prompt_cost(self, prompt_tokens: int) -> Optional[float]:
        if self.prompt_cost_per_token is None:
            return None
        return float(prompt_tokens or 0) * float(self.prompt_cost_per_token)

    def estimate_usage_cost(self, usage: Optional[LLMUsage]) -> Optional[float]:
        if usage is None:
            return None

        total = 0.0
        has_any = False

        non_cached_prompt_tokens = max(
            0,
            int(usage.prompt_tokens or 0)
            - int(usage.cached_prompt_tokens or 0)
            - int(usage.cache_write_tokens or 0),
        )

        if self.prompt_cost_per_token is not None:
            total += non_cached_prompt_tokens * float(self.prompt_cost_per_token)
            has_any = True

        if self.completion_cost_per_token is not None:
            total += int(usage.completion_tokens or 0) * float(self.completion_cost_per_token)
            has_any = True

        if self.internal_reasoning_cost_per_token is not None and int(usage.reasoning_tokens or 0) > 0:
            total += int(usage.reasoning_tokens or 0) * float(self.internal_reasoning_cost_per_token)
            has_any = True

        if self.cache_read_cost_per_token is not None and int(usage.cached_prompt_tokens or 0) > 0:
            total += int(usage.cached_prompt_tokens or 0) * float(self.cache_read_cost_per_token)
            has_any = True

        if self.cache_write_cost_per_token is not None and int(usage.cache_write_tokens or 0) > 0:
            total += int(usage.cache_write_tokens or 0) * float(self.cache_write_cost_per_token)
            has_any = True

        if self.request_cost is not None:
            total += float(self.request_cost)
            has_any = True

        return total if has_any else None


class ModelPricingManager:
    _TTL_SECONDS = 60 * 60

    def __init__(self):
        self._cache: Dict[tuple[str, str], tuple[float, Optional[ModelPricingInfo]]] = {}

    def resolve_for_preset(self, preset: PresetSettings) -> Optional[ModelPricingInfo]:
        if not preset or not preset.api_model:
            return None

        protocol_id = str(getattr(preset, "protocol_id", "") or "")
        model = str(getattr(preset, "api_model", "") or "")
        cache_key = (protocol_id, model)

        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self._TTL_SECONDS:
            return cached[1]

        info = None
        try:
            if protocol_id == "openrouter_default":
                info = self._fetch_openrouter_model_info(preset)
        except Exception as e:
            logger.debug(f"[ModelPricingManager] metadata fetch failed for {protocol_id}/{model}: {e}")

        self._cache[cache_key] = (time.time(), info)
        return info

    def _fetch_openrouter_model_info(self, preset: PresetSettings) -> Optional[ModelPricingInfo]:
        models_url = self._build_openrouter_models_url(preset.api_url)
        if not models_url:
            return None

        headers = dict(getattr(preset, "headers", {}) or {})
        if preset.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {preset.api_key}"

        resp = requests.get(models_url, headers=headers, timeout=3)
        if resp.status_code != 200:
            logger.debug(f"[ModelPricingManager] OpenRouter models HTTP {resp.status_code}")
            return None

        data = resp.json()
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return None

        wanted = str(preset.api_model or "")
        entry = next((m for m in models if isinstance(m, dict) and str(m.get("id") or "") == wanted), None)
        if not isinstance(entry, dict):
            return None

        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        top_provider = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}

        return ModelPricingInfo(
            model=wanted,
            currency="USD",
            context_length=int(entry.get("context_length")) if entry.get("context_length") not in (None, "") else None,
            max_completion_tokens=int(top_provider.get("max_completion_tokens")) if top_provider.get("max_completion_tokens") not in (None, "") else None,
            prompt_cost_per_token=_to_float(pricing.get("prompt")),
            completion_cost_per_token=_to_float(pricing.get("completion")),
            request_cost=_to_float(pricing.get("request")),
            internal_reasoning_cost_per_token=_to_float(pricing.get("internal_reasoning")),
            cache_read_cost_per_token=_to_float(pricing.get("input_cache_read")),
            cache_write_cost_per_token=_to_float(pricing.get("input_cache_write")),
            source="openrouter_models_api",
        )

    def _build_openrouter_models_url(self, api_url: str) -> Optional[str]:
        try:
            parsed = urlparse(str(api_url or ""))
            if not parsed.scheme or not parsed.netloc:
                return None
            return f"{parsed.scheme}://{parsed.netloc}/api/v1/models"
        except Exception:
            return None
