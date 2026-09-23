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
            def post(self, *_args, **_kwargs): return Response()

        with tempfile.TemporaryDirectory() as folder:
            config = ExternalTTSConfig("http://localhost", output_dir=folder)
            with patch("services.external_tts_service.aiohttp.ClientSession", return_value=Session()):
                result = asyncio.run(ExternalTTSClient().synthesize(config, "hello"))
            self.assertTrue(Path(result).is_file())
            self.assertEqual(Path(result).read_bytes(), audio)
            self.assertEqual(list(Path(folder).glob("*.part")), [])

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
