import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from installables.registry_builder import build_installable_registry
from installables.voice_assets import MITA_VOICES
from utils import voice_assets_installer as vi


def _make_bundle(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


class VoiceAssetsRegistryTests(unittest.TestCase):
    def test_registry_exposes_all_voices_and_aggregate(self):
        registry = build_installable_registry()
        self.assertIsNotNone(registry.get("voices:all"))
        for spec in MITA_VOICES:
            self.assertIsNotNone(registry.get(f"voices:{spec['short_name']}"))

    def test_bundle_url_points_at_release_asset(self):
        self.assertEqual(
            vi.bundle_url("CrazyMita", repo="Atm4x/NeuroMita", tag="voice-assets"),
            "https://github.com/Atm4x/NeuroMita/releases/download/voice-assets/CrazyMita.zip",
        )


class VoiceBundleExtractionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_extract_flat_layout(self):
        zip_path = self.root / "CrazyMita.zip"
        _make_bundle(zip_path, {
            "CrazyMita.pth": b"pth",
            "CrazyMita.index": b"idx",
            "CrazyMita.wav": b"wav",
            "CrazyMita.txt": b"txt",
            "CrazyMita_Cuts/CrazyMita_default.wav": b"cut",
        })
        out = self.root / "Models"
        self.assertTrue(vi.extract_bundle(zip_path, "CrazyMita", base=out))
        self.assertTrue((out / "CrazyMita.pth").exists())
        self.assertTrue((out / "CrazyMita_Cuts" / "CrazyMita_default.wav").exists())

    def test_extract_strips_models_wrapper(self):
        zip_path = self.root / "Mila.zip"
        _make_bundle(zip_path, {
            "Models/Mila.pth": b"pth",
            "Models/Mila.index": b"idx",
        })
        out = self.root / "Models"
        self.assertTrue(vi.extract_bundle(zip_path, "Mila", base=out))
        self.assertTrue((out / "Mila.pth").exists())
        self.assertFalse((out / "Models").exists())

    def test_extract_rejects_path_traversal(self):
        zip_path = self.root / "Evil.zip"
        _make_bundle(zip_path, {
            "Evil.pth": b"ok",
            "../escape.txt": b"nope",
        })
        out = self.root / "Models"
        vi.extract_bundle(zip_path, "Evil", base=out)
        self.assertTrue((out / "Evil.pth").exists())
        self.assertFalse((self.root / "escape.txt").exists())

    def test_remove_assets_clears_files_and_cuts(self):
        out = self.root / "Models"
        (out / "Crazy_Cuts").mkdir(parents=True)
        for rel in ("Crazy.pth", "Crazy.onnx", "Crazy.index", "Crazy.wav", "Crazy.txt"):
            (out / rel).write_bytes(b"x")
        (out / "Crazy_Cuts" / "Crazy_default.wav").write_bytes(b"x")
        (out / "Crazy_Cuts" / "Crazy_default.txt").write_bytes(b"x")

        self.assertTrue(vi.remove_assets("Crazy", base=out))
        self.assertFalse((out / "Crazy.pth").exists())
        self.assertFalse((out / "Crazy_Cuts").exists())  # emptied dir is removed


if __name__ == "__main__":
    unittest.main()
