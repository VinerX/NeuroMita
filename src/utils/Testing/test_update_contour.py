from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.update_contour import (
    CONTOUR_SETTING,
    LEGACY_LAST_SHARED_STABLE_VERSION,
    migrate_update_contour,
    target_for_contour,
)


class UpdateContourTests(unittest.TestCase):
    def test_targets_are_fixed_by_contour(self) -> None:
        test = target_for_contour("test")
        self.assertEqual((test.repo, test.channel), ("Atm4x/NeuroMita", "stable"))

        release = target_for_contour("release")
        self.assertEqual((release.repo, release.channel), ("VinerX/NeuroMita", "stable"))

    def test_missing_or_invalid_contour_is_safe_release(self) -> None:
        self.assertEqual(target_for_contour(None).contour, "release")
        self.assertEqual(target_for_contour("something-else").repo, "VinerX/NeuroMita")

    def test_explicit_contour_wins_over_all_legacy_hints(self) -> None:
        settings = {
            CONTOUR_SETTING: "release",
            "UPDATE_CHANNEL": "beta",
            "TESTER_CODE": "23",
        }
        result = migrate_update_contour(settings)
        self.assertEqual(result.contour, "release")
        self.assertFalse(result.changed)
        self.assertEqual(settings[CONTOUR_SETTING], "release")

    def test_legacy_beta_is_migrated_once_to_test(self) -> None:
        settings = {"UPDATE_CHANNEL": "beta"}
        result = migrate_update_contour(settings)
        self.assertEqual((result.contour, result.reason), ("test", "legacy-beta-channel"))
        self.assertTrue(result.changed)
        self.assertEqual(settings[CONTOUR_SETTING], "test")

        settings["UPDATE_CHANNEL"] = "stable"
        second = migrate_update_contour(settings)
        self.assertEqual(second.contour, "test")
        self.assertEqual(second.reason, "explicit")

    def test_legacy_tester_code_is_migrated_to_test(self) -> None:
        settings = {"TESTER_CODE": "23"}
        result = migrate_update_contour(settings)
        self.assertEqual((result.contour, result.reason), ("test", "legacy-tester-code"))

    def test_distribution_marker_bootstraps_fresh_test_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_file = root / "NeuroMita" / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            (settings_file.parent / "distribution.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "contour": "test",
                        "source_repo": "Atm4x/NeuroMita",
                        "source_tag": "v2026.08.17",
                        "source_commit": "abcdef123456",
                    }
                ),
                encoding="utf-8",
            )

            settings: dict[str, str] = {}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("test", "distribution-marker"))
            self.assertEqual(settings[CONTOUR_SETTING], "test")

    def test_distribution_marker_bootstraps_fresh_release_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_file = root / "NeuroMita" / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            (settings_file.parent / "distribution.json").write_text(
                json.dumps({"schema": 1, "contour": "release"}),
                encoding="utf-8",
            )

            settings: dict[str, str] = {}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("release", "distribution-marker"))

    def test_persisted_contour_wins_over_distribution_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_file = root / "NeuroMita" / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            (settings_file.parent / "distribution.json").write_text(
                json.dumps({"schema": 1, "contour": "release"}),
                encoding="utf-8",
            )

            settings = {CONTOUR_SETTING: "test"}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("test", "explicit"))
            self.assertFalse(result.changed)

    def test_invalid_or_future_distribution_marker_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings_file = root / "NeuroMita" / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            (settings_file.parent / "distribution.json").write_text(
                json.dumps({"schema": 999, "contour": "test"}),
                encoding="utf-8",
            )

            settings: dict[str, str] = {}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("release", "default-release"))

    def test_atm4x_journal_after_cutoff_is_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install = root / "NeuroMita"
            settings_file = install / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            journal = root / ".NeuroMita.update-state" / "python" / "operation.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(
                json.dumps(
                    {
                        "version": "v2026.08.16",
                        "archive_url": "https://github.com/Atm4x/NeuroMita/releases/download/v2026.08.16/Python.zip",
                    }
                ),
                encoding="utf-8",
            )

            settings: dict[str, str] = {}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("test", "legacy-atm4x-version"))

    def test_atm4x_journal_at_cutoff_does_not_make_user_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install = root / "NeuroMita"
            settings_file = install / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            journal = root / ".NeuroMita.update-state" / "python" / "operation.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(
                json.dumps(
                    {
                        "version": f"v{LEGACY_LAST_SHARED_STABLE_VERSION}",
                        "archive_url": "https://github.com/Atm4x/NeuroMita/releases/download/old/Python.zip",
                    }
                ),
                encoding="utf-8",
            )

            settings: dict[str, str] = {}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("release", "default-release"))

    def test_embedded_current_version_is_not_used_for_migration(self) -> None:
        # A byte-identical pyz promoted to VinerX may contain a dated version newer
        # than the cutoff. With no external legacy evidence it must stay release.
        settings: dict[str, str] = {}
        result = migrate_update_contour(settings)
        self.assertEqual((result.contour, result.reason), ("release", "default-release"))

    def test_vinerx_journal_is_release_even_if_legacy_beta_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install = root / "NeuroMita"
            settings_file = install / "Settings" / "settings.json"
            settings_file.parent.mkdir(parents=True)
            journal = root / ".NeuroMita.update-state" / "python" / "operation.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(
                json.dumps(
                    {
                        "version": "v2026.09.01",
                        "archive_url": "https://github.com/VinerX/NeuroMita/releases/download/v2026.09.01/Python.zip",
                    }
                ),
                encoding="utf-8",
            )

            settings = {"UPDATE_CHANNEL": "beta"}
            result = migrate_update_contour(settings, config_path=str(settings_file))
            self.assertEqual((result.contour, result.reason), ("release", "legacy-vinerx-journal"))


if __name__ == "__main__":
    unittest.main()
