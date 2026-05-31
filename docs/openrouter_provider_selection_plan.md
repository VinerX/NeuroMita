# OpenRouter Provider Selection Plan

Last reviewed: 2026-05-31

Scope: this plan applies only to the chat/completions path that uses the `openrouter_default` protocol. It must not affect other providers, other OpenAI-compatible presets, or embedding presets.

Relevant OpenRouter docs:
- https://openrouter.ai/docs/guides/routing/provider-selection
- https://openrouter.ai/docs/api/reference/parameters

## Goal

Add first-class OpenRouter provider routing support to NeuroMita so a user can control which upstream providers OpenRouter should prefer or exclude for a given preset.

The end result should let the user configure OpenRouter-only request routing without leaking OpenRouter-specific controls into unrelated providers.

## OpenRouter request surface

OpenRouter accepts a `provider` object in the request body for chat/completions routing. The current docs expose at least these fields:

- `order`: ordered list of provider slugs to prioritize
- `allow_fallbacks`: whether OpenRouter may fall back outside the preferred list
- `require_parameters`: route only to providers that support all requested parameters
- `only`: allowlist of provider slugs
- `ignore`: denylist of provider slugs
- `sort`: provider selection strategy such as `price`, `latency`, or `throughput`
- `max_price`: ceiling for prompt/completion/request/image pricing
- `quantizations`: quantization filters
- `zdr`: require zero data retention endpoints
- `data_collection`: request-level data collection policy

This feature belongs in the JSON payload, not in headers and not in transforms.

## Current architecture

Relevant files:

- `src/handlers/chat_handler.py`
- `src/managers/api_preset_resolver.py`
- `src/handlers/llm_providers/openai_compatible.py`
- `src/handlers/llm_providers/openai_http_base.py`
- `src/ui/settings/api_settings/*`

Current behavior:

1. `ApiPresetResolver` returns protocol metadata, headers, transforms, and generation overrides.
2. `ChatHandler` builds `LLMRequest.extra` from unified generation params.
3. `OpenAICompatibleProvider` / `OpenAIHTTPProviderBase` serialize `model`, `messages`, and mapped generation params.
4. There is no request-body slot for OpenRouter routing configuration.

That means the main missing piece is a preset-level routing config that survives resolution and is injected into payloads only for `openrouter_default`.

## Design constraints

1. OpenRouter logic must be isolated by protocol id.
2. OpenRouter UI must only appear for OpenRouter presets/templates.
3. The stored config should be structured, not a free-form text blob as the final UX.
4. A temporary advanced JSON field is acceptable only as an intermediate debug tool, not as the final user-facing solution.
5. The feature should coexist with existing generation overrides and protocol overrides without overloading either one incorrectly.

## Proposed storage model

Add a dedicated preset field:

- `openrouter_routing: Dict[str, Any]`

Why separate field instead of reusing `protocol_overrides`:

- `protocol_overrides` currently means transforms, capabilities, and extra headers.
- OpenRouter routing is request-body semantics, not protocol metadata.
- Keeping it separate makes validation and UI gating simpler.

Suggested persisted shape:

```json
{
  "openrouter_routing": {
    "enabled": true,
    "order": ["together", "fireworks"],
    "allow_fallbacks": true,
    "require_parameters": false,
    "only": [],
    "ignore": ["azure"],
    "sort": "latency",
    "max_price": {
      "prompt": 1.0,
      "completion": 2.0
    },
    "quantizations": ["fp8"],
    "zdr": false,
    "data_collection": "deny"
  }
}
```

## Resolver changes

### `src/controllers/api_presets_controller.py`

- Extend `UserPreset` with `openrouter_routing`.
- Load/save that field in JSON persistence.
- Include it in `_build_effective_preset_dict()`.

### `src/managers/api_preset_resolver.py`

- Extend `PresetSettings` with `openrouter_routing: Dict[str, Any]`.
- Resolve and carry the field through unchanged.

This keeps request construction deterministic and avoids hidden SettingsManager lookups later in providers.

## Request construction changes

### `src/handlers/chat_handler.py`

When building `LLMRequest.extra`, attach routing only when:

- `preset_settings.protocol_id == "openrouter_default"`
- and the routing config is enabled and non-empty

Suggested runtime shape:

```python
req.extra["openrouter_routing"] = preset_settings.openrouter_routing
```

### `src/handlers/llm_providers/openai_compatible.py`
### `src/handlers/llm_providers/openai_http_base.py`

Inject into the payload only for OpenRouter:

```python
provider_cfg = (req.extra or {}).get("openrouter_routing")
if req.protocol_id == "openrouter_default" and isinstance(provider_cfg, dict):
    payload["provider"] = validated_provider_cfg
```

For the SDK-based provider and the HTTP-based provider, behavior must match exactly.

## Validation layer

Add a small validator/normalizer dedicated to OpenRouter routing.

Suggested file:

- `src/utils/openrouter_routing.py`

Responsibilities:

1. Accept dict input.
2. Drop unknown keys.
3. Normalize string lists:
   - `order`
   - `only`
   - `ignore`
   - `quantizations`
4. Normalize booleans:
   - `allow_fallbacks`
   - `require_parameters`
   - `zdr`
5. Validate enums:
   - `sort` in `price|latency|throughput`
   - `data_collection` in `allow|deny`
6. Normalize `max_price` subfields to floats.
7. Return an empty dict when nothing valid remains.

This avoids pushing raw UI state directly into outbound payloads.

## UI plan

UI must exist only inside API settings for OpenRouter presets/templates.

### Placement

Inside `src/ui/settings/api_settings/ui.py`, add a dedicated collapsible section below protocol configuration and generation overrides:

- title: `OpenRouter routing`

Show this section only when the selected effective protocol is `openrouter_default`.

### Controls

Minimum useful controls:

1. `Enable OpenRouter routing` checkbox
2. Preferred providers list
3. `Allow fallbacks` checkbox
4. `Require parameter support` checkbox
5. `Only providers` list
6. `Ignore providers` list
7. `Sort by` combo:
   - Default/empty
   - Price
   - Latency
   - Throughput
8. `Max price` numeric controls:
   - prompt
   - completion
   - request
   - image
9. `Quantizations` multi-select or tag list
10. `ZDR only` checkbox
11. `Data collection` combo:
   - Default
   - Allow
   - Deny

### Provider slug discovery

There are two viable levels:

#### Phase 1

Simple text/tag entry for provider slugs.

Pros:
- fast to ship
- no new OpenRouter endpoint dependency

Cons:
- user must know or copy slugs manually

#### Phase 2

Provider picker sourced from OpenRouter model/provider metadata.

Pros:
- better UX
- less user error

Cons:
- more moving pieces

Recommendation: ship phase 1 first, but structure the UI so the list widget can later be backed by fetched suggestions.

## OpenRouter-only gating

This feature must be invisible or inactive when the preset is not OpenRouter.

Required guardrails:

1. UI section hidden unless effective protocol is `openrouter_default`
2. Resolver may store the field on any custom preset, but request injection must hard-gate on `openrouter_default`
3. Non-OpenRouter providers must never see `payload["provider"]`

## Debug / observability

To make this support maintainable:

1. Save the final `provider` object into `last_request_context.json`
2. Show it in the request context viewer
3. If possible, surface the selected upstream provider from OpenRouter response metadata later

This matters because routing bugs are hard to reason about if the final payload is invisible.

## Rollout plan

### Commit 1

Storage and resolver:

- add `openrouter_routing` to preset data classes
- persist it through load/save/export/import
- extend `PresetSettings`

### Commit 2

Payload plumbing:

- attach OpenRouter routing to `LLMRequest.extra`
- inject validated `provider` object into OpenRouter payloads
- add unit-level validation helper

### Commit 3

UI:

- add OpenRouter-only routing section
- wire load/save/apply/cancel state
- hide section for non-OpenRouter presets

### Commit 4

Debug polish:

- save routing config into request context snapshot
- show it in the context viewer

## Tests and manual verification

### Functional

1. OpenRouter preset with no routing config sends no `provider` object.
2. OpenRouter preset with `order=["together"]` sends the object unchanged after normalization.
3. Non-OpenRouter preset ignores stored OpenRouter routing config entirely.
4. UI values survive preset save/reload.

### Manual request checks

1. `order + allow_fallbacks=true`
2. `order + allow_fallbacks=false`
3. `only`
4. `ignore`
5. `sort=latency`
6. `max_price`
7. `zdr=true`

### Regression checks

1. Standard OpenRouter requests without routing still work.
2. Other OpenAI-compatible providers are unaffected.
3. Existing protocol overrides/transforms are unaffected.

## Open questions

1. Do we want a hidden advanced JSON editor in addition to structured UI for debugging?
2. Do we want provider slug suggestions from OpenRouter model metadata in v1, or later?
3. Should routing config be available for builtin OpenRouter template usage without saving a custom preset first?

## Recommendation

Implement this as a dedicated OpenRouter feature, not as a generic provider-routing abstraction.

The API surface, semantics, and UI are vendor-specific enough that a generic abstraction would either become leaky immediately or force weaker controls than OpenRouter actually supports.
