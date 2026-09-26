from __future__ import annotations

import asyncio
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.external_tts_service import (
    ExternalTTSAuthenticationError,
    ExternalTTSClient,
    ExternalTTSConfig,
    ExternalTTSConfigError,
    ExternalTTSAudioError,
    ExternalTTSConnectionError,
    ExternalTTSSizeError,
)


def wav_bytes() -> bytes:
    import io
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 120)
    return output.getvalue()


class ExternalTTSServiceTests(unittest.TestCase):
    def test_health_accepts_protocol_v1_without_synthesizing(self):
        class Content:
            async def iter_chunked(self, _size):
                yield b'{"status":"ok","api_version":1}'

        class Response:
            status = 200
            content_type = "application/json"
            content_length = 32
            content = Content()
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def get(self, *_args, **_kwargs): return Response()
            def post(self, *_args, **_kwargs): raise AssertionError("health must not synthesize")

        with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
            result = asyncio.run(ExternalTTSClient().health(ExternalTTSConfig("http://localhost")))
        self.assertEqual(result["api_version"], 1)

    def test_endpoint_paths_are_appended_to_base_url_and_cannot_change_host(self):
        self.assertEqual(
            ExternalTTSClient._endpoint_url("https://tts.example/prefix", "status"),
            "https://tts.example/prefix/status",
        )
        for path in ("//evil.example/status", "https://evil.example/status", "/a/../status", " "):
            with self.subTest(path=path), self.assertRaises(ExternalTTSConfigError):
                ExternalTTSClient._endpoint_url("https://tts.example", path)

    def test_health_uses_configured_path(self):
        class Content:
            async def iter_chunked(self, _size):
                yield b'{"status":"ok","api_version":1}'

        class Response:
            status = 200
            content_type = "application/json"
            content_length = 32
            content = Content()
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def get(self, url, **_kwargs):
                self.url = url
                return Response()
            def post(self, *_args, **_kwargs): raise AssertionError("health must not synthesize")

        session = Session()
        with patch("services.external_tts_service.aiohttp.ClientSession", return_value=session):
            asyncio.run(ExternalTTSClient().health(ExternalTTSConfig(
                "http://localhost/prefix", health_path="/status"
            )))
        self.assertEqual(session.url, "http://localhost/prefix/status")

    def test_rejects_missing_output_folder_instead_of_using_working_directory(self):
        with self.assertRaises(ExternalTTSConfigError):
            asyncio.run(ExternalTTSClient().synthesize(
                ExternalTTSConfig("http://localhost:8080"), "hello"
            ))

    def test_cleans_only_stale_owned_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stale = root / "external_tts_old.wav"
            partial = root / "external_tts_old_dead.part"
            unrelated = root / "user.wav"
            for path in (stale, partial, unrelated):
                path.write_bytes(b"x")
            old = 1
            import os
            os.utime(stale, (old, old))
            os.utime(partial, (old, old))
            ExternalTTSClient._cleanup_stale_output(root)
            self.assertFalse(stale.exists())
            self.assertFalse(partial.exists())
            self.assertTrue(unrelated.exists())

    def test_maps_auth_failure_without_leaking_response_body(self):
        class Response:
            status = 401
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def get(self, *_args, **_kwargs): return Response()

        with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
            with self.assertRaises(ExternalTTSAuthenticationError):
                asyncio.run(ExternalTTSClient().health(ExternalTTSConfig("http://localhost")))

    def test_synthesis_saves_valid_wav_atomically(self):
        audio = wav_bytes()

        class Content:
            async def iter_chunked(self, _size):
                yield audio

        class Response:
            status = 200
            headers = {"Content-Type": "audio/wav"}
            content_length = len(audio)
            content = Content()
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def post(self, url, **_kwargs):
                self.url = url
                return Response()

        with tempfile.TemporaryDirectory() as folder:
            config = ExternalTTSConfig(
                "http://localhost/prefix", output_dir=folder, synthesize_path="/tts/generate"
            )
            session = Session()
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=session):
                result = asyncio.run(ExternalTTSClient().synthesize(config, "hello"))
            self.assertTrue(Path(result).is_file())
            self.assertEqual(Path(result).read_bytes(), audio)
            self.assertEqual(list(Path(folder).glob("*.part")), [])
            self.assertEqual(session.url, "http://localhost/prefix/tts/generate")

    def test_bad_content_type_removes_partial_download(self):
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}
            content_length = 2
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def post(self, *_args, **_kwargs): return Response()

        with tempfile.TemporaryDirectory() as folder:
            config = ExternalTTSConfig("http://localhost", output_dir=folder)
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
                with self.assertRaises(ExternalTTSAudioError):
                    asyncio.run(ExternalTTSClient().synthesize(config, "hello"))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_timeout_and_cancel_remove_partial_files(self):
        class TimeoutContent:
            async def iter_chunked(self, _size):
                yield b"RIFFpartial"
                raise asyncio.TimeoutError()

        class Response:
            status = 200
            headers = {"Content-Type": "audio/wav"}
            content_length = None
            content = TimeoutContent()
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def post(self, *_args, **_kwargs): return Response()

        with tempfile.TemporaryDirectory() as folder:
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
                with self.assertRaises(ExternalTTSConnectionError):
                    asyncio.run(ExternalTTSClient().synthesize(
                        ExternalTTSConfig("http://localhost", output_dir=folder), "hello"
                    ))
            self.assertEqual(list(Path(folder).iterdir()), [])

            class UnavailableSession(Session):
                def post(self, *_args, **_kwargs):
                    raise __import__("aiohttp").ClientError("offline")

            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=UnavailableSession()):
                with self.assertRaises(ExternalTTSConnectionError):
                    asyncio.run(ExternalTTSClient().synthesize(
                        ExternalTTSConfig("http://localhost", output_dir=folder), "hello"
                    ))
            self.assertEqual(list(Path(folder).iterdir()), [])

        class BlockingContent:
            def __init__(self):
                self.release = asyncio.Event()
            async def iter_chunked(self, _size):
                yield b"RIFFpartial"
                await self.release.wait()

        class BlockingResponse(Response):
            content = BlockingContent()

        class BlockingSession(Session):
            def post(self, *_args, **_kwargs): return BlockingResponse()

        async def cancel_request(folder):
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=BlockingSession()):
                task = asyncio.create_task(ExternalTTSClient().synthesize(
                    ExternalTTSConfig("http://localhost", output_dir=folder), "hello"
                ))
                while not list(Path(folder).glob("*.part")):
                    await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(cancel_request(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_rejects_corrupt_wav_and_audio_size_over_limit(self):
        class Content:
            data = b"not-a-wave"
            async def iter_chunked(self, _size):
                yield self.data

        class Response:
            status = 200
            headers = {"Content-Type": "audio/wav"}
            content_length = None
            content = Content()
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return False
            def post(self, *_args, **_kwargs): return Response()

        with tempfile.TemporaryDirectory() as folder:
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
                with self.assertRaises(ExternalTTSAudioError):
                    asyncio.run(ExternalTTSClient().synthesize(
                        ExternalTTSConfig("http://localhost", output_dir=folder), "hello"
                    ))
            self.assertEqual(list(Path(folder).iterdir()), [])

        class LargeContent(Content):
            data = b"x" * 100

        class LargeResponse(Response):
            content = LargeContent()

        class LargeSession(Session):
            def post(self, *_args, **_kwargs): return LargeResponse()

        with tempfile.TemporaryDirectory() as folder:
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=LargeSession()):
                with self.assertRaises(ExternalTTSSizeError):
                    asyncio.run(ExternalTTSClient().synthesize(
                        ExternalTTSConfig("http://localhost", output_dir=folder, max_audio_bytes=64), "hello"
                    ))
            self.assertEqual(list(Path(folder).iterdir()), [])
