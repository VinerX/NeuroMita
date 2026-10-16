from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from release_contract import validate_local_release
from services.release_revisions import is_python_archive, parse_build_version, python_archive_version


class PublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicationPlan:
    build_tag: str
    release_tag: str
    mode: str
    should_release: bool
    previous_tag: str
    recover_revision: bool = False


def publication_plan(version: str, releases: list[dict]) -> PublicationPlan:
    build = parse_build_version(version)
    if build is None:
        raise PublicationError(f"Invalid build version: {version}")
    published = [release for release in releases if not release.get("draft") and not release.get("prerelease")]
    target = next((release for release in published if release.get("tag_name") == build.base_tag), None)
    mode = "revision" if build.revision else "release"
    if mode == "revision":
        if target is None:
            raise PublicationError(f"Revision requires an existing published release {build.base_tag}")
        if target.get("immutable"):
            raise PublicationError(f"Release {build.base_tag} is immutable")
    known = set()
    previous = []
    for release in published:
        tag = parse_build_version(str(release.get("tag_name") or ""))
        if tag is not None:
            known.add(tag)
            if tag < build:
                previous.append(tag)
        for asset in release.get("assets") or []:
            asset_version = python_archive_version(asset.get("name", ""))
            if asset_version is not None:
                known.add(asset_version)
    newer = max(known) if known else None
    should_release = newer is None or build > newer
    recover = mode == "revision" and newer == build and any(
        asset.get("name") == f"PythonBuild-{build.tag}.zip" for asset in (target or {}).get("assets") or []
    )
    return PublicationPlan(build.tag, build.base_tag, mode, should_release,
                           max(previous).tag if previous else "", recover)


class GitHubReleases:
    def __init__(self, repository: str):
        if len(repository.split("/")) != 2 or any(not part or not all(c.isalnum() or c in "-_." for c in part) for part in repository.split("/")):
            raise PublicationError("Invalid repository")
        self.repository = repository

    def run(self, *args: str):
        result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise PublicationError(result.stderr.strip())
        return json.loads(result.stdout) if args[0] == "api" and result.stdout.strip() else None

    def releases(self) -> list[dict]:
        pages = self.run("api", "--paginate", "--slurp", f"repos/{self.repository}/releases?per_page=100")
        return [release for page in pages for release in page]

    def release(self, tag: str) -> dict:
        release = self.run("api", f"repos/{self.repository}/releases/tags/{quote(tag, safe='')}")
        pages = self.run("api", "--paginate", "--slurp", f"repos/{self.repository}/releases/{release['id']}/assets?per_page=100")
        release["assets"] = [asset for page in pages for asset in page]
        return release

    def upload(self, tag: str, archive: Path) -> None:
        self.run("release", "upload", tag, str(archive), "--repo", self.repository)

    def delete(self, asset_id: int) -> None:
        self.run("api", "--method", "DELETE", f"repos/{self.repository}/releases/assets/{int(asset_id)}")


def embedded_version(archive: Path) -> str:
    with zipfile.ZipFile(archive) as package:
        names = [name for name in package.namelist() if name == "NeuroMita.pyz" or name.endswith("/NeuroMita.pyz")]
        if len(names) != 1:
            raise PublicationError("Expected exactly one NeuroMita.pyz")
        with zipfile.ZipFile(io.BytesIO(package.read(names[0]))) as application:
            tree = ast.parse(application.read("_version.py").decode("utf-8-sig"))
    versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise PublicationError("Invalid embedded __version__")
    return versions[0]


def publish_revision(api: GitHubReleases, version: str, archive: Path) -> None:
    build = parse_build_version(version)
    if build is None or not build.revision:
        raise PublicationError("Publishing in-place requires a revision version")
    expected_name = f"PythonBuild-{build.tag}.zip"
    if archive.name != expected_name:
        raise PublicationError(f"Expected {expected_name}")
    release = api.release(build.base_tag)
    if release.get("draft") or release.get("prerelease") or release.get("immutable"):
        raise PublicationError("Target must be a mutable published stable release")
    if any((found := python_archive_version(asset.get("name", ""))) is not None and found > build
           for asset in release.get("assets") or []):
        raise PublicationError("Refusing to replace a newer Python build")
    existing = next((asset for asset in release.get("assets") or [] if asset.get("name") == expected_name), None)
    local_hash = ""
    if archive.is_file():
        validation = validate_local_release(build.tag, [archive])
        if not validation.ok:
            raise PublicationError("Full Python archive failed release contract validation")
        if embedded_version(archive) != build.tag.removeprefix("v"):
            raise PublicationError("Embedded version does not match archive version")
        with archive.open("rb") as source:
            local_hash = hashlib.file_digest(source, "sha256").hexdigest()
    elif existing is None:
        raise PublicationError("Local build is missing and no uploaded revision can be recovered")
    if existing is None:
        api.upload(build.base_tag, archive)
        release = api.release(build.base_tag)
        existing = next((asset for asset in release.get("assets") or [] if asset.get("name") == expected_name), None)
    if existing is None or existing.get("state") != "uploaded" or int(existing.get("size") or 0) <= 0:
        raise PublicationError("Uploaded revision is not complete; previous assets retained")
    digest = str(existing.get("digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PublicationError("Uploaded revision has no SHA-256; previous assets retained")
    if local_hash and (digest != f"sha256:{local_hash}" or int(existing["size"]) != archive.stat().st_size):
        raise PublicationError("Uploaded revision differs from local build; previous assets retained")
    if any((found := python_archive_version(asset.get("name", ""))) is not None and found > build
           for asset in release.get("assets") or []):
        raise PublicationError("A newer Python build appeared during upload; assets retained")
    for asset in release.get("assets") or []:
        if asset.get("id") != existing["id"] and is_python_archive(asset.get("name", "")):
            api.delete(asset["id"])
    remaining = [asset for asset in api.release(build.base_tag).get("assets") or [] if is_python_archive(asset.get("name", ""))]
    if len(remaining) != 1 or remaining[0].get("id") != existing["id"]:
        raise PublicationError("Python asset replacement did not finish")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "publish"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()
    api = GitHubReleases(args.repository)
    if args.command == "publish":
        if args.archive is None:
            parser.error("--archive is required")
        publish_revision(api, args.version, args.archive)
        print(f"Published build {args.version} in its existing release")
        return 0
    plan = publication_plan(args.version, api.releases())
    values = {"current_tag": plan.build_tag, "release_tag": plan.release_tag,
              "publication_mode": plan.mode, "should_release": str(plan.should_release).lower(),
              "recover_revision": str(plan.recover_revision).lower(),
              "previous_tag": plan.previous_tag}
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write("".join(f"{key}={value}\n" for key, value in values.items()))
    print(json.dumps(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
