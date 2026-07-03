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


class VoiceIsInstalledTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("NEUROMITA_MODELS_DIR")
        os.environ["NEUROMITA_MODELS_DIR"] = self._tmp.name
        self.root = Path(self._tmp.name)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("NEUROMITA_MODELS_DIR", None)
        else:
            os.environ["NEUROMITA_MODELS_DIR"] = self._prev
        self._tmp.cleanup()

    def test_pth_only_counts_as_installed(self):
        # Бандл может содержать только .pth (.onnx опционален). На AMD/CPU,
        # где «правильное» расширение .onnx, такой голос всё равно установлен.
        (self.root / "CrazyMita.pth").write_bytes(b"x")
        self.assertTrue(vi.is_installed("CrazyMita"))

    def test_onnx_only_counts_as_installed(self):
        (self.root / "CrazyMita.onnx").write_bytes(b"x")
        self.assertTrue(vi.is_installed("CrazyMita"))

    def test_missing_voice_is_not_installed(self):
        self.assertFalse(vi.is_installed("CrazyMita"))


class VoiceExtractionAtomicityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_corrupt_zip_leaves_no_partial_files(self):
        out = self.root / "Models"
        out.mkdir()
        bad = self.root / "Bad.zip"
        bad.write_bytes(b"not a zip at all")
        self.assertFalse(vi.extract_bundle(bad, "Bad", base=out))
        # Ни целевых файлов, ни staging-каталога не осталось.
        self.assertFalse((out / "Bad.pth").exists())
        self.assertFalse((out / ".stage_Bad").exists())

    def test_successful_extract_removes_stage(self):
        zip_path = self.root / "Crazy.zip"
        _make_bundle(zip_path, {"Crazy.pth": b"pth", "Crazy.wav": b"wav"})
        out = self.root / "Models"
        self.assertTrue(vi.extract_bundle(zip_path, "Crazy", base=out))
        self.assertTrue((out / "Crazy.pth").exists())
        self.assertFalse((out / ".stage_Crazy").exists())


class DefaultInstalledVoiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _touch(self, name):
        Path(self.root, name).write_bytes(b"x")

    def test_prefers_mila_when_present(self):
        from utils import default_installed_voice
        self._touch("Mila.pth")
        self._touch("CrazyMita.pth")
        self.assertEqual(default_installed_voice(self.root, ext="pth"), "Mila")

    def test_falls_back_to_any_installed_when_mila_absent(self):
        from utils import default_installed_voice
        self._touch("CrazyMita.pth")
        self.assertEqual(default_installed_voice(self.root, ext="pth"), "CrazyMita")

    def test_ext_filter_is_respected(self):
        from utils import default_installed_voice
        self._touch("CrazyMita.onnx")  # only onnx present
        # asking for pth, nothing matches -> preferred fallback name
        self.assertEqual(default_installed_voice(self.root, ext="pth"), "Mila")
        self.assertEqual(default_installed_voice(self.root, ext="onnx"), "CrazyMita")

    def test_empty_dir_returns_preferred(self):
        from utils import default_installed_voice
        self.assertEqual(default_installed_voice(self.root), "Mila")


class VoiceVersioningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("NEUROMITA_MODELS_DIR")
        os.environ["NEUROMITA_MODELS_DIR"] = self._tmp.name
        self.root = Path(self._tmp.name)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("NEUROMITA_MODELS_DIR", None)
        else:
            os.environ["NEUROMITA_MODELS_DIR"] = self._prev
        self._tmp.cleanup()

    def _install(self, name="CrazyMita"):
        (self.root / f"{name}.pth").write_bytes(b"x")

    def _manifest(self, name="CrazyMita", **entry):
        return {"schema": 1, "voices": {name: entry}}

    def test_remote_entry_reads_manifest(self):
        m = self._manifest("CrazyMita", date="2026-07-03", sha256="abc")
        self.assertEqual(vi.remote_entry("CrazyMita", m)["date"], "2026-07-03")
        self.assertIsNone(vi.remote_entry("Nope", m))
        self.assertIsNone(vi.remote_entry("CrazyMita", None))

    def test_record_and_read_version_roundtrip(self):
        vi.record_installed_version("CrazyMita", {"date": "2026-07-03", "sha256": "abc", "size": 5})
        got = vi.installed_version("CrazyMita")
        self.assertEqual(got, {"date": "2026-07-03", "sha256": "abc", "size": 5})

    def test_not_installed_never_updates(self):
        m = self._manifest("CrazyMita", date="2026-07-03")
        self.assertFalse(vi.is_update_available("CrazyMita", m))

    def test_installed_without_marker_is_stale(self):
        # Ставился до появления версий → маркера нет → считаем устаревшим.
        self._install()
        m = self._manifest("CrazyMita", date="2026-07-03", sha256="abc")
        self.assertTrue(vi.is_update_available("CrazyMita", m))

    def test_matching_sha_is_up_to_date(self):
        self._install()
        vi.record_installed_version("CrazyMita", {"date": "2026-07-03", "sha256": "abc"})
        m = self._manifest("CrazyMita", date="2026-07-03", sha256="abc")
        self.assertFalse(vi.is_update_available("CrazyMita", m))

    def test_differing_sha_is_update(self):
        self._install()
        vi.record_installed_version("CrazyMita", {"date": "2026-07-03", "sha256": "old"})
        m = self._manifest("CrazyMita", date="2026-07-04", sha256="new")
        self.assertTrue(vi.is_update_available("CrazyMita", m))

    def test_date_fallback_when_no_sha(self):
        self._install()
        vi.record_installed_version("CrazyMita", {"date": "2026-06-20"})
        self.assertTrue(vi.is_update_available("CrazyMita", self._manifest("CrazyMita", date="2026-07-03")))
        vi.record_installed_version("CrazyMita", {"date": "2026-07-03"})
        self.assertFalse(vi.is_update_available("CrazyMita", self._manifest("CrazyMita", date="2026-07-03")))

    def test_no_remote_entry_no_update(self):
        self._install()
        self.assertFalse(vi.is_update_available("CrazyMita", {"schema": 1, "voices": {}}))

    def test_remove_clears_version_marker(self):
        self._install()
        vi.record_installed_version("CrazyMita", {"date": "2026-07-03"})
        self.assertTrue(vi.remove_assets("CrazyMita", base=self.root))
        self.assertIsNone(vi.installed_version("CrazyMita"))

    def test_update_available_plan_redownloads(self):
        from installables.voice_assets import VoiceAssetComponent
        self._install()
        vi.record_installed_version("CrazyMita", {"date": "2026-06-20", "sha256": "old"})
        comp = VoiceAssetComponent({"short_name": "CrazyMita", "title": "Crazy"})
        manifest = self._manifest("CrazyMita", date="2026-07-03", sha256="new")
        # ctx с готовым манифестом минует сеть: подложим его в кэш модуля.
        vi._MANIFEST_CACHE["data"] = manifest
        vi._MANIFEST_CACHE["ts"] = 1e18  # не протухнет
        try:
            plan = comp.build_install_plan({})
            self.assertFalse(plan.already_installed)
            self.assertTrue(any(a.type == "download_http" for a in plan.actions))
        finally:
            vi._MANIFEST_CACHE["data"] = None
            vi._MANIFEST_CACHE["ts"] = 0.0


if __name__ == "__main__":
    unittest.main()
