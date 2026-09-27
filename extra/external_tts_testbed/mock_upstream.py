from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import struct
import time
import wave
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


_CONTROL_RE = re.compile(r"\[\[mock:(delay|duration|status)=([0-9]+(?:\.[0-9]+)?)\]\]")


@dataclass(frozen=True)
class TestControls:
    delay_seconds: float = 0.0
    duration_seconds: float = 1.0
    status_code: int | None = None
    corrupt_wav: bool = False
    drop_connection: bool = False


def parse_test_controls(text: str) -> tuple[str, TestControls]:
    values: dict[str, float] = {}

    def remove_control(match: re.Match[str]) -> str:
        values[match.group(1)] = float(match.group(2))
        return " "

    cleaned = _CONTROL_RE.sub(remove_control, str(text or ""))
    corrupt = "[[mock:corrupt]]" in cleaned
    drop = "[[mock:drop]]" in cleaned
    cleaned = cleaned.replace("[[mock:corrupt]]", " ").replace("[[mock:drop]]", " ")
    status = int(values["status"]) if "status" in values else None
    if status is not None and not 400 <= status <= 599:
        raise ValueError("mock status must be between 400 and 599")
    delay = values.get("delay", 0.0)
    duration = values.get("duration", 1.0)
    if not 0 <= delay <= 30:
        raise ValueError("mock delay must be between 0 and 30 seconds")
    if not 0.1 <= duration <= 20:
        raise ValueError("mock duration must be between 0.1 and 20 seconds")
    controls = TestControls(delay, duration, status, corrupt, drop)
    return " ".join(cleaned.split()), controls


def generate_test_wav(duration_seconds: float = 1.0, sample_rate: int = 24000) -> bytes:
    frames = int(duration_seconds * sample_rate)
    samples = (
        int(5000 * math.sin(2 * math.pi * 440 * frame / sample_rate))
        for frame in range(frames)
    )
    pcm = b"".join(struct.pack("<h", sample) for sample in samples)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


class MockStageHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def log_message(self, _format: str, *_args) -> None:
        return

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 48 * 1024 * 1024:
            raise ValueError("invalid request size")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("expected JSON object")
        return payload

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._respond(404, b"not found", "text/plain")
            return
        self._respond(200, b'{"status":"ok"}', "application/json")

    def do_POST(self) -> None:
        stage = str(getattr(self.server, "stage", ""))
        started = time.perf_counter()
        expected_path = "/synthesize" if stage == "f5" else "/convert"
        if self.path != expected_path:
            self._respond(404, b"not found", "text/plain")
            return
        try:
            payload = self._json_body()
            if stage == "f5":
                text, controls = parse_test_controls(str(payload.get("text", "")))
                if controls.drop_connection:
                    self.close_connection = True
                    self.connection.close()
                    return
                if controls.delay_seconds:
                    time.sleep(controls.delay_seconds)
                if controls.status_code:
                    self._respond(controls.status_code, b"mock upstream error", "text/plain")
                    return
                audio = b"not-a-wav" if controls.corrupt_wav else generate_test_wav(controls.duration_seconds)
                self._respond(200, audio, "audio/wav")
                print(
                    f"stage=f5 result=ok elapsed_ms={int((time.perf_counter() - started) * 1000)} "
                    f"text_chars={len(text)} voice_id={payload.get('voice_id', '')}",
                    flush=True,
                )
                return

            encoded_audio = str(payload.get("audio_base64", ""))
            audio = base64.b64decode(encoded_audio, validate=True)
            with wave.open(io.BytesIO(audio), "rb") as wav:
                wav.getparams()
            result = json.dumps({"audio_base64": base64.b64encode(audio).decode("ascii")}).encode()
            self._respond(200, result, "application/json")
            print(
                f"stage=rvc result=ok elapsed_ms={int((time.perf_counter() - started) * 1000)} "
                f"audio_bytes={len(audio)} voice_id={payload.get('voice_id', '')}",
                flush=True,
            )
        except (ValueError, json.JSONDecodeError, wave.Error) as exc:
            self._respond(400, str(exc).encode("utf-8", errors="replace"), "text/plain")


def run_server(stage: str, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), MockStageHandler)
    server.stage = stage
    print(f"mock stage ready stage={stage} host={host} port={port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("f5", "rvc"), default=os.environ.get("MOCK_STAGE", "f5"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8001")))
    args = parser.parse_args()
    run_server(args.stage, args.host, args.port)
