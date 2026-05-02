"""Tests for src/utils/release_assets.py

Run with:
    "C:/Games/NeuroMita/Venv/Scripts/python.exe" -m pytest src/utils/Testing/test_release_assets.py -v
"""
import sys
from pathlib import Path

# Allow import without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.release_assets import (  # noqa: E402
    PickedAssets,
    Release,
    ReleaseAsset,
    find_latest_python_full,
    parse_release,
    pick_from_release,
    pick_latest,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _a(name: str) -> ReleaseAsset:
    return ReleaseAsset(name=name, url=f"https://example.com/{name}", size=1024)


def _r(tag: str, name: str, assets: list, prerelease: bool = False) -> Release:
    return Release(tag=tag, name=name, prerelease=prerelease, body="", published_at="", assets=assets)


# ── pick_from_release ─────────────────────────────────────────────────────────

def test_picks_unity_and_python_full():
    r = _r("v1.0.0", "v1.0.0", [
        _a("UnityBuild-v1.0.0.7z"),
        _a("PythonBuild-v1.0.0.zip"),
        _a("README.txt"),
    ])
    p = pick_from_release(r)
    assert p.unity is not None and "UnityBuild" in p.unity.name
    assert p.python_full is not None and "PythonBuild" in p.python_full.name
    assert p.python_patch is None


def test_release_name_marks_patch():
    r = _r("v1.1.0", "v1.1.0 Patch", [_a("PythonBuild-v1.1.0.7z")])
    p = pick_from_release(r)
    assert p.python_patch is not None
    assert p.python_full is None


def test_filename_marks_patch():
    r = _r("v1.1.0", "v1.1.0", [
        _a("PythonBuild-v1.1.0-Patch.7z"),
        _a("UnityBuild-v1.1.0.zip"),
    ])
    p = pick_from_release(r)
    assert p.python_patch is not None and "Patch" in p.python_patch.name
    assert p.python_full is None
    assert p.unity is not None


def test_unsupported_ext_skipped():
    r = _r("v1", "v1", [_a("PythonBuild.rar"), _a("UnityBuild.tar.gz")])
    p = pick_from_release(r)
    assert p == PickedAssets()


def test_empty_assets():
    r = _r("v1", "v1", [])
    p = pick_from_release(r)
    assert p == PickedAssets()


def test_case_insensitive_matching():
    r = _r("v1", "v1", [
        _a("pythonbuild-v1.zip"),
        _a("UNITYBUILD-v1.7z"),
    ])
    p = pick_from_release(r)
    assert p.python_full is not None
    assert p.unity is not None


def test_only_first_asset_of_each_type_picked():
    r = _r("v1", "v1", [
        _a("PythonBuild-v1-a.zip"),
        _a("PythonBuild-v1-b.zip"),
    ])
    p = pick_from_release(r)
    assert p.python_full is not None
    assert p.python_full.name == "PythonBuild-v1-a.zip"


# ── pick_latest ───────────────────────────────────────────────────────────────

def test_pick_latest_stable_skips_prerelease():
    beta = _r("v1.2.0", "beta", [_a("PythonBuild-v1.2.0.zip")], prerelease=True)
    stable = _r("v1.1.0", "stable", [_a("PythonBuild-v1.1.0.zip")])
    r, _ = pick_latest([beta, stable], "stable")
    assert r is stable


def test_pick_latest_beta_accepts_prerelease():
    beta = _r("v1.2.0", "beta", [_a("PythonBuild-v1.2.0.zip")], prerelease=True)
    stable = _r("v1.1.0", "stable", [_a("PythonBuild-v1.1.0.zip")])
    r, _ = pick_latest([beta, stable], "beta")
    assert r is beta


def test_pick_latest_empty_list():
    r, p = pick_latest([], "stable")
    assert r is None
    assert p == PickedAssets()


def test_pick_latest_no_matching_assets():
    r1 = _r("v1", "v1", [_a("random.txt")])
    result, p = pick_latest([r1], "stable")
    assert result is None


# ── find_latest_python_full ───────────────────────────────────────────────────

def test_find_latest_full_skips_patch_releases():
    patch = _r("v1.2.0", "v1.2.0 Patch", [_a("PythonBuild-v1.2.0-Patch.7z")])
    full = _r("v1.1.0", "v1.1.0", [_a("PythonBuild-v1.1.0.zip")])
    r, a = find_latest_python_full([patch, full], "stable")
    assert r is full
    assert a is not None


def test_find_latest_full_returns_none_if_all_patches():
    releases = [
        _r("v1.2.0", "Patch", [_a("PythonBuild-v1.2.0-Patch.zip")]),
        _r("v1.1.0", "Patch", [_a("PythonBuild-v1.1.0-Patch.zip")]),
    ]
    r, a = find_latest_python_full(releases, "stable")
    assert r is None and a is None


# ── parse_release ─────────────────────────────────────────────────────────────

def test_parse_release_basic():
    raw = {
        "tag_name": "v2.0.0",
        "name": "Release v2.0.0",
        "prerelease": False,
        "body": "Changes",
        "published_at": "2026-01-01T00:00:00Z",
        "assets": [
            {"name": "PythonBuild-v2.0.0.zip", "browser_download_url": "https://x/a.zip", "size": 500, "content_type": "application/zip"},
        ],
    }
    r = parse_release(raw)
    assert r.tag == "v2.0.0"
    assert len(r.assets) == 1
    assert r.assets[0].name == "PythonBuild-v2.0.0.zip"
    assert not r.is_patch


def test_parse_release_is_patch():
    raw = {"tag_name": "v2.1.0-patch", "name": "patch", "prerelease": False, "body": "", "published_at": "", "assets": []}
    r = parse_release(raw)
    assert r.is_patch


def test_parse_release_missing_name_falls_back_to_tag():
    raw = {"tag_name": "v1.0.0", "name": None, "prerelease": False, "body": "", "published_at": "", "assets": []}
    r = parse_release(raw)
    assert r.name == "v1.0.0"
