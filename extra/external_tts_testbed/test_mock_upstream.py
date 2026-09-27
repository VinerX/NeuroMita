from __future__ import annotations

import io
import json
import threading
import unittest
import wave
import urllib.request
from http.server import ThreadingHTTPServer

from mock_upstream import MockStageHandler, generate_test_wav, parse_test_controls
from smoke_test import verify_wav


class MockUpstreamTests(unittest.TestCase):
    def _start_server(self, stage: str):
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockStageHandler)
        server.stage = stage
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return server

    def test_generates_valid_pcm_wav(self):
        audio = generate_test_wav(duration_seconds=1.25, sample_rate=24000)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 1.25, places=2)

    def test_parses_scenario_controls_without_sending_them_to_voice_engine(self):
        text, controls = parse_test_controls(
            "[[mock:delay=1.5]][[mock:duration=2]][[mock:status=503]] hello"
        )
        self.assertEqual(text, "hello")
        self.assertEqual(controls.delay_seconds, 1.5)
        self.assertEqual(controls.duration_seconds, 2.0)
        self.assertEqual(controls.status_code, 503)
        self.assertFalse(controls.corrupt_wav)

    def test_parses_corrupt_and_connection_drop_scenarios(self):
        _text, controls = parse_test_controls("[[mock:corrupt]][[mock:drop]] hello")
        self.assertTrue(controls.corrupt_wav)
        self.assertTrue(controls.drop_connection)

    def test_smoke_verifier_reads_generated_wav_metadata(self):
        metadata = verify_wav(generate_test_wav(duration_seconds=2.0))
        self.assertEqual(metadata["sample_rate"], 24000)
        self.assertEqual(metadata["channels"], 1)
        self.assertEqual(metadata["duration_seconds"], 2.0)

    def test_f5_mock_returns_synthetic_wav(self):
        server = self._start_server("f5")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/synthesize",
            data=json.dumps({"text": "hello", "voice_id": "test"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "audio/wav")
            self.assertEqual(verify_wav(response.read())["sample_rate"], 24000)

    def test_rvc_mock_roundtrips_wav_as_json_base64(self):
        server = self._start_server("rvc")
        audio = generate_test_wav()
        import base64

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/convert",
            data=json.dumps({"audio_base64": base64.b64encode(audio).decode()}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
        self.assertEqual(base64.b64decode(result["audio_base64"], validate=True), audio)


if __name__ == "__main__":
    unittest.main()
