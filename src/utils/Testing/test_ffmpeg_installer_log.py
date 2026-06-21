import tempfile
import unittest

from utils.ffmpeg_installer import install_ffmpeg


class FfmpegInstallerLogTests(unittest.TestCase):
    def test_download_error_reaches_log_callback(self):
        """A failed download must surface its real reason through the install-log
        sink, not just the file logger (regression: the AI Hub window only showed
        a generic 'failed')."""
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            # Malformed scheme -> requests raises immediately, no network needed.
            ok = install_ffmpeg(target_directory=tmp, url="bogus://no-host/x.zip", log=messages.append)
        self.assertFalse(ok)
        self.assertTrue(messages, "log callback received nothing")
        self.assertTrue(
            any("error" in m.lower() for m in messages),
            f"no error detail surfaced to the install log: {messages}",
        )


if __name__ == "__main__":
    unittest.main()
