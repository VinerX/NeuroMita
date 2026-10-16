from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class BuildVersion:
    year: int
    month: int
    day: int
    revision: int = 0

    @property
    def base_tag(self) -> str:
        return f"v{self.year:04}.{self.month:02}.{self.day:02}"

    @property
    def tag(self) -> str:
        return self.base_tag + (f".{self.revision}" if self.revision else "")


def parse_build_version(value: str) -> BuildVersion | None:
    match = re.fullmatch(r"v?(\d{4})\.(\d{2})\.(\d{2})(?:\.([1-9]\d*))?", str(value or ""))
    if match is None:
        return None
    parts = [int(part or 0) for part in match.groups()]
    try:
        date(*parts[:3])
    except ValueError:
        return None
    return BuildVersion(*parts)


def python_archive_version(name: str) -> BuildVersion | None:
    match = re.fullmatch(r"PythonBuild-(v\d{4}\.\d{2}\.\d{2}(?:\.[1-9]\d*)?)\.(?:zip|7z)", str(name), re.IGNORECASE)
    return parse_build_version(match[1]) if match else None


def is_python_archive(name: str) -> bool:
    name = str(name or "").lower()
    return "pythonbuild" in name and name.endswith((".zip", ".7z"))


def project_python_revision(release: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expose build revisions to schema-1 clients without changing Unity's version."""
    entry = dict(release)
    if entry.get("component") == "python" and entry.get("release_tag"):
        return [entry]
    parent = parse_build_version(str(entry.get("tag_name") or ""))
    if parent is None:
        return [entry]
    candidates = []
    for asset in entry.get("assets") or []:
        version = python_archive_version(asset.get("name", ""))
        if version is not None and version.base_tag == parent.base_tag and version > parent:
            candidates.append((version, str(asset["name"]).lower().endswith(".zip"), asset))
    if not candidates:
        return [entry]
    version, _, asset = max(candidates, key=lambda candidate: candidate[:2])
    revision = dict(entry, tag_name=version.tag, release_tag=entry["tag_name"],
                    build_version=version.tag.removeprefix("v"), component="python", assets=[asset])
    entry["assets"] = [asset for asset in entry.get("assets") or [] if not is_python_archive(asset.get("name", ""))]
    return [revision, entry]


def release_tag_for_channel(manifest: Mapping[str, Any], channel: str) -> str:
    tag = str((manifest.get("channels") or {}).get(channel) or "")
    entry = next((entry for entry in manifest.get("releases") or [] if entry.get("tag_name") == tag), {})
    return str(entry.get("release_tag") or tag)


def release_news_entries(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one news card per real GitHub release, including Python-only revisions."""
    grouped: dict[str, dict[str, Any]] = {}
    for entry in releases:
        tag = str(entry.get("release_tag") or entry.get("tag_name") or "")
        if tag not in grouped:
            grouped[tag] = dict(entry, tag_name=tag, assets=list(entry.get("assets") or []))
        else:
            grouped[tag]["assets"].extend(entry.get("assets") or [])
    return list(grouped.values())
