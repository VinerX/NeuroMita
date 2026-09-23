# NeuroMita External TTS API v1

This contract lets NeuroMita use a user-hosted speech service without knowing whether it runs F5-TTS, RVC, Piper, or another engine. The server owns model paths, Docker containers, GPU scheduling, and any conversion needed to produce the response format below.

## Base URL and authentication

Configure the API base URL in NeuroMita without the endpoint path, for example `https://tts.example.net` or `http://192.168.1.20:8080`. A reverse-proxy path prefix is allowed. When an API key is configured, NeuroMita sends:

```http
Authorization: Bearer <api-key>
```

Use HTTPS when the endpoint is reachable over the public internet. HTTP is suitable only for a trusted LAN or VPN. NeuroMita keeps normal TLS certificate verification enabled.

The API key is stored with the rest of the application settings in `Settings/settings.json`; the UI masks it and the settings update log redacts it, but the file is not encrypted. Restrict access to that file using the operating system account permissions.

## Health check

```http
GET /v1/health
```

Return HTTP 200 and JSON:

```json
{
  "status": "ok",
  "api_version": 1
}
```

The health check verifies connectivity and compatibility. It must not start speech generation.

## Synthesize speech

```http
POST /v1/synthesize
Content-Type: application/json
```

Request:

```json
{
  "request_id": "bd8fd0da-18d5-4b6d-984a-...",
  "text": "Hello from NeuroMita.",
  "character_id": "mita",
  "voice_id": "mita_f5_rvc"
}
```

`request_id` is unique per request. `character_id` and `voice_id` may be `null`. `voice_id` is an application-level profile name that the server maps to its own TTS and voice-conversion configuration; it is not a model file path or container ID.

On success, return HTTP 200 with `Content-Type: audio/wav` (or `audio/x-wav`) and a complete, uncompressed PCM WAV in the response body. NeuroMita accepts one or two channels, 16–48 kHz, and common PCM sample widths from 8 to 32 bits; 16-bit PCM is recommended. Return a non-2xx status for errors and never put an error page or JSON document in a successful audio response.

The server should return the final audio directly in the HTTP response. No WebSocket, polling endpoint, or client-side conversion is part of v1.

## Generic Linux adapter example

`extra/external_tts_adapter` contains a Docker Compose adapter for chaining configurable HTTP stages. It can send JSON or form fields and consume WAV or JSON/base64 WAV responses. Start from `adapter.example.json`, copy it to `adapter.json`, then set the actual F5/RVC URLs, methods, field names, and response modes used by your containers. Values in payload templates support `{text}`, `{voice_id}`, `{character_id}`, `{request_id}`, and `{audio_base64}`.

A character can override the global voice profile by setting `external_voice_id` in that character's `config.json`. If omitted, NeuroMita sends the global `EXTERNAL_TTS_VOICE_ID` value.

The sample field names are illustrative. TTS and RVC containers do not share a standard HTTP contract, so verify each upstream request/response against that container's documentation before deployment. Protect the adapter with a long random `NEUROMITA_API_KEY`; expose it only through a trusted LAN/VPN or TLS reverse proxy.

## Minimal server checklist

- Expose `GET /v1/health` and `POST /v1/synthesize` at the configured base URL.
- Validate bearer authentication when enabled and do not expose private model paths in responses.
- Route the logical voice profile to the server's configured engine or engine chain.
- Keep the request open until synthesis finishes, then return the complete PCM WAV.
- Normalize output to the channel count and sample-rate range above on the server.
- Bound request duration and return clear HTTP error statuses for failures.
