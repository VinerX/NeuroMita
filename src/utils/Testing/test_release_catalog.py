from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.release_catalog import (
    MANIFEST_ASSET_NAME,
    ReleaseCatalogError,
    build_release_manifest,
    discover_release_catalog,
    manifest_download_url,
    parse_release_manifest,
)


def _release(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    published_at: str = "2026-09-01T12:00:00Z",
) -> dict:
    return {
        "tag_name": tag,
        "name": f"NeuroMita {tag}",
        "body": "Changes",
        "draft": draft,
        "prerelease": prerelease,
        "created_at": published_at,
        "published_at": published_at,
        "html_url": f"https://github.com/Atm4x/NeuroMita/releases/tag/{tag}",
        "assets": [
            {
                "name": f"PythonBuild-{tag}.zip",
                "browser_download_url": (
                    f"https://github.com/Atm4x/NeuroMita/releases/download/{tag}/"
                    f"PythonBuild-{tag}.zip"
                ),
                "size": 123,
                "content_type": "application/zip",
                "digest": "sha256:" + "a" * 64,
            },
            {
                "name": MANIFEST_ASSET_NAME,
                "browser_download_url": "https://example.invalid/old-manifest.json",
                "size": 10,
            },
        ],
    }


def test_build_manifest_keeps_known_public_versions_and_channels() -> None:
    manifest = build_release_manifest(
        "Atm4x/NeuroMita",
        [
            _release("v2026.09.03-beta", prerelease=True, published_at="2026-09-03T12:00:00Z"),
            _release("v2026.09.02", draft=True, published_at="2026-09-02T12:00:00Z"),
            _release("v2026.09.01"),
        ],
        stable_tag="v2026.09.01",
        generated_at="2026-09-04T00:00:00Z",
    )

    assert manifest["channels"] == {
        "stable": "v2026.09.01",
        "beta": "v2026.09.03-beta",
    }
    assert [release["tag_name"] for release in manifest["releases"]] == [
        "v2026.09.03-beta",
        "v2026.09.01",
    ]
    assert [asset["name"] for asset in manifest["releases"][0]["assets"]] == [
        "PythonBuild-v2026.09.03-beta.zip"
    ]


def test_parse_manifest_rejects_a_different_repository() -> None:
    payload = build_release_manifest("Atm4x/NeuroMita", [_release("v2026.09.01")])
    with pytest.raises(ReleaseCatalogError, match="repository mismatch"):
        parse_release_manifest(payload, expected_repository="VinerX/NeuroMita")


def test_discovery_prefers_manifest_without_calling_api() -> None:
    payload = build_release_manifest("Atm4x/NeuroMita", [_release("v2026.09.01")])
    requested: list[str] = []

    class Client:
        def get(self, url, **_kwargs):
            requested.append(url)
            return SimpleNamespace(status_code=200, json=lambda: payload)

    catalog = discover_release_catalog("Atm4x/NeuroMita", client=Client())

    assert catalog.source == "manifest"
    assert catalog.releases[0]["tag_name"] == "v2026.09.01"
    assert requested == [manifest_download_url("Atm4x/NeuroMita")]


def test_discovery_falls_back_to_github_api_before_manifest_rollout() -> None:
    release = _release("v2026.09.01")
    requested: list[str] = []

    class Client:
        def get(self, url, **_kwargs):
            requested.append(url)
            if "releases/latest/download" in url:
                return SimpleNamespace(status_code=404, json=lambda: {})
            return SimpleNamespace(status_code=200, json=lambda: [release])

    catalog = discover_release_catalog("Atm4x/NeuroMita", client=Client())

    assert catalog.source == "github-api"
    assert catalog.releases[0]["tag_name"] == "v2026.09.01"
    assert len(requested) == 2


def test_discovery_reports_both_failed_sources() -> None:
    class Client:
        def get(self, url, **_kwargs):
            return SimpleNamespace(status_code=503, json=lambda: {})

    with pytest.raises(ReleaseCatalogError) as caught:
        discover_release_catalog("Atm4x/NeuroMita", client=Client())

    assert "manifest:" in str(caught.value)
    assert "github-api:" in str(caught.value)
