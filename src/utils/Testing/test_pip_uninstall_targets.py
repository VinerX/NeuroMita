from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from utils.pip_installer import PipInstaller


def _write(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class _Installer(PipInstaller):
    """PipInstaller, переключённый на изолированный Lib без побочных эффектов."""

    def __init__(self, libs_dir: str):
        super().__init__(update_log=lambda *_: None, update_status=lambda *_: None)
        self.libs_path_abs = os.path.abspath(libs_dir)


class CollectRemovalTargetsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self._tmp.name)
        self.inst = _Installer(str(self.lib))

    def tearDown(self):
        self._tmp.cleanup()

    def _make_record(self, dist_info: str, rel_files: list[str]) -> str:
        di = self.lib / dist_info
        di.mkdir(parents=True, exist_ok=True)
        lines = [f"{rel},sha256=deadbeef,123" for rel in rel_files]
        # dist-info собственные файлы тоже перечислены в RECORD
        lines.append(f"{dist_info}/RECORD,,")
        lines.append(f"{dist_info}/METADATA,sha256=aa,10")
        (di / "RECORD").write_text("\n".join(lines), encoding="utf-8")
        (di / "METADATA").write_text("Name: x\nVersion: 1.0\n", encoding="utf-8")
        return str(di)

    def test_record_targets_exact_files_not_dirs(self):
        # Два пакета делят namespace-каталог google/.
        _write(self.lib / "google" / "protobuf" / "__init__.py")
        _write(self.lib / "google" / "protobuf" / "msg.py")
        _write(self.lib / "google" / "api_core" / "client.py")  # чужой пакет

        di = self._make_record(
            "protobuf-4.0.dist-info",
            ["google/protobuf/__init__.py", "google/protobuf/msg.py"],
        )
        targets = self.inst._collect_removal_targets(di, "protobuf")

        # Возвращаются точные файлы protobuf + сам dist-info, но НЕ каталог google/.
        self.assertIn(str(self.lib / "google" / "protobuf" / "__init__.py"), targets)
        self.assertIn(str(self.lib / "google" / "protobuf" / "msg.py"), targets)
        self.assertNotIn(str(self.lib / "google"), targets)
        self.assertEqual(targets[-1], os.path.abspath(di))

    def test_manual_remove_preserves_sibling_namespace_package(self):
        _write(self.lib / "google" / "protobuf" / "__init__.py")
        _write(self.lib / "google" / "api_core" / "client.py")  # чужой пакет
        di = self._make_record("protobuf-4.0.dist-info", ["google/protobuf/__init__.py"])

        self.assertTrue(self.inst._manual_remove(di, "protobuf"))

        # protobuf вычищен, пустой подкаталог убран, соседний пакет цел.
        self.assertFalse((self.lib / "google" / "protobuf").exists())
        self.assertFalse(Path(di).exists())
        self.assertTrue((self.lib / "google" / "api_core" / "client.py").exists())
        self.assertTrue((self.lib / "google").exists())  # ещё не пуст

    def test_record_entries_outside_lib_are_ignored(self):
        di = self._make_record("evil-1.0.dist-info", ["../../escape.py", "evil/ok.py"])
        _write(self.lib / "evil" / "ok.py")
        targets = self.inst._collect_removal_targets(di, "evil")
        # ../.. отброшен, остался только файл внутри Lib.
        self.assertTrue(all(".." not in t for t in targets))
        self.assertIn(str(self.lib / "evil" / "ok.py"), targets)

    def test_no_record_falls_back_to_top_level_dir(self):
        di = self.lib / "mypkg-1.0.dist-info"
        di.mkdir(parents=True)
        (di / "top_level.txt").write_text("mypkg\n", encoding="utf-8")
        _write(self.lib / "mypkg" / "__init__.py")

        targets = self.inst._collect_removal_targets(str(di), "mypkg")
        # Без RECORD точного списка нет — удаляем каталог целиком.
        self.assertIn(str(self.lib / "mypkg"), targets)

    def test_no_record_no_top_level_falls_back_to_canonical_name(self):
        di = self.lib / "torch-2.0.dist-info"
        di.mkdir(parents=True)
        _write(self.lib / "torch" / "__init__.py")

        targets = self.inst._collect_removal_targets(str(di), "torch")
        self.assertIn(str(self.lib / "torch"), targets)


class RepairBrokenMetadataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self._tmp.name) / ".staging" / "target"
        self.lib.mkdir(parents=True)
        self.inst = _Installer(str(self.lib))

    def tearDown(self):
        self._tmp.cleanup()

    def _dist_info(self, name: str, *, metadata: bytes | None) -> Path:
        di = self.lib / name
        di.mkdir(parents=True, exist_ok=True)
        if metadata is not None:
            (di / "METADATA").write_bytes(metadata)
        return di

    def test_removes_dist_info_without_metadata(self):
        good = self._dist_info("good-1.0.dist-info", metadata=b"Name: good\nVersion: 1.0\n")
        broken = self._dist_info("torch-2.7.1+cu128.dist-info", metadata=None)

        n = self.inst.repair_broken_target_metadata()

        self.assertEqual(n, 1)
        self.assertFalse(broken.exists())
        self.assertTrue(good.exists())

    def test_empty_metadata_is_treated_as_broken(self):
        broken = self._dist_info("torch-2.7.1.dist-info", metadata=b"")
        n = self.inst.repair_broken_target_metadata()
        self.assertEqual(n, 1)
        self.assertFalse(broken.exists())

    def test_healthy_only_changes_nothing(self):
        good = self._dist_info("numpy-1.26.0.dist-info", metadata=b"Name: numpy\n")
        n = self.inst.repair_broken_target_metadata()
        self.assertEqual(n, 0)
        self.assertTrue(good.exists())

    def test_active_target_is_never_repaired_destructively(self):
        active = Path(self._tmp.name) / "environment" / "overlays" / "active"
        active.mkdir(parents=True)
        broken = active / "torch-2.7.1.dist-info"
        broken.mkdir()
        installer = _Installer(str(active))

        n = installer.repair_broken_target_metadata()

        self.assertEqual(n, 0)
        self.assertTrue(broken.exists())


if __name__ == "__main__":
    unittest.main()
