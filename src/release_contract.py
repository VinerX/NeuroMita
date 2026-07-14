from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import tempfile
import urllib.request
import zipfile
from typing import Iterable, Optional

from utils.release_assets import raw_release_has_launcher_assets


SUPPORTED_ARCHIVE_EXTS = (".zip", ".7z")
PYTHON_FULL_KIND = "python_full"
PYTHON_PATCH_KIND = "python_patch"
UNITY_KIND = "unity"

PYTHON_FULL_REQUIRED_FILES = (
    "NeuroMita.pyz",
    "requirements.txt",
    "run.py",
    "run.bat",
    "Launcher.exe",
    "init.py",
    "init_triton.bat",
    "libs/python/python.exe",
)
PYTHON_FULL_REQUIRED_PREFIXES = (
    "Prompts/",
    "assets/",
    "libs/",
)


@dataclass
class ContractIssue:
    level: str
    message: str


@dataclass
class AssetValidationResult:
    name: str
    kind: str
    issues: list[ContractIssue] = field(default_factory=list)
    inspected_files: int = 0

    @property
    def ok(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def add_error(self, message: str) -> None:
        self.issues.append(ContractIssue("error", message))

    def add_warning(self, message: str) -> None:
        self.issues.append(ContractIssue("warning", message))

    def add_info(self, message: str) -> None:
        self.issues.append(ContractIssue("info", message))


@dataclass
class ReleaseValidationResult:
    tag: str
    issues: list[ContractIssue] = field(default_factory=list)
    assets: list[AssetValidationResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if any(issue.level == "error" for issue in self.issues):
            return False
        return all(asset.ok for asset in self.assets)

    def add_error(self, message: str) -> None:
        self.issues.append(ContractIssue("error", message))

    def add_warning(self, message: str) -> None:
        self.issues.append(ContractIssue("warning", message))

    def add_info(self, message: str) -> None:
        self.issues.append(ContractIssue("info", message))


def _normalize_archive_members(names: Iterable[str]) -> list[str]:
    cleaned = []
    for raw in names:
        text = str(raw or "").replace("\\", "/").strip("/")
        if not text or text.endswith("/"):
            continue
        cleaned.append(text)

    if not cleaned:
        return []

    roots = {item.split("/", 1)[0] for item in cleaned}
    if len(roots) == 1 and all("/" in item for item in cleaned):
        prefix = next(iter(roots)) + "/"
        return [item[len(prefix):] for item in cleaned]
    return cleaned


def _list_archive_files(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            return _normalize_archive_members(info.filename for info in zf.infolist())
    if suffix == ".7z":
        try:
            import py7zr  # type: ignore
        except Exception as exc:
            raise RuntimeError("py7zr is not installed; cannot inspect .7z archives") from exc
        with py7zr.SevenZipFile(path, mode="r") as zf:
            return _normalize_archive_members(zf.getnames())
    raise ValueError(f"Unsupported archive type: {path.suffix}")


def classify_asset_name(name: str, tag: str) -> str:
    escaped_tag = re.escape(tag)
    lowered = str(name or "").lower()
    if re.fullmatch(rf"PythonBuild-{escaped_tag}\.(zip|7z)", name, flags=re.IGNORECASE):
        return PYTHON_FULL_KIND
    if re.fullmatch(rf"PythonBuild-{escaped_tag}-Patch\.(zip|7z)", name, flags=re.IGNORECASE):
        return PYTHON_PATCH_KIND
    if re.fullmatch(rf"UnityBuild-{escaped_tag}\.(zip|7z)", name, flags=re.IGNORECASE):
        return UNITY_KIND
    if "pythonbuild" in lowered:
        return "python_invalid"
    if "unitybuild" in lowered:
        return "unity_invalid"
    return "other"


def classify_asset_name_loose(name: str) -> str:
    lowered = str(name or "").lower()
    if not _asset_name_looks_supported(name):
        return "other"
    if "pythonbuild" in lowered:
        return PYTHON_PATCH_KIND if "patch" in lowered else PYTHON_FULL_KIND
    if "unitybuild" in lowered:
        return UNITY_KIND
    return "other"


def validate_release_assets(tag: str, asset_names: Iterable[str]) -> ReleaseValidationResult:
    result = ReleaseValidationResult(tag=tag)
    python_fulls: list[str] = []
    python_patches: list[str] = []
    unity_assets: list[str] = []

    for asset_name in asset_names:
        kind = classify_asset_name(str(asset_name or ""), tag)
        if kind == PYTHON_FULL_KIND:
            python_fulls.append(str(asset_name))
        elif kind == PYTHON_PATCH_KIND:
            python_patches.append(str(asset_name))
        elif kind == UNITY_KIND:
            unity_assets.append(str(asset_name))
        elif kind == "python_invalid":
            result.add_error(
                f"Asset '{asset_name}' looks like a Python build but does not match "
                f"'PythonBuild-{tag}.zip/.7z' or 'PythonBuild-{tag}-Patch.zip/.7z'."
            )
        elif kind == "unity_invalid":
            result.add_error(
                f"Asset '{asset_name}' looks like a Unity build but does not match "
                f"'UnityBuild-{tag}.zip/.7z'."
            )

    if not python_fulls and not python_patches:
        result.add_error("Release must contain at least one Python build asset for launcher updates.")
    if len(python_fulls) > 1:
        result.add_error(f"Release contains multiple full Python assets: {python_fulls}")
    if len(python_patches) > 1:
        result.add_error(f"Release contains multiple Python patch assets: {python_patches}")
    if len(unity_assets) > 1:
        result.add_error(f"Release contains multiple Unity assets: {unity_assets}")
    if python_patches and not python_fulls:
        result.add_warning(
            "Release contains a Python patch asset without a full Python asset. "
            "Launcher fallback will require an older full Python release to exist."
        )

    return result


def validate_archive_contract(path: Path, kind: str) -> AssetValidationResult:
    result = AssetValidationResult(name=path.name, kind=kind)
    files = _list_archive_files(path)
    result.inspected_files = len(files)

    if not files:
        result.add_error("Archive is empty.")
        return result

    file_set = set(files)

    if kind == PYTHON_FULL_KIND:
        missing_required = []
        for required in PYTHON_FULL_REQUIRED_FILES:
            if required not in file_set:
                missing_required.append(required)
                result.add_error(f"Missing required file: {required}")
        missing_prefixes = []
        for prefix in PYTHON_FULL_REQUIRED_PREFIXES:
            if not any(name.startswith(prefix) for name in files):
                missing_prefixes.append(prefix)
                result.add_error(f"Missing required folder content: {prefix}")
        if missing_required or missing_prefixes:
            preview = ", ".join(files[:10])
            if preview:
                result.add_info(f"Archive preview: {preview}")
    elif kind == PYTHON_PATCH_KIND:
        if not any(
            name == "NeuroMita.pyz"
            or name.startswith("assets/")
            or name.startswith("Prompts/")
            or name.startswith("src/")
            or name.endswith(".py")
            for name in files
        ):
            result.add_warning(
                "Patch archive does not contain obvious runtime payload "
                "(no .pyz, .py, assets/, Prompts/). Verify this is intentional."
            )
    elif kind == UNITY_KIND:
        if not any(name.lower().endswith(".exe") for name in files):
            result.add_error("Unity archive does not contain any .exe file.")
    else:
        result.add_warning(f"Archive kind '{kind}' is not validated structurally.")

    return result


def validate_local_release(tag: str, asset_paths: Iterable[Path]) -> ReleaseValidationResult:
    asset_paths = [Path(path) for path in asset_paths]
    result = validate_release_assets(tag, [path.name for path in asset_paths])

    for path in asset_paths:
        kind = classify_asset_name(path.name, tag)
        asset_result = AssetValidationResult(name=path.name, kind=kind)

        if not path.exists():
            asset_result.add_error(f"Asset file does not exist: {path}")
            result.assets.append(asset_result)
            continue

        if kind in (PYTHON_FULL_KIND, PYTHON_PATCH_KIND, UNITY_KIND):
            asset_result = validate_archive_contract(path, kind)
        elif kind == "python_invalid":
            asset_result.add_error(
                f"Invalid Python asset name. Expected 'PythonBuild-{tag}.zip/.7z' "
                f"or 'PythonBuild-{tag}-Patch.zip/.7z'."
            )
        elif kind == "unity_invalid":
            asset_result.add_error(
                f"Invalid Unity asset name. Expected 'UnityBuild-{tag}.zip/.7z'."
            )
        else:
            asset_result.add_warning("Asset is not part of the launcher release contract and was not checked.")

        result.assets.append(asset_result)

    return result


def _asset_name_looks_supported(name: str) -> bool:
    low = str(name or "").lower()
    return any(low.endswith(ext) for ext in SUPPORTED_ARCHIVE_EXTS)


def _release_assets(raw_release: dict) -> list[dict]:
    return list(raw_release.get("assets") or [])


def _published_sort_key(release: dict) -> str:
    return str(release.get("published_at") or release.get("created_at") or "")


def _iter_release_candidates(
    releases: Iterable[dict],
    channel: str = "stable",
    exclude_tags: Iterable[str] = (),
) -> list[dict]:
    excluded = {str(tag or "").lower() for tag in exclude_tags if str(tag or "").strip()}
    candidates = []
    for release in releases:
        if bool(release.get("draft")):
            continue
        if not raw_release_has_launcher_assets(release):
            continue
        if channel == "stable" and bool(release.get("prerelease")):
            continue
        tag_name = str(release.get("tag_name") or "")
        if tag_name.lower() in excluded:
            continue
        candidates.append(release)
    candidates.sort(key=_published_sort_key, reverse=True)
    return candidates


def find_previous_python_full_asset(
    releases: Iterable[dict],
    channel: str = "stable",
    exclude_tags: Iterable[str] = (),
) -> Optional[tuple[dict, dict]]:
    for release in _iter_release_candidates(releases, channel=channel, exclude_tags=exclude_tags):
        tag_name = str(release.get("tag_name") or "")
        release_name = f"{tag_name} {release.get('name', '')}".lower()
        if "patch" in release_name:
            continue

        for asset in _release_assets(release):
            asset_name = str(asset.get("name") or "")
            strict_kind = classify_asset_name(asset_name, tag_name)
            loose_kind = classify_asset_name_loose(asset_name)
            if strict_kind == PYTHON_FULL_KIND or loose_kind == PYTHON_FULL_KIND:
                return release, asset
    return None


def find_previous_unity_asset(
    releases: Iterable[dict],
    channel: str = "stable",
    exclude_tags: Iterable[str] = (),
) -> Optional[tuple[dict, dict]]:
    for release in _iter_release_candidates(releases, channel=channel, exclude_tags=exclude_tags):
        tag_name = str(release.get("tag_name") or "")
        for asset in _release_assets(release):
            asset_name = str(asset.get("name") or "")
            strict_kind = classify_asset_name(asset_name, tag_name)
            loose_kind = classify_asset_name_loose(asset_name)
            if strict_kind == UNITY_KIND or loose_kind == UNITY_KIND:
                return release, asset
    return None


def explain_release_fallbacks(
    result: ReleaseValidationResult,
    current_release_assets: Iterable[str],
    other_releases: Iterable[dict],
    channel: str = "stable",
) -> None:
    current_assets = [str(name or "") for name in current_release_assets]
    has_python_full = any(classify_asset_name(name, result.tag) == PYTHON_FULL_KIND for name in current_assets)
    has_python_patch = any(classify_asset_name(name, result.tag) == PYTHON_PATCH_KIND for name in current_assets)
    has_unity = any(classify_asset_name(name, result.tag) == UNITY_KIND for name in current_assets)

    if has_python_patch and not has_python_full:
        previous_full = find_previous_python_full_asset(other_releases, channel=channel)
        if previous_full is None:
            result.add_warning(
                "Release contains only a Python patch asset and no older full Python release was found. "
                "Fresh installs or patch fallback may fail."
            )
        else:
            prev_tag = str(previous_full[0].get("tag_name") or "")
            prev_asset = str(previous_full[1].get("name") or "")
            result.add_info(
                f"Python patch fallback is available via older full release {prev_tag} ({prev_asset})."
            )

    if not has_unity:
        previous_unity = find_previous_unity_asset(other_releases, channel=channel)
        if previous_unity is None:
            result.add_warning(
                "Current release has no Unity asset and no older Unity release was found. "
                "Launcher will have nothing to offer for Unity updates."
            )
        else:
            prev_tag = str(previous_unity[0].get("tag_name") or "")
            prev_asset = str(previous_unity[1].get("name") or "")
            result.add_info(
                f"Unity updates remain available from older release {prev_tag} ({prev_asset})."
            )


def fetch_release(repo: str, tag: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NeuroMita-ReleaseContract/1.0",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_releases(repo: str, per_page: int = 100) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/releases?per_page={int(per_page)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NeuroMita-ReleaseContract/1.0",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return list(json.loads(resp.read()) or [])


def download_asset(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "NeuroMita-ReleaseContract/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        destination.write_bytes(resp.read())
    return destination


def temp_download_path(asset_name: str) -> Path:
    return Path(tempfile.gettempdir()) / "neuromita_release_contract" / asset_name
