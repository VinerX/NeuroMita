from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.stamp_distribution_metadata import MARKER_PATH, stamp_archive


class DistributionMetadataStampTests(unittest.TestCase):
    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def test_stamp_nested_archive_keeps_marker_next_to_pyz(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "PythonBuild-v2026.08.17.zip"
            root = "neuromita_ci_build"
            pyz_member = f"{root}/NeuroMita.pyz"
            marker_member = f"{root}/{MARKER_PATH}"
            pyz = b"byte-for-byte-tested-pyz\x00\x01\x02"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(pyz_member, pyz)
                archive.writestr(f"{root}/assets/readme.txt", "hello")

            hashes = stamp_archive(
                archive_path,
                contour="test",
                source_repo="Atm4x/NeuroMita",
                source_tag="v2026.08.17",
                source_commit="abc123",
            )

            self.assertEqual(hashes, {pyz_member: self._hash(pyz)})
            with zipfile.ZipFile(archive_path, "r") as archive:
                self.assertEqual(archive.read(pyz_member), pyz)
                marker = json.loads(archive.read(marker_member).decode("utf-8"))
                self.assertNotIn(MARKER_PATH, archive.namelist())
            self.assertEqual(marker["schema"], 1)
            self.assertEqual(marker["contour"], "test")
            self.assertEqual(marker["source_repo"], "Atm4x/NeuroMita")
            self.assertEqual(marker["source_tag"], "v2026.08.17")
            self.assertEqual(marker["source_commit"], "abc123")

    def test_restamp_removes_wrong_marker_and_preserves_pyz(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "PythonBuild.zip"
            root = "neuromita_ci_build"
            pyz_member = f"{root}/NeuroMita.pyz"
            marker_member = f"{root}/{MARKER_PATH}"
            pyz = b"same-python"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(pyz_member, pyz)
                archive.writestr(MARKER_PATH, json.dumps({"schema": 1, "contour": "test"}))
                archive.writestr(marker_member, json.dumps({"schema": 1, "contour": "test"}))

            stamp_archive(
                archive_path,
                contour="release",
                source_repo="Atm4x/NeuroMita",
                source_tag="v2026.08.17",
                source_commit="abc123",
            )

            with zipfile.ZipFile(archive_path, "r") as archive:
                names = archive.namelist()
                marker = json.loads(archive.read(marker_member).decode("utf-8"))
                self.assertEqual(archive.read(pyz_member), pyz)
            marker_names = [
                name for name in names
                if name.replace("\\", "/").casefold().endswith(MARKER_PATH.casefold())
            ]
            self.assertEqual(marker_names, [marker_member])
            self.assertEqual(marker["contour"], "release")

    def test_flat_archive_uses_root_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "flat.zip"
            pyz = b"flat"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("NeuroMita.pyz", pyz)

            stamp_archive(
                archive_path,
                contour="test",
                source_repo="Atm4x/NeuroMita",
                source_tag="v2026.08.17",
                source_commit="abc123",
            )

            with zipfile.ZipFile(archive_path, "r") as archive:
                self.assertIn(MARKER_PATH, archive.namelist())
                self.assertEqual(archive.read("NeuroMita.pyz"), pyz)

    def test_multiple_pyz_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "ambiguous.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a/NeuroMita.pyz", b"a")
                archive.writestr("b/Other.pyz", b"b")

            with self.assertRaisesRegex(RuntimeError, "do not share one directory"):
                stamp_archive(
                    archive_path,
                    contour="test",
                    source_repo="Atm4x/NeuroMita",
                    source_tag="v2026.08.17",
                    source_commit="abc123",
                )

    def test_archive_without_pyz_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("readme.txt", "nothing")

            with self.assertRaisesRegex(RuntimeError, "No \\.pyz artifact"):
                stamp_archive(
                    archive_path,
                    contour="test",
                    source_repo="Atm4x/NeuroMita",
                    source_tag="v2026.08.17",
                    source_commit="abc123",
                )


if __name__ == "__main__":
    unittest.main()
