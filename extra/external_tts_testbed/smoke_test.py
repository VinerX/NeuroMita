from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path


def call(base_url: str, path: str, api_key: str, *, payload: dict | None = None,
         timeout: float = 30.0) -> tuple[int, bytes, float]:
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if path.endswith("/synthesize") and response.status == 200:
                if response.headers.get_content_type() not in {"audio/wav", "audio/x-wav"}:
                    raise AssertionError("synthesis response Content-Type must be audio/wav")
            return response.status, response.read(), time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.perf_counter() - started


def synthesize(base_url: str, api_key: str, text: str, *, timeout: float = 30.0) -> tuple[bytes, float]:
    status, body, elapsed = call(
        base_url,
        "/v1/synthesize",
        api_key,
        payload={
            "request_id": str(uuid.uuid4()),
            "text": text,
            "character_id": "test-mita",
            "voice_id": "test-voice",
        },
        timeout=timeout,
    )
    if status != 200:
        raise AssertionError(f"synthesize expected HTTP 200, got {status}: {body[:200]!r}")
    return body, elapsed


def wait_for_adapter(base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, body, _elapsed = call(base_url, "/v1/health", api_key, timeout=2.0)
            if status == 200 and json.loads(body).get("api_version") == 1:
                return
            if status in (401, 403):
                raise PermissionError("adapter rejected the configured API key")
            raise RuntimeError(f"health returned HTTP {status}: {body[:160]!r}")
        except PermissionError:
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"adapter did not become ready within {timeout:g}s: {last_error}")


def verify_wav(audio: bytes) -> dict:
    import io

    with wave.open(io.BytesIO(audio), "rb") as wav:
        if (
            wav.getcomptype() != "NONE"
            or wav.getnchannels() not in (1, 2)
            or wav.getsampwidth() not in (1, 2, 3, 4)
        ):
            raise AssertionError("response is not supported PCM WAV")
        if not 16000 <= wav.getframerate() <= 48000 or wav.getnframes() <= 0:
            raise AssertionError("response WAV has invalid sample rate or no audio")
        return {
            "channels": wav.getnchannels(),
            "sample_rate": wav.getframerate(),
            "sample_width_bytes": wav.getsampwidth(),
            "duration_seconds": round(wav.getnframes() / wav.getframerate(), 3),
        }


def run(base_url: str, api_key: str, artifact_dir: Path) -> dict:
    wait_for_adapter(base_url, api_key)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"base_url": base_url, "checks": {}, "started_at": time.time()}

    status, body, elapsed = call(base_url, "/v1/health", api_key)
    if status != 200 or json.loads(body).get("api_version") != 1:
        raise AssertionError(f"health check failed: HTTP {status}, {body[:200]!r}")
    report["checks"]["health"] = {"status": "passed", "seconds": round(elapsed, 3)}

    status, _body, elapsed = call(base_url, "/v1/health", "intentionally-wrong-key")
    if status not in (401, 403):
        raise AssertionError(f"bad API key should be rejected, got HTTP {status}")
    report["checks"]["auth_rejection"] = {"status": "passed", "http": status, "seconds": round(elapsed, 3)}

    audio, elapsed = synthesize(base_url, api_key, "External TTS testbed normal response")
    wav_info = verify_wav(audio)
    output_path = artifact_dir / "latest.wav"
    output_path.write_bytes(audio)
    report["checks"]["two_stage_synthesis"] = {
        "status": "passed", "seconds": round(elapsed, 3), "wav_bytes": len(audio), **wav_info,
    }
    report["output_wav"] = str(output_path)

    _audio, elapsed = synthesize(base_url, api_key, "[[mock:delay=1]] delayed response")
    if elapsed < 0.9:
        raise AssertionError(f"configured mock delay was not observed: {elapsed:.3f}s")
    report["checks"]["delayed_response"] = {"status": "passed", "seconds": round(elapsed, 3)}

    for case, text in (
        ("upstream_http_error", "[[mock:status=503]] expected failure"),
        ("invalid_upstream_wav", "[[mock:corrupt]] expected failure"),
        ("upstream_disconnect", "[[mock:drop]] expected failure"),
    ):
        status, _body, elapsed = call(
            base_url,
            "/v1/synthesize",
            api_key,
            payload={"request_id": str(uuid.uuid4()), "text": text},
        )
        if status != 502:
            raise AssertionError(f"{case} should map to HTTP 502, got {status}")
        report["checks"][case] = {"status": "passed", "http": status, "seconds": round(elapsed, 3)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(synthesize, base_url, api_key, f"parallel request {index}")
            for index in range(4)
        ]
        results = [future.result() for future in futures]
    for audio, _elapsed in results:
        verify_wav(audio)
    report["checks"]["concurrent_synthesis"] = {"status": "passed", "requests": len(results)}
    report["finished_at"] = time.time()
    report["total_seconds"] = round(report["finished_at"] - report["started_at"], 3)
    report_path = artifact_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nPASS: report={report_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise the External TTS adapter testbed")
    parser.add_argument("--base-url", default=os.environ.get("EXTERNAL_TTS_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--api-key", default=os.environ.get("NEUROMITA_API_KEY", ""))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    if not args.api_key:
        parser.error("set --api-key or NEUROMITA_API_KEY")
    try:
        run(args.base_url, args.api_key, args.artifact_dir)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
