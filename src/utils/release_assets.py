"""Match GitHub release assets to Python/Unity builds by name substring.

Rules (case-insensitive):
- Unity:        asset name contains "UnityBuild"
- Python full:  asset name contains "PythonBuild" AND no "Patch" in release tag/name or asset
- Python patch: asset name contains "PythonBuild" AND "Patch" in release tag/name or asset name
- Supported extensions: .zip and .7z

Usage::

    from utils.release_assets import parse_release, pick_latest, find_latest_python_full

    raw_items = fetch_github_releases(repo)  # list of dicts from GitHub API
    releases = [parse_release(r) for r in raw_items]
    release, picked = pick_latest(releases, channel="stable")
    if picked.python_full:
        print(picked.python_full.url)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_EXT = (".zip", ".7z")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int
    content_type: str = ""


@dataclass
class Release:
    tag: str
    name: str
    prerelease: bool
    body: str
    published_at: str
    assets: list[ReleaseAsset] = field(default_factory=list)

    @property
    def is_patch(self) -> bool:
        return "patch" in f"{self.tag} {self.name}".lower()


@dataclass
class PickedAssets:
    unity: Optional[ReleaseAsset] = None
    python_full: Optional[ReleaseAsset] = None
    python_patch: Optional[ReleaseAsset] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ext_ok(name: str) -> bool:
    low = name.lower()
    return any(low.endswith(ext) for ext in SUPPORTED_EXT)


# ── Core selection logic ──────────────────────────────────────────────────────

def pick_from_release(release: Release) -> PickedAssets:
    """Find Unity / Python-full / Python-patch assets inside a single release."""
    picked = PickedAssets()
    release_is_patch = release.is_patch

    for a in release.assets:
        low = a.name.lower()
        if not _ext_ok(a.name):
            continue

        if "unitybuild" in low and picked.unity is None:
            picked.unity = a
            continue

        if "pythonbuild" in low:
            asset_is_patch = "patch" in low or release_is_patch
            if asset_is_patch:
                if picked.python_patch is None:
                    picked.python_patch = a
            else:
                if picked.python_full is None:
                    picked.python_full = a

    return picked


def pick_latest(
    releases: list[Release],
    channel: str,
) -> tuple[Optional[Release], PickedAssets]:
    """Return the newest relevant release for the channel and its picked assets.

    - channel == "stable": skip prereleases.
    - channel == "beta":   accept any.
    Releases are assumed to be sorted newest-first (GitHub API default).
    """
    for r in releases:
        if channel == "stable" and r.prerelease:
            continue
        picked = pick_from_release(r)
        if picked.unity or picked.python_full or picked.python_patch:
            return r, picked
    return None, PickedAssets()


def find_latest_python_full(
    releases: list[Release],
    channel: str,
) -> tuple[Optional[Release], Optional[ReleaseAsset]]:
    """Walk releases newest-first; return the first one with a Python-full asset."""
    for r in releases:
        if channel == "stable" and r.prerelease:
            continue
        if r.is_patch:
            continue
        picked = pick_from_release(r)
        if picked.python_full is not None:
            return r, picked.python_full
    return None, None


# ── GitHub API parsing ────────────────────────────────────────────────────────

def parse_release(item: dict) -> Release:
    """Parse a raw GitHub API release dict into a Release object."""
    assets = [
        ReleaseAsset(
            name=a.get("name", ""),
            url=a.get("browser_download_url", ""),
            size=int(a.get("size") or 0),
            content_type=a.get("content_type", ""),
        )
        for a in (item.get("assets") or [])
    ]
    return Release(
        tag=item.get("tag_name", ""),
        name=item.get("name") or item.get("tag_name", ""),
        prerelease=bool(item.get("prerelease")),
        body=item.get("body") or "",
        published_at=item.get("published_at") or "",
        assets=assets,
    )
