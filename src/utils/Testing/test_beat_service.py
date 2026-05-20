from __future__ import annotations

import math
import shutil
import unittest
import uuid
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from game_connections.services.beat_service import (
    BEAT_CACHE_VERSION,
    BeatService,
    BeatTrackResult,
)

_TMP_ROOT = Path(__file__).resolve().parents[3] / ".tmp_test_beat_service_runtime"


def _write_test_wav(path: Path, *, frequency_hz: float = 440.0) -> None:
    sr = 22050
    frames = int(sr * 0.5)
    amplitude = 8192
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sr)

        pcm = bytearray()
        for idx in range(frames):
            sample = int(amplitude * math.sin(2.0 * math.pi * float(frequency_hz) * (idx / sr)))
            pcm.extend(sample.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(pcm))


@contextmanager
def _workspace_temp_dir():
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = _TMP_ROOT / f"case_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class BeatServiceTests(unittest.TestCase):
    def test_save_and_load_cache_uses_content_hash_metadata(self):
        with _workspace_temp_dir() as root:
            audio_path = root / "track.wav"
            _write_test_wav(audio_path)

            service = BeatService()
            service._cache_dir = str(root / "beat_sync_cache")

            result = BeatTrackResult(
                beats=[{"time": 0.1, "confidence": 0.9}],
                duration=0.5,
                sr=22050,
                method="unit_test",
                bpm_estimate=120.0,
            )

            service._save_cached_result(str(audio_path), result, track_name="Track A")

            source_hash = service._file_content_hash(str(audio_path))
            cache_path = Path(service._cache_path_for_hash(source_hash))
            self.assertTrue(cache_path.exists())

            payload = cache_path.read_text(encoding="utf-8")
            self.assertIn('"version":2', payload)
            self.assertIn(f'"source_hash":"{source_hash}"', payload)
            self.assertIn('"track_name":"Track A"', payload)

            loaded = service._load_cached_result(str(audio_path))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.method, "unit_test")
            self.assertEqual(loaded.beats[0]["time"], 0.1)
            self.assertEqual(BEAT_CACHE_VERSION, 2)

    def test_build_cache_for_directory_reuses_existing_entries(self):
        with _workspace_temp_dir() as root:
            track_a = root / "a.wav"
            track_b = root / "b.wav"
            _write_test_wav(track_a)
            _write_test_wav(track_b, frequency_hz=660.0)

            service = BeatService()
            service._cache_dir = str(root / "beat_sync_cache")
            fake_result = BeatTrackResult(
                beats=[{"time": 0.1, "confidence": 0.9}],
                duration=0.5,
                sr=22050,
                method="unit_test",
                bpm_estimate=120.0,
            )

            with patch.object(service, "_engine_call_sync", return_value=True), \
                 patch.object(service, "_extract_uncached_sync", return_value=fake_result):
                first = service.build_cache_for_directory(str(root), auto_install=False)
                second = service.build_cache_for_directory(str(root), auto_install=False)

            self.assertEqual(first.scanned_files, 2)
            self.assertEqual(first.generated, 2)
            self.assertEqual(first.cache_hits, 0)
            self.assertEqual(first.failed, 0)

            self.assertEqual(second.scanned_files, 2)
            self.assertEqual(second.generated, 0)
            self.assertEqual(second.cache_hits, 2)
            self.assertEqual(second.failed, 0)


class BeatServiceStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_uses_single_cache_first_chunk(self):
        service = BeatService()
        fake_result = BeatTrackResult(
            beats=[{"time": 0.25, "confidence": 0.8}],
            duration=1.0,
            sr=22050,
            method="cache:beat_this",
            bpm_estimate=128.0,
        )

        with patch.object(service, "extract_beats", AsyncMock(return_value=fake_result)):
            chunks = [
                chunk async for chunk in service.extract_beats_streaming(
                    audio_path="C:/tmp/fake.wav",
                    track_name="fake",
                    auto_install=False,
                )
            ]

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].chunks_total, 1)
        self.assertEqual(chunks[0].method, "cache:beat_this")
        self.assertEqual(chunks[0].beats[0]["time"], 0.25)


if __name__ == "__main__":
    unittest.main()
