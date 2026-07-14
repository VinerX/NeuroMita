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

import re
from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_EXT = (".zip", ".7z")


def _version_key(tag: str) -> tuple:
    """Числовой ключ версии из тега для сравнения/сортировки.

    'v2026.06.12_Full' → (2026, 6, 12). Берём только ведущие числовые
    компоненты, игнорируя суффиксы вроде _Full. Нужен, потому что GitHub
    /releases отдаёт список в порядке created_at (даты коммита тега), а не по
    версии или публикации — нельзя доверять порядку списка.
    """
    return tuple(int(n) for n in re.findall(r"\d+", tag or ""))


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int
    content_type: str = ""
    digest: str = ""


@dataclass
class Release:
    tag: str
    name: str
    prerelease: bool
    body: str
    published_at: str
    assets: list[ReleaseAsset] = field(default_factory=list)
    html_url: str = ""

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


def has_launcher_release_assets(release: "Release") -> bool:
    """True when a release contains launcher-consumable Python/Unity assets.

    This intentionally ignores auxiliary releases such as voice bundles:
    they may be valid GitHub releases, but they are not part of the launcher
    update/news contract and should not appear in the main release feed.
    """
    picked = pick_from_release(release)
    return bool(picked.unity or picked.python_full or picked.python_patch)


def raw_release_has_launcher_assets(item: dict) -> bool:
    try:
        return has_launcher_release_assets(parse_release(item))
    except Exception:
        return False


def has_python_release_assets(release: "Release") -> bool:
    """True когда релиз реально несёт Python-сборку (full или patch).

    В отличие от has_launcher_release_assets (любой launcher-ассет, включая
    Unity), судим строго по наличию Python-файла: Unity-only релиз (например
    v2026.07.12 с одним UnityBuild) не должен считаться доступным Python-
    обновлением.
    """
    picked = pick_from_release(release)
    return bool(picked.python_full or picked.python_patch)


def raw_release_has_python_assets(item: dict) -> bool:
    try:
        return has_python_release_assets(parse_release(item))
    except Exception:
        return False


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
        if not has_launcher_release_assets(r):
            continue
        picked = pick_from_release(r)
        if picked.unity or picked.python_full or picked.python_patch:
            return r, picked
    return None, PickedAssets()


def find_latest_python_full(
    releases: list[Release],
    channel: str,
) -> tuple[Optional[Release], Optional[ReleaseAsset]]:
    """Return the highest-version release that has a Python-full asset.

    Сортируем по версии тега, а не доверяем порядку списка GitHub (он по
    created_at коммита тега, из-за чего более старая версия может оказаться
    первой — см. _version_key).
    """
    for r in sorted(releases, key=lambda x: _version_key(x.tag), reverse=True):
        if channel == "stable" and r.prerelease:
            continue
        if not has_launcher_release_assets(r):
            continue
        if r.is_patch:
            continue
        picked = pick_from_release(r)
        if picked.python_full is not None:
            return r, picked.python_full
    return None, None


def find_latest_unity_asset(
    releases: list[Release],
    channel: str,
) -> tuple[Optional[Release], Optional[ReleaseAsset]]:
    """Return the highest-version release that has a Unity asset.

    Сортируем по версии тега, а не доверяем порядку списка GitHub (он по
    created_at коммита тега, из-за чего более старая версия может оказаться
    первой — см. _version_key).
    """
    for r in sorted(releases, key=lambda x: _version_key(x.tag), reverse=True):
        if channel == "stable" and r.prerelease:
            continue
        if not has_launcher_release_assets(r):
            continue
        picked = pick_from_release(r)
        if picked.unity is not None:
            return r, picked.unity
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
            digest=str(a.get("digest") or ""),
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
        html_url=item.get("html_url") or "",
    )
