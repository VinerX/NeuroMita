# External TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an experimental External voiceover method that obtains validated WAV audio from a user-hosted HTTP API and sends it through NeuroMita's existing playback path.

**Architecture:** An isolated `ExternalTTSClient` owns HTTP, configuration validation, bounded WAV download, and health checks. An `ExternalVoiceService` is registered only for the External method. `AudioController` routes the method through common post-processing, and the voiceover settings UI owns its URL, key, voice profile, timeout, and connectivity check.

**Tech Stack:** Python, aiohttp (already in requirements.txt), stdlib `wave`, existing settings registry, feature manager, PyQt6 UI, performance tracing.

**Spec:** `docs/superpowers/specs/2026-09-23-external-tts-design.md`

## Global Constraints

- Keep F5-TTS, RVC, Docker, model files, and model compute on the user's server.
- Use `GET /v1/health` and `POST /v1/synthesize`; send Bearer authentication when configured.
- Accept only HTTP/HTTPS URLs without userinfo, query, or fragment; keep TLS certificate verification enabled.
- Do not automatically retry synthesis or fall back to Local.
- Download no more than 32 MiB of PCM WAV, in chunks, and remove partial files on errors or cancellation.
- Do not log API keys or full private text.
- Preserve Telegram and Local behavior and existing Unity/desktop playback lifecycle.
- Do not add or run tests unless the user asks; perform source review and non-test validation during implementation.

## Review Focus

- API returns HTML/JSON, empty data, malformed WAV, compressed WAV, unsupported channels/sample rate, or more than the configured byte cap: reject and remove the temporary file.
- Network timeout, connection failure, 401/403, and user cancellation: report a useful error, do not retry generation, and clear waiting/task state.
- Settings change while a synthesis is in flight: request continues using the immutable configuration snapshot captured at start.
- Unity is connected but the event has no task UID: retain current desktop routing semantics and do not claim delivery to the game.
- API key contains unusual characters: pass via the HTTP auth header and ensure diagnostics redact it.

---

### Task 1: External TTS transport and WAV validation

**Files:**
- Create: `src/services/external_tts_service.py`

**Interfaces:**
- Produces: `ExternalTTSConfig(base_url, api_key="", voice_id="", connect_timeout=5.0, total_timeout=180.0, output_dir="", max_audio_bytes=32*1024*1024)`.
- Produces: `ExternalTTSClient.health(config) -> dict` and `ExternalTTSClient.synthesize(config, text, *, character_id=None, voice_id=None) -> str` (absolute WAV path).
- Raises typed, user-readable external TTS errors for invalid configuration, connectivity/timeout, authentication/HTTP failure, invalid/oversized audio.

- [ ] Add immutable configuration and typed client errors. Validate scheme, hostname, URL components, port, finite positive timeouts, non-empty text, and configured size cap before network work.
- [ ] Implement `health()` as `GET {base_url}/v1/health` with the captured config, bearer header when present, bounded timeout, status and JSON version validation; do not call synthesize.
- [ ] Implement synthesis JSON contract with unique request ID and nullable `character_id`/`voice_id`; stream the response in bounded chunks to a unique temp file under `output_dir`.
- [ ] Require an audio WAV content type and successful HTTP status. Map 401/403, HTTP failures, timeout and connectivity errors without including secrets in messages.
- [ ] Validate WAV with stdlib `wave`: PCM/uncompressed, 1–2 channels, 16–48 kHz, 16-bit preferred, nonempty frames, and complete readable frame payload. Reject malformed, empty, unexpected, or oversized content.
- [ ] Atomically rename only after validation; `finally` removes partial files after exceptions and cancellation. Return the final absolute path.
- [ ] Review all log/error paths to confirm they omit API key and full input text.

### Task 2: External voice service contract and feature registration

**Files:**
- Modify: `src/services/contracts.py`
- Create: `src/controllers/external_voice_controller.py`
- Modify: `src/controllers/main_controller.py`

**Interfaces:**
- Consumes: `ExternalTTSConfig`, `ExternalTTSClient` from Task 1.
- Produces: `ExternalVoiceService.health(config_snapshot=None)` and `ExternalVoiceService.synthesize(text, *, character_id=None, voice_id=None, config_snapshot=None) -> str`.

- [ ] Add an abstract service contract separate from `LocalVoiceService`; external synthesis must not initialize or query local model state.
- [ ] Implement the controller as a narrow adapter to the HTTP client, deriving an immutable config snapshot from current settings only when no explicit snapshot was supplied.
- [ ] Register an `external_voice` optional feature in `MainController`, enabled only when voiceover is enabled and method is External; declare the provided service contract and add a factory/shutdown hook if required by neighboring features.
- [ ] Confirm feature registration dependencies and settings keys follow the existing Telegram/Local `FeatureSpec` patterns.

### Task 3: External settings and connection check

**Files:**
- Modify: `src/ui/settings/voiceover_settings/ui.py`
- Modify: `src/controllers/gui/voiceover_settings_logic.py`
- Modify: `src/controllers/gui/voiceover_settings_view_model.py`
- Modify: `src/controllers/gui/voiceover_controller.py` (only if existing refresh/visibility owner requires it)
- Modify: `src/services/character_environment_context.py` (keep LLM environment facts accurate for External mode)
- Modify: `src/core/events.py` (only if a dedicated typed GUI event is required)

**Interfaces:**
- Consumes: `ExternalVoiceService` registered in Task 2.
- Produces: persisted settings `EXTERNAL_TTS_BASE_URL`, `EXTERNAL_TTS_API_KEY`, `EXTERNAL_TTS_VOICE_ID`, and `EXTERNAL_TTS_TIMEOUT`.

- [ ] Add `External` to the method options and create a visually consistent External section for URL, masked API key, voice ID, timeout, and Check Connection action.
- [ ] Wire section visibility to the selected method; ensure changing methods refreshes visibility without presenting passive settings as a combobox or modifying Local/TG settings.
- [ ] Implement the connection action through a GUI intent/event and the async service lifecycle; show success/failure on the UI thread without generating speech or logging credentials.
- [ ] Add translated labels and short guidance describing the expected API base URL and the user's responsibility to expose `/v1/health` and `/v1/synthesize`.
- [ ] Inspect settings save/load paths to ensure the password-style input persists according to existing private-setting conventions.
- [ ] Ensure the character environment context describes External voice as server-generated and does not report a stale local model as the active voice.

### Task 4: Audio routing and shared post-processing

**Files:**
- Modify: `src/controllers/audio_controller.py`
- Modify: `src/controllers/main_controller.py` if service construction ordering needs adjustment after Task 2

**Interfaces:**
- Consumes: `ExternalVoiceService.synthesize()` and the existing Local voice service.
- Produces: a shared path-based post-processing method for Local and External synthesis.

- [ ] Add the External branch in `_on_voiceover_requested()` and capture the request's setting snapshot before asynchronous work begins.
- [ ] Extract the common portion of `_await_local_voiceover_and_postprocess()` so both methods pass a local WAV path into one lifecycle implementation.
- [ ] Preserve `tts.ready`, task SUCCESS/FAILED_ON_VOICEOVER, `delivered_to_game = task_uid and GameLinkService.is_connected()`, existing Unity payload, desktop playback volume/deletion rules, UI voicing events, Mita speaking state, and performance trace completion.
- [ ] Keep Telegram's independent send/receive path unchanged.
- [ ] Ensure External errors cannot publish SUCCESS, do not pass a remote URL to Unity, reset `waiting_answer`, hide voicing UI, and finish the trace exactly once.
- [ ] Check that Local/TG settings and startup behavior remain unchanged when External is not selected.

### Task 5: Contract documentation and delivery checks

**Files:**
- Create: `docs/external_tts_api_v1.md`
- Modify: user-facing README/settings help only if project documentation conventions require it.

**Interfaces:**
- Documents: health and synthesize routes, JSON fields, bearer auth, WAV constraints, example request/response, and reverse-proxy HTTPS guidance.

- [ ] Document the API v1 contract independently of F5-TTS/RVC internals, including a minimal server implementation checklist.
- [ ] Re-read every modified source and documentation file for consistency with the design, feature registration, and GUI setting names.
- [ ] Run `git diff --check` and inspect the final diff and repository status; do not stage, commit, or push as part of implementation unless asked.
- [ ] Report source-level validation separately from any live server or UI proof, which requires a configured External API endpoint.
