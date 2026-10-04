from __future__ import annotations

import asyncio
import json
import threading
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from core.networking import HttpClientRegistry
from core.remote_voice import RemoteCharacterVoice, RemoteVoiceError
from services.remote_voice_repository import RemoteVoiceRepository
from services.remote_voice_service import DefaultRemoteVoiceService


SECRET = "test-secret-never-log-this"
VOICE_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def service_factory(tmp_path):
    instances = []

    def create(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = DefaultRemoteVoiceService(
            repository=RemoteVoiceRepository(tmp_path / "profiles.json"),
            registry=HttpClientRegistry(), client=client, output_dir=tmp_path / "audio",
        )
        preset = replace(service.configuration().active, api_key=SECRET, voice_id=VOICE_ID)
        service.save_preset(preset)
        instances.append(service)
        return service

    yield create
    for service in instances:
        service.close()


def test_native_contract_and_wav_output(service_factory):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "audio/pcm"}, content=b"\x01\x00\x02\x00")

    service = service_factory(respond)
    assert service.status().configured and not service.status().verified
    path = asyncio.run(service.synthesize("Привет <command>секрет</command> мир!"))
    request = requests[0]
    assert str(request.url) == "https://api.fish.audio/v1/tts"
    assert request.headers["authorization"] == "Bearer " + SECRET
    assert request.headers["model"] == "s1"
    payload = json.loads(request.content)
    assert payload["format"] == "pcm"
    assert payload["reference_id"] == VOICE_ID
    assert payload["prosody"] == {"speed": 1.0, "normalize_loudness": True}
    assert "command" not in payload["text"] and "секрет" not in payload["text"]
    with wave.open(path) as audio:
        assert audio.getframerate() == 44100
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.readframes(2) == b"\x01\x00\x02\x00"
    assert service.status().verified
    service.save_preset(replace(service.configuration().active, speed=1.2))
    assert not service.status().verified


@pytest.mark.parametrize("status", [301, 401, 402, 403, 404, 422, 429, 500])
def test_failure_is_safe_and_no_files_remain(service_factory, status, tmp_path):
    service = service_factory(lambda request: httpx.Response(status, text=SECRET,
                               headers={"location": "https://example.com/"}))
    with patch("services.remote_voice_service.logger") as log:
        with pytest.raises(RemoteVoiceError) as error:
            asyncio.run(service.synthesize("Привет"))
    assert error.value.code == f"http.{status}"
    assert SECRET not in str(error.value)
    assert SECRET not in str(log.mock_calls)
    assert not list((tmp_path / "audio").glob("*"))
    assert not service.status().verified


@pytest.mark.parametrize("body,content_type", [(b"", "audio/pcm"), (b"a", "audio/pcm"), (b"{}", "application/json")])
def test_invalid_audio_is_removed(service_factory, tmp_path, body, content_type):
    service = service_factory(lambda request: httpx.Response(200, content=body, headers={"content-type": content_type}))
    with pytest.raises(RemoteVoiceError):
        asyncio.run(service.synthesize("Привет"))
    assert not list((tmp_path / "audio").glob("*"))


def test_network_error_details_do_not_expose_key(service_factory):
    def fail(request):
        raise httpx.ReadTimeout(SECRET, request=request)

    service = service_factory(fail)
    with patch("services.remote_voice_service.logger") as log:
        with pytest.raises(RemoteVoiceError) as error:
            asyncio.run(service.synthesize("Привет"))
    assert SECRET not in str(error.value)
    assert SECRET not in str(log.mock_calls)
    assert error.value.__suppress_context__


def test_profile_persistence_normalization_and_templates(service_factory, tmp_path):
    service = service_factory(lambda request: httpx.Response(200, content=b"\x00\x00"))
    active = service.configuration().active
    assert SECRET not in repr(active)
    assert SECRET not in repr(service.configuration())
    service.save_preset(replace(active, voice_id="https://fish.audio/m/" + VOICE_ID.upper() + "/"))
    assert service.configuration().active.voice_id == VOICE_ID
    second = service.add_preset("fish_audio").active
    assert second.model == "s1" and second.api_key == ""
    service.select_preset(active.id)
    assert service.configuration().active.api_key == SECRET
    assert RemoteVoiceRepository(tmp_path / "profiles.json").load() == service.configuration()
    service.delete_preset(second.id)
    with pytest.raises(RemoteVoiceError, match="хотя бы один"):
        service.delete_preset(active.id)
    with pytest.raises(RemoteVoiceError):
        service.save_preset(replace(active, template_id="custom"))
    with pytest.raises(RemoteVoiceError):
        service.save_preset(replace(active, model="invented"))
    assert service.templates()[0].endpoint == "https://api.fish.audio/v1/tts"


@pytest.mark.parametrize("field,value", [("voice_id", "https://evil.example/" + VOICE_ID),
                                         ("voice_id", "bad"), ("speed", float("nan")),
                                         ("api_key", "secret\nheader"), ("name", "")])
def test_invalid_profile_cannot_be_saved(service_factory, field, value):
    service = service_factory(lambda request: httpx.Response(200))
    previous = service.configuration()
    with pytest.raises(RemoteVoiceError):
        service.save_preset(replace(previous.active, **{field: value}))
    assert service.configuration() == previous


def test_cancelled_request_cleans_output(service_factory, tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def respond(request):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, content=b"\x00\x00")

    service = service_factory(respond)

    async def run():
        task = asyncio.create_task(service.synthesize("Привет"))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

    asyncio.run(run())
    assert not list((tmp_path / "audio").glob("*"))
    assert not service.status().verified


def test_closed_service_makes_no_request(service_factory):
    requested = []
    service = service_factory(lambda request: requested.append(request) or httpx.Response(200))
    service.close()
    with pytest.raises(RemoteVoiceError, match="закрыт"):
        asyncio.run(service.synthesize("Привет"))
    assert not requested


def test_no_speech_does_not_spend_api_quota(service_factory):
    requested = []
    service = service_factory(lambda request: requested.append(request) or httpx.Response(200))
    with pytest.raises(RemoteVoiceError):
        asyncio.run(service.synthesize("<command>hidden</command>"))
    assert not requested


def test_later_error_invalidates_verified_status(service_factory):
    statuses = iter([200, 401])
    service = service_factory(lambda request: httpx.Response(next(statuses), content=b"\x00\x00"))
    asyncio.run(service.synthesize("Привет"))
    assert service.status().verified
    with pytest.raises(RemoteVoiceError):
        asyncio.run(service.synthesize("Привет"))
    assert not service.status().verified


def test_bad_repository_has_safe_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(SECRET)
    with pytest.raises(RemoteVoiceError) as error:
        RemoteVoiceRepository(path).load()
    assert SECRET not in str(error.value)


def test_character_voices_are_routed_independently(service_factory):
    references = []
    kind_voice = "a" * 32
    cappie_voice = "b" * 32

    def respond(request):
        references.append(json.loads(request.content)["reference_id"])
        return httpx.Response(200, content=b"\x00\x00")

    service = service_factory(respond)
    service.save_preset(replace(service.configuration().active, character_voices=(
        RemoteCharacterVoice("Kind", kind_voice), RemoteCharacterVoice("Cappie", cappie_voice),
    )))

    async def run():
        await asyncio.gather(service.synthesize("Привет", character_id="Kind"),
                             service.synthesize("Привет", character_id="Cappie"))

    asyncio.run(run())
    assert sorted(references) == [kind_voice, cappie_voice]
    assert service.status(character_id="Kind").verified
    assert service.status(character_id="Cappie").verified
    assert not service.status(character_id="Crazy").verified
    asyncio.run(service.synthesize("Привет", character_id="Crazy"))
    assert references[-1] == VOICE_ID


def test_individual_voice_without_default_and_verification_isolation(service_factory):
    service = service_factory(lambda request: httpx.Response(200, content=b"\x00\x00"))
    service.save_preset(replace(service.configuration().active, voice_id="", character_voices=(
        RemoteCharacterVoice("Kind", "a" * 32), RemoteCharacterVoice("Cappie", "b" * 32),
    )))
    assert service.status().configured
    assert service.status(character_id="Kind").configured
    assert not service.status(character_id="Crazy").configured
    with pytest.raises(RemoteVoiceError):
        asyncio.run(service.synthesize("Привет", character_id="Crazy"))
    asyncio.run(service.synthesize("Привет", character_id="Kind"))
    service.save_preset(replace(service.configuration().active, character_voices=(
        RemoteCharacterVoice("Kind", "a" * 32), RemoteCharacterVoice("Cappie", "c" * 32),
    )))
    assert service.status(character_id="Kind").verified
    assert not service.status(character_id="Cappie").verified


def test_assignments_persist_and_v1_default_migrates(service_factory, tmp_path):
    service = service_factory(lambda request: httpx.Response(200))
    service.save_preset(replace(service.configuration().active, character_voices=(
        RemoteCharacterVoice("Kind", "https://fish.audio/m/" + "A" * 32),
    )))
    config = RemoteVoiceRepository(tmp_path / "profiles.json").load()
    assert config.active.character_voices == (RemoteCharacterVoice("Kind", "a" * 32),)
    assert config.active.voice_id == VOICE_ID
    data = json.loads((tmp_path / "profiles.json").read_text())
    assert data["version"] == 3
    data["version"] = 1
    for preset in data["presets"]:
        preset.pop("character_voices")
        preset.pop("voice_display_name")
    (tmp_path / "profiles.json").write_text(json.dumps(data))
    migrated = RemoteVoiceRepository(tmp_path / "profiles.json").load()
    assert migrated.active.voice_id == VOICE_ID
    assert migrated.active.character_voices == ()


def test_voice_display_names_persist_without_affecting_synthesis(service_factory, tmp_path):
    references = []
    service = service_factory(lambda request: references.append(json.loads(request.content)["reference_id"]) or httpx.Response(200, content=b"\x00\x00"))
    service.save_preset(replace(service.configuration().active, voice_display_name="Общий · основной",
        character_voices=(RemoteCharacterVoice("Kind", "a" * 32, "Добрая · спокойный"),)))
    asyncio.run(service.synthesize("Привет", character_id="Kind"))
    assert references == ["a" * 32]
    service.save_preset(replace(service.configuration().active,
        character_voices=(RemoteCharacterVoice("Kind", "a" * 32, "Новое название"),)))
    assert service.status(character_id="Kind").verified
    config = RemoteVoiceRepository(tmp_path / "profiles.json").load()
    assert config.active.voice_display_name == "Общий · основной"
    assert config.active.character_voices[0].display_name == "Новое название"
