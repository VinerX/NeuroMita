# External TTS testbed

This local-only testbed runs the real NeuroMita adapter against two lightweight HTTP mocks: an F5-like stage that produces a synthetic 440 Hz PCM WAV and an RVC-like stage that accepts and returns that WAV. It does not install TTS models, CUDA, or GPU dependencies.

## Requirements

- Ubuntu in WSL or another Linux environment. WSL2 is needed for the containerized setup; WSL1 can use the native runner below.
- Docker Engine and the Docker Compose plugin for the containerized setup. Docker Desktop with WSL integration also works.
- Python 3.10+ on the machine running the smoke test; the runner uses only the standard library.
- For the native runner without Docker, install `python3-aiohttp` in the Linux distribution.

The adapter is published only on `127.0.0.1:8080`. Mock F5/RVC ports are internal to the Compose network.

## Start

From this directory in WSL:

```bash
cp .env.example .env
# Edit .env and replace the local example key with any private test key.
docker compose -f compose.yaml up --build -d
```

From Windows PowerShell, you can invoke the smoke test through WSL after substituting your Windows repository path:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/<path-to-repo>/extra/external_tts_testbed -- python3 smoke_test.py --api-key <the-key-from-.env>
```

If WSL2 virtualization is unavailable, or you do not want Docker, run the same real adapter and mock stages directly as local Linux processes:

```bash
sudo apt-get update
sudo apt-get install -y python3-aiohttp
export NEUROMITA_API_KEY='your-local-test-key'
bash run_native.sh
```

The native runner binds all three services to loopback, stops them on exit, and keeps its WAV, JSON report, and logs under `artifacts/`.

Or run `python3 smoke_test.py --api-key <the-key-from-.env>` inside WSL. The smoke test waits for readiness and checks:

- API v1 health and rejection of a wrong bearer key;
- a full adapter → mock F5 → mock RVC → adapter PCM WAV round trip;
- a one-second synthetic delay;
- an upstream HTTP error, malformed WAV, and dropped upstream connection mapping to HTTP 502;
- four concurrent syntheses.

It writes `artifacts/latest.wav` and `artifacts/report.json`. Reports contain timings and WAV metadata, never the API key.

## Connect NeuroMita manually

In Voiceover settings choose **External** and enter:

- Server URL: `http://localhost:8080`
- API key: the same value as `NEUROMITA_API_KEY` in `.env`
- Health path: `/v1/health`
- Synthesize path: `/v1/synthesize`
- Voice profile: `test-voice`

Press **Check connection**, then trigger a voice response. The generated audio is a tone; successful task delivery through Unity can be checked with the normal in-game flow.

For the Local → External → Local regression, load a Local voice first, switch to External, trigger a line and confirm Unity plays the tone, then switch back to Local and immediately trigger another line. The first Local request should initialize correctly after the pending unload completes.

## Scenario controls

Include one of these markers in the requested text. The F5 mock removes the marker before recording the text length:

| Marker | Mock behavior |
| --- | --- |
| `[[mock:delay=1]]` | Wait for the requested number of seconds (0–30). |
| `[[mock:duration=2]]` | Generate a WAV of the requested duration (0.1–20 seconds). |
| `[[mock:status=503]]` | Return the selected upstream HTTP error (400–599). |
| `[[mock:corrupt]]` | Return a non-WAV body; adapter should respond 502. |
| `[[mock:drop]]` | Close the upstream connection; adapter should respond 502. |

The smoke runner exercises the success and representative failure paths automatically. To test the adapter timeout manually, use a delay longer than `timeout_seconds` in `adapter.test.json`.

## Logs and stop

```bash
docker compose -f compose.yaml logs --tail=100
docker compose -f compose.yaml down
```

This testbed validates the HTTP contract and NeuroMita adapter behavior. It does not validate actual F5/RVC APIs, CUDA, GPU memory, model quality, or real inference latency.
