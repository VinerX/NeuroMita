from __future__ import annotations

import threading
from core.task_supervisor import task_supervisor
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from main_logger import logger
from managers.api_preset_resolver import PresetSettings
from handlers.llm_providers.base import LLMUsage
from presets.provider_host_metadata import infer_provider_currency


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_openai_compat_pricing_units(pricing: Dict[str, Any], api_url: str) -> Dict[str, Any]:
    if not pricing:
        return {}

    host = urlparse(str(api_url or "")).netloc.lower()
    if "chutes.ai" not in host:
        return pricing

    normalized: Dict[str, Any] = {}
    for key, value in pricing.items():
        if isinstance(value, bool) or value in (None, ""):
            normalized[key] = value
            continue
        try:
            normalized[key] = float(value) / 1_000_000
        except Exception:
            normalized[key] = value
    return normalized


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
    # Successful lookups are cached for an hour; failures (None) only briefly so a
    # transient network blip does not disable cost estimation for the whole hour.
    _NEGATIVE_TTL_SECONDS = 30

    def __init__(self):
        self._cache: Dict[tuple[str, str], tuple[float, Optional[ModelPricingInfo]]] = {}
        self._lock = threading.Lock()
        self._inflight: set[tuple[str, str]] = set()

    def resolve_for_preset(self, preset: PresetSettings) -> Optional[ModelPricingInfo]:
        """Return cached pricing immediately and refresh in the background.

        Never performs network IO on the calling thread, so it is safe to call from
        the token-stats / cost hot paths (which run on the event-bus worker and are
        awaited by the UI with a short timeout). On a cache miss this returns the
        last known value (or None) right away and kicks off an async fetch.
        """
        if not preset or not preset.api_model:
            return None

        protocol_id = str(getattr(preset, "protocol_id", "") or "")
        model = str(getattr(preset, "api_model", "") or "")
        cache_key = (protocol_id, model)
        now = time.time()

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                ts, info = cached
                ttl = self._TTL_SECONDS if info is not None else self._NEGATIVE_TTL_SECONDS
                if (now - ts) < ttl:
                    return info
            stale_info = cached[1] if cached is not None else None
            if cache_key in self._inflight:
                return stale_info
            self._inflight.add(cache_key)

        self._start_background_fetch(cache_key, preset, protocol_id, model)
        return stale_info

    def _start_background_fetch(
        self, cache_key: tuple[str, str], preset: PresetSettings, protocol_id: str, model: str
    ) -> None:
        def _run() -> None:
            info = None
            try:
                if protocol_id == "openrouter_default":
                    info = self._fetch_openrouter_model_info(preset)
                elif protocol_id == "openai_compatible_default":
                    info = self._fetch_openai_compatible_model_info(preset)
            except Exception as e:
                logger.debug(f"[ModelPricingManager] metadata fetch failed for {protocol_id}/{model}: {e}")
            finally:
                with self._lock:
                    self._cache[cache_key] = (time.time(), info)
                    self._inflight.discard(cache_key)

        task_supervisor().start_thread(
            self,
            f"pricing-fetch-{protocol_id}-{model}",
            _run,
            replace=True,
        )

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

        return self._extract_pricing_info_from_models_payload(
            resp.json(),
            wanted_model=str(preset.api_model or ""),
            api_url=str(preset.api_url or ""),
            source="openrouter_models_api",
        )

    def _fetch_openai_compatible_model_info(self, preset: PresetSettings) -> Optional[ModelPricingInfo]:
        models_url = self._build_models_url(preset.api_url)
        if not models_url:
            return None

        headers = dict(getattr(preset, "headers", {}) or {})
        if preset.api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {preset.api_key}"

        resp = requests.get(models_url, headers=headers, timeout=3)
        if resp.status_code != 200:
            logger.debug(f"[ModelPricingManager] generic models HTTP {resp.status_code} for {models_url}")
            return None

        return self._extract_pricing_info_from_models_payload(
            resp.json(),
            wanted_model=str(preset.api_model or ""),
            api_url=str(preset.api_url or ""),
            source="openai_compatible_models_api",
        )

    def _extract_pricing_info_from_models_payload(
        self,
        payload: Any,
        *,
        wanted_model: str,
        api_url: str = "",
        source: str,
    ) -> Optional[ModelPricingInfo]:
        models = None
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                models = payload.get("data")
            elif isinstance(payload.get("models"), list):
                models = payload.get("models")
        if not isinstance(models, list):
            return None

        entry = next((m for m in models if isinstance(m, dict) and str(m.get("id") or "") == wanted_model), None)
        if not isinstance(entry, dict):
            return None

        top_provider = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        if not pricing:
            pricing = self._build_flat_pricing(entry, top_provider)
        pricing = _normalize_openai_compat_pricing_units(pricing, api_url)

        return ModelPricingInfo(
            model=wanted_model,
            currency=self._resolve_currency(entry, api_url),
            context_length=int(entry.get("context_length")) if entry.get("context_length") not in (None, "") else None,
            max_completion_tokens=int(top_provider.get("max_completion_tokens")) if top_provider.get("max_completion_tokens") not in (None, "") else None,
            prompt_cost_per_token=_to_float(pricing.get("prompt")),
            completion_cost_per_token=_to_float(pricing.get("completion")),
            request_cost=_to_float(pricing.get("request")),
            internal_reasoning_cost_per_token=_to_float(pricing.get("internal_reasoning")),
            cache_read_cost_per_token=_to_float(pricing.get("input_cache_read")),
            cache_write_cost_per_token=_to_float(pricing.get("input_cache_write")),
            source=source,
        )

    @staticmethod
    def _resolve_currency(entry: dict, api_url: str) -> str:
        return infer_provider_currency(api_url, str(entry.get("currency") or "")) or "USD"

    @staticmethod
    def _build_flat_pricing(entry: dict, top_provider: dict) -> Dict[str, Any]:
        alias_map = {
            "prompt": ("prompt", "input", "input_price", "input_cost", "prompt_price", "prompt_cost", "input_token_price"),
            "completion": ("completion", "output", "output_price", "output_cost", "completion_price", "completion_cost", "output_token_price"),
            "request": ("request", "request_price", "request_cost"),
            "internal_reasoning": ("internal_reasoning", "reasoning", "reasoning_price", "reasoning_cost"),
            "input_cache_read": ("input_cache_read", "cache_read", "cache_read_price", "cache_read_cost", "cache_read_token_price"),
            "input_cache_write": ("input_cache_write", "cache_write", "cache_write_price", "cache_write_cost", "cache_write_token_price"),
        }
        extracted: Dict[str, Any] = {}
        for target_key, aliases in alias_map.items():
            for source in (entry, top_provider):
                if not isinstance(source, dict):
                    continue
                for alias in aliases:
                    if alias in source and source.get(alias) not in (None, ""):
                        extracted[target_key] = source.get(alias)
                        break
                if target_key in extracted:
                    break
        return extracted

    def _build_openrouter_models_url(self, api_url: str) -> Optional[str]:
        return self._build_models_url(api_url)

    def _build_models_url(self, api_url: str) -> Optional[str]:
        try:
            parsed = urlparse(str(api_url or ""))
            if not parsed.scheme or not parsed.netloc:
                return None
            path = str(parsed.path or "")
            if "/v1/" in path:
                prefix = path.split("/v1/", 1)[0]
                return f"{parsed.scheme}://{parsed.netloc}{prefix}/v1/models"
            return f"{parsed.scheme}://{parsed.netloc}/v1/models"
        except Exception:
            return None
