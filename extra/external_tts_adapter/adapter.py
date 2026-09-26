from __future__ import annotations

import base64
import json
import os
import uuid

import aiohttp
from aiohttp import web


def load_config() -> dict:
    with open(os.environ.get("ADAPTER_CONFIG", "/config/adapter.json"), encoding="utf-8") as stream:
        return json.load(stream)


def require_api_key() -> str:
    key = str(os.environ.get("NEUROMITA_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("NEUROMITA_API_KEY must be set before the adapter starts")
    return key


def auth(request: web.Request) -> None:
    expected = require_api_key()
    if request.headers.get("Authorization") != f"Bearer {expected}":
        raise web.HTTPUnauthorized()


def make_payload(template: dict, *, text: str, character_id: str | None, voice_id: str | None,
                 request_id: str, audio: bytes | None = None) -> dict:
    values = {
        "text": text,
        "character_id": character_id or "",
        "voice_id": voice_id or "",
        "request_id": request_id,
        "audio_base64": base64.b64encode(audio).decode("ascii") if audio is not None else "",
    }
    return {key: str(value).format_map(values) for key, value in template.items()}


async def post_stage(session: aiohttp.ClientSession, stage: dict, payload: dict) -> bytes:
    async with session.request(
        stage.get("method", "POST").upper(), stage["url"],
        json=payload if stage.get("encoding", "json") == "json" else None,
        data=payload if stage.get("encoding", "json") == "form" else None,
        headers=stage.get("headers", {}),
    ) as response:
        response.raise_for_status()
        limit = int(stage.get("max_response_bytes", 48 * 1024 * 1024))
        if response.content_length is not None and response.content_length > limit:
            raise web.HTTPBadGateway(text="Upstream response exceeds configured size limit")
        chunks = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            if len(chunks) + len(chunk) > limit:
                raise web.HTTPBadGateway(text="Upstream response exceeds configured size limit")
            chunks.extend(chunk)
        data = bytes(chunks)
        if stage.get("response", "wav") == "json_base64":
            decoded = json.loads(data)
            data = base64.b64decode(decoded[stage.get("audio_field", "audio_base64")], validate=True)
        if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
            raise web.HTTPBadGateway(text="Upstream did not return a WAV container")
        return data


async def health(request: web.Request) -> web.Response:
    auth(request)
    return web.json_response({"status": "ok", "api_version": 1})


async def synthesize(request: web.Request) -> web.Response:
    auth(request)
    try:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise web.HTTPBadRequest(text="Expected a JSON request body") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Expected a JSON object")
        text = str(body.get("text") or "").strip()
        if not text or len(text) > 100_000:
            raise web.HTTPBadRequest(text="text is required and limited to 100000 characters")
        cfg = request.app["config"]
        request_id = str(body.get("request_id") or uuid.uuid4())
        stages = cfg.get("stages", [])
        if not stages:
            raise web.HTTPServiceUnavailable(text="No upstream stages configured")
        timeout = aiohttp.ClientTimeout(total=float(cfg.get("timeout_seconds", 240)))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            audio = None
            for index, stage in enumerate(stages):
                template = stage.get("payload", {"text": "{text}"})
                stage_text = text if index == 0 else ""
                payload = make_payload(template, text=stage_text, character_id=body.get("character_id"),
                                       voice_id=body.get("voice_id"), request_id=request_id, audio=audio)
                audio = await post_stage(session, stage, payload)
        return web.Response(body=audio, content_type="audio/wav")
    except web.HTTPException:
        raise
    except (aiohttp.ClientError, TimeoutError, KeyError, ValueError, TypeError) as exc:
        raise web.HTTPBadGateway(text=f"Configured upstream failed: {type(exc).__name__}") from exc


def create_app() -> web.Application:
    require_api_key()
    app = web.Application(client_max_size=1_000_000)
    app["config"] = load_config()
    app.router.add_get("/v1/health", health)
    app.router.add_post("/v1/synthesize", synthesize)
    return app


if __name__ == "__main__":
    require_api_key()
    web.run_app(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
