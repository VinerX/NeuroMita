# Generic External TTS adapter

This service presents NeuroMita External TTS API v1 and proxies requests through configured HTTP stages. It keeps F5-TTS/RVC dependencies on the Linux host; the adapter itself needs only Python and aiohttp.

1. Copy `adapter.example.json` to `adapter.json`.
2. Edit each stage to match the actual HTTP method, request encoding, payload fields, response format, and container URL.
3. Set `NEUROMITA_API_KEY` in the shell or an untracked `.env` file to a long random secret. The adapter refuses to start without it.
4. Run `docker compose up --build -d`.
5. Configure NeuroMita with the adapter base URL and the same API key.

The example's F5/RVC endpoints and payloads are placeholders. Confirm them against the running containers' API docs. The adapter allows JSON or form upstream bodies; each stage's response must be WAV or JSON containing a base64 WAV field. Later-stage templates can use `{audio_base64}` to receive the previous stage's WAV. Compose binds the port to loopback, so expose it through an explicitly configured VPN or TLS reverse proxy if remote access is needed.

Do not publish port 8080 directly to the internet. Use a trusted private network or a TLS reverse proxy.
