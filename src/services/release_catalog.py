from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


MANIFEST_SCHEMA = 1
MANIFEST_ASSET_NAME = "releases-manifest.json"


class ReleaseCatalogError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseCatalog:
    repository: str
    releases: list[dict[str, Any]]
    source: str


def _repository(value: str) -> str:
    repository = str(value or "").strip().strip("/")
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid GitHub repository: {value!r}")
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(any(character not in allowed for character in part) for part in parts):
        raise ValueError(f"Invalid GitHub repository: {value!r}")
    return repository


def manifest_download_url(repository: str) -> str:
    repo = _repository(repository)
    return f"https://github.com/{repo}/releases/latest/download/{MANIFEST_ASSET_NAME}"


def github_api_releases_url(repository: str, *, per_page: int = 100) -> str:
    repo = _repository(repository)
    return f"https://api.github.com/repos/{repo}/releases?per_page={int(per_page)}"


def _asset_entry(asset: Mapping[str, Any]) -> dict[str, Any] | None:
    name = str(asset.get("name") or "").strip()
    url = str(asset.get("browser_download_url") or "").strip()
    if not name or not url or name.casefold() == MANIFEST_ASSET_NAME.casefold():
        return None
    try:
        size = max(0, int(asset.get("size") or 0))
    except (TypeError, ValueError):
        size = 0
    return {
        "name": name,
        "browser_download_url": url,
        "size": size,
        "content_type": str(asset.get("content_type") or ""),
        "digest": str(asset.get("digest") or ""),
    }


def _release_entry(release: Mapping[str, Any]) -> dict[str, Any] | None:
    if release.get("draft"):
        return None
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        return None
    assets = []
    for raw_asset in release.get("assets") or []:
        if not isinstance(raw_asset, Mapping):
            continue
        asset = _asset_entry(raw_asset)
        if asset is not None:
            assets.append(asset)
    return {
        "tag_name": tag,
        "name": str(release.get("name") or tag),
        "body": str(release.get("body") or ""),
        "draft": False,
        "prerelease": bool(release.get("prerelease")),
        "created_at": str(release.get("created_at") or ""),
        "published_at": str(release.get("published_at") or ""),
        "html_url": str(release.get("html_url") or ""),
        "assets": assets,
    }


def _published_key(release: Mapping[str, Any]) -> str:
    return str(release.get("published_at") or release.get("created_at") or "")


def build_release_manifest(
    repository: str,
    releases: Iterable[Mapping[str, Any]],
    *,
    stable_tag: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    repo = _repository(repository)
    entries = []
    for raw_release in releases:
        entry = _release_entry(raw_release)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=_published_key, reverse=True)

    known_tags = {entry["tag_name"] for entry in entries}
    stable = str(stable_tag or "").strip()
    if stable not in known_tags:
        stable = next(
            (entry["tag_name"] for entry in entries if not entry["prerelease"]),
            "",
        )
    beta = entries[0]["tag_name"] if entries else ""
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": MANIFEST_SCHEMA,
        "repository": repo,
        "generated_at": timestamp,
        "channels": {"stable": stable, "beta": beta},
        "releases": entries,
    }


def parse_release_manifest(
    payload: Any,
    *,
    expected_repository: str,
) -> list[dict[str, Any]]:
    expected = _repository(expected_repository)
    if not isinstance(payload, Mapping):
        raise ReleaseCatalogError("Release manifest root must be an object")
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ReleaseCatalogError(
            f"Unsupported release manifest schema: {payload.get('schema')!r}"
        )
    actual = str(payload.get("repository") or "").strip()
    if actual.casefold() != expected.casefold():
        raise ReleaseCatalogError(
            f"Release manifest repository mismatch: expected {expected}, got {actual or '<empty>'}"
        )
    raw_releases = payload.get("releases")
    if not isinstance(raw_releases, list):
        raise ReleaseCatalogError("Release manifest releases must be an array")

    releases = []
    for index, raw_release in enumerate(raw_releases):
        if not isinstance(raw_release, Mapping):
            raise ReleaseCatalogError(f"Release manifest entry {index} must be an object")
        entry = _release_entry(raw_release)
        if entry is None:
            if raw_release.get("draft"):
                continue
            raise ReleaseCatalogError(f"Release manifest entry {index} has no tag")
        releases.append(entry)
    releases.sort(key=_published_key, reverse=True)
    return releases


def _response_json(client, url: str, *, timeout: float, headers: dict[str, str]) -> Any:
    response = client.get(url, timeout=timeout, headers=headers)
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        raise ReleaseCatalogError(f"HTTP {status or 'error'} for {url}")
    try:
        return response.json()
    except Exception as error:
        raise ReleaseCatalogError(f"Invalid JSON from {url}: {error}") from error


def discover_release_catalog(
    repository: str,
    *,
    client,
    timeout: float = 8,
    allow_api_fallback: bool = True,
) -> ReleaseCatalog:
    repo = _repository(repository)
    attempts: list[str] = []
    manifest_url = manifest_download_url(repo)
    try:
        payload = _response_json(
            client,
            manifest_url,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "NeuroMita-Updater/3.0"},
        )
        releases = parse_release_manifest(payload, expected_repository=repo)
        return ReleaseCatalog(repo, releases, "manifest")
    except Exception as error:
        attempts.append(f"manifest: {error}")

    if allow_api_fallback:
        api_url = github_api_releases_url(repo)
        try:
            payload = _response_json(
                client,
                api_url,
                timeout=timeout,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "NeuroMita-Updater/3.0",
                },
            )
            if not isinstance(payload, list):
                raise ReleaseCatalogError("GitHub releases response must be an array")
            releases = []
            for raw_release in payload:
                if not isinstance(raw_release, Mapping):
                    continue
                entry = _release_entry(raw_release)
                if entry is not None:
                    releases.append(entry)
            releases.sort(key=_published_key, reverse=True)
            return ReleaseCatalog(repo, releases, "github-api")
        except Exception as error:
            attempts.append(f"github-api: {error}")

    raise ReleaseCatalogError(
        f"Could not load releases for {repo} ({'; '.join(attempts)})"
    )
