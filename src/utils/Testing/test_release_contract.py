"""Tests for src/release_contract.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[2] / "release_contract.py"
SPEC = importlib.util.spec_from_file_location("release_contract_under_test", MODULE_PATH)
release_contract = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = release_contract
SPEC.loader.exec_module(release_contract)

def _raw_release(tag: str, name: str, assets: list[str], prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": name,
        "prerelease": prerelease,
        "assets": [{"name": asset_name} for asset_name in assets],
    }

def test_validate_local_release_accepts_full_python_archive():
    with patch("pathlib.Path.exists", return_value=True):
        with patch.object(
            release_contract,
            "_list_archive_files",
            return_value=[
                "NeuroMita.pyz",
                "requirements.txt",
                "run.py",
                "run.bat",
                "init.py",
                "init_triton.bat",
                "libs/python/python.exe",
                "Prompts/default.txt",
                "assets/icon.png",
                "libs/site-packages/dummy.txt",
            ],
        ):
            result = release_contract.validate_local_release("v1.2.3", [Path("PythonBuild-v1.2.3.zip")])

    assert result.ok
    assert len(result.assets) == 1
    assert result.assets[0].kind == release_contract.PYTHON_FULL_KIND


def test_validate_local_release_reports_missing_required_file():
    with patch("pathlib.Path.exists", return_value=True):
        with patch.object(
            release_contract,
            "_list_archive_files",
            return_value=[
                "NeuroMita.pyz",
                "requirements.txt",
                "run.py",
                "run.bat",
                "init.py",
                "Prompts/default.txt",
                "assets/icon.png",
                "libs/site-packages/dummy.txt",
            ],
        ):
            result = release_contract.validate_local_release("v1.2.3", [Path("PythonBuild-v1.2.3.zip")])

    assert not result.ok
    messages = [issue.message for issue in result.assets[0].issues]
    assert any("init_triton.bat" in message for message in messages)
    assert any("libs/python/python.exe" in message for message in messages)


def test_validate_local_release_rejects_wrong_asset_name():
    result = release_contract.validate_local_release("v1.2.3", [Path("PythonBuild.zip")])

    assert not result.ok
    assert any("looks like a Python build" in issue.message for issue in result.issues)
    assert any("Asset file does not exist" in issue.message for issue in result.assets[0].issues)


def test_validate_archive_contract_requires_unity_exe():
    with patch.object(
        release_contract,
        "_list_archive_files",
        return_value=["Game_Data/globalgamemanagers"],
    ):
        result = release_contract.validate_archive_contract(
            Path("UnityBuild-v1.2.3.zip"),
            release_contract.UNITY_KIND,
        )

    assert not result.ok
    assert any(".exe" in issue.message for issue in result.issues)


def test_explain_release_fallbacks_reports_previous_python_and_unity_assets():
    result = release_contract.validate_release_assets("v1.2.3", ["PythonBuild-v1.2.3-Patch.zip"])
    other_releases = [
        _raw_release("v1.2.2", "v1.2.2", ["PythonBuild-v1.2.2.zip"]),
        _raw_release("v1.1.0", "v1.1.0", ["UnityBuild-v1.1.0.zip"]),
    ]

    release_contract.explain_release_fallbacks(
        result,
        ["PythonBuild-v1.2.3-Patch.zip"],
        other_releases,
        channel="stable",
    )

    info_messages = [issue.message for issue in result.issues if issue.level == "info"]
    assert any("Python patch fallback is available" in message for message in info_messages)
    assert any("Unity updates remain available" in message for message in info_messages)


def test_explain_release_fallbacks_warns_when_no_previous_unity_exists():
    result = release_contract.validate_release_assets("v1.2.3", ["PythonBuild-v1.2.3.zip"])

    release_contract.explain_release_fallbacks(
        result,
        ["PythonBuild-v1.2.3.zip"],
        [],
        channel="stable",
    )

    warnings = [issue.message for issue in result.issues if issue.level == "warning"]
    assert any("no older Unity release was found" in message for message in warnings)
