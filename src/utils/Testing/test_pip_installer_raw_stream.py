from __future__ import annotations

import sys
import unittest

from utils.pip_installer import PipInstaller


class PipInstallerRawStreamTests(unittest.TestCase):
    def test_winpty_forwards_exact_raw_chunk_separately_from_parsed_log(self):
        semantic: list[str] = []
        raw: list[str] = []
        installer = PipInstaller(
            update_status=lambda *_: None,
            update_log=semantic.append,
            update_raw_log=raw.append,
            update_progress=lambda *_: None,
            protected_packages=[],
        )
        state = installer._RunState("Installing...", [sys.executable, "-m", "uv"])
        state.uv_progress = installer._UvProgressAggregator()
        chunk = "\x1b[31mResolving\x1b[0m\r[1/1] package\n"

        class FakePty:
            def __init__(self):
                self._chunks = [chunk]
                self.exitstatus = 0
                self._alive = True

            def isalive(self):
                return self._alive

            def read(self, _size):
                if self._chunks:
                    value = self._chunks.pop(0)
                    self._alive = False
                    return value
                self._alive = False
                return ""

            def close(self, force=True):
                self._alive = False

        class FakePtyProcess:
            @staticmethod
            def spawn(_cmdline, env=None):
                return FakePty()

        ok, ret = installer._run_with_winpty(
            [sys.executable, "-m", "uv", "pip", "install", "package"],
            {},
            state,
            FakePtyProcess,
        )

        self.assertTrue(ok)
        self.assertEqual(ret, 0)
        self.assertEqual("".join(raw), chunk)
        self.assertNotIn("\x1b", "\n".join(semantic))

    def test_pipe_stream_preserves_line_ending_for_raw_callback(self):
        semantic: list[str] = []
        raw: list[str] = []
        installer = PipInstaller(
            update_status=lambda *_: None,
            update_log=semantic.append,
            update_raw_log=raw.append,
            update_progress=lambda *_: None,
            protected_packages=[],
        )
        state = installer._RunState("Installing...", [sys.executable])
        ok, ret = installer._run_with_pipes(
            [sys.executable, "-c", "print('exact-line')"],
            {},
            state,
        )

        self.assertTrue(ok)
        self.assertEqual(ret, 0)
        self.assertEqual("".join(raw), "exact-line\n")
        self.assertIn("exact-line", semantic)


if __name__ == "__main__":
    unittest.main()
