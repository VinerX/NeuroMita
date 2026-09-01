from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.release_catalog import build_release_manifest


def _request_json(url: str, token: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "NeuroMita-release-manifest",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API returned HTTP {error.code} for {url}: {body}") from error


def fetch_all_releases(api_base: str, repository: str, token: str) -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        payload = _request_json(
            f"{api_base.rstrip('/')}/repos/{repository}/releases?{query}",
            token,
        )
        if not isinstance(payload, list):
            raise RuntimeError("GitHub releases response is not an array")
        releases.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return releases
        page += 1


def fetch_latest_tag(api_base: str, repository: str, token: str) -> str:
    url = f"{api_base.rstrip('/')}/repos/{repository}/releases/latest"
    try:
        payload = _request_json(url, token)
    except RuntimeError as error:
        if "HTTP 404" in str(error):
            return ""
        raise
    return str(payload.get("tag_name") or "") if isinstance(payload, dict) else ""


def _write_github_output(path: str, *, stable_tag: str, release_count: int) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output:
        output.write(f"stable_tag={stable_tag}\n")
        output.write(f"release_count={release_count}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the public NeuroMita release catalog")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-base", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=Path("releases-manifest.json"))
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()

    repository = str(args.repository or "").strip()
    if not repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")

    releases = fetch_all_releases(args.api_base, repository, args.token)
    stable_tag = fetch_latest_tag(args.api_base, repository, args.token)
    manifest = build_release_manifest(repository, releases, stable_tag=stable_tag)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    _write_github_output(
        args.github_output,
        stable_tag=str(manifest["channels"]["stable"]),
        release_count=len(manifest["releases"]),
    )
    print(
        f"Built {args.output}: {len(manifest['releases'])} releases, "
        f"stable={manifest['channels']['stable'] or '<none>'}, "
        f"beta={manifest['channels']['beta'] or '<none>'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
