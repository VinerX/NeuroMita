from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from release_contract import (  # noqa: E402
    classify_asset_name_loose,
    download_asset,
    fetch_releases,
    find_previous_python_full_asset,
    temp_download_path,
)
from utils.archive_utils import PasswordError, extract_archive  # noqa: E402


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Восстанавливает папку libs/ для релизной сборки из предыдущего полного Python-релиза. "
            "Нужно для CI: libs не хранится в git, но full-архив обязан её содержать."
        )
    )
    parser.add_argument("--repo", required=True, help="GitHub repo в формате owner/name.")
    parser.add_argument("--target", default="libs", help="Куда положить извлечённую папку libs.")
    parser.add_argument(
        "--channel",
        choices=("stable", "beta"),
        default="stable",
        help="Канал релизов, по умолчанию stable.",
    )
    parser.add_argument(
        "--exclude-tag",
        action="append",
        default=[],
        help="Теги, которые нельзя использовать как источник bootstrap-runtime.",
    )
    parser.add_argument(
        "--prefer-tag",
        default=None,
        help="Явный full-release tag для временного pinned baseline runtime.",
    )
    parser.add_argument(
        "--before-tag",
        default=None,
        help="Использовать только runtime-релизы со строго меньшей версией тега.",
    )
    parser.add_argument(
        "--tester-code",
        default=None,
        help="Пароль для зашифрованных release-архивов. Если не задан, берётся из TESTER_CODE/BOOTSTRAP_TESTER_CODE.",
    )
    return parser.parse_args()


def _resolve_tester_code(cli_value: str | None) -> str | None:
    if cli_value:
        return cli_value
    for env_name in ("BOOTSTRAP_TESTER_CODE", "TESTER_CODE"):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def _release_version(tag: str) -> tuple[int, ...] | None:
    """Возвращает числовую часть тега vYYYY.MM.DD[.N][_Full]."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:_[A-Za-z]+)?", str(tag or "").strip())
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _releases_before_tag(releases: list[dict], before_tag: str | None) -> list[dict]:
    if not before_tag:
        return releases
    limit = _release_version(before_tag)
    if limit is None:
        raise ValueError(f"Invalid --before-tag version: {before_tag}")
    return [
        release
        for release in releases
        if (version := _release_version(str(release.get("tag_name") or ""))) is not None and version < limit
    ]


def _collapse_single_root(root: Path) -> Path:
    current = root
    while True:
        children = [child for child in current.iterdir()]
        dirs = [child for child in children if child.is_dir()]
        files = [child for child in children if child.is_file()]
        if files or len(dirs) != 1:
            return current
        current = dirs[0]


def _preview_entries(path: Path, limit: int = 10) -> str:
    try:
        entries = sorted(child.name for child in path.iterdir())
    except FileNotFoundError:
        return "<missing>"
    if not entries:
        return "<empty>"
    preview = ", ".join(entries[:limit])
    if len(entries) > limit:
        preview += ", ..."
    return preview


def _find_release_by_tag(releases: list[dict], tag: str | None) -> dict | None:
    wanted = str(tag or "").strip().lower()
    if not wanted:
        return None
    for release in releases:
        if str(release.get("tag_name") or "").strip().lower() == wanted:
            return release
    return None


def _pick_full_python_asset(release: dict) -> dict | None:
    archive_candidates: list[dict] = []
    for asset in list(release.get("assets") or []):
        name = str(asset.get("name") or "")
        low = name.lower()
        if classify_asset_name_loose(name) == "python_full":
            return asset
        if low.endswith((".zip", ".7z")) and "unity" not in low and "patch" not in low:
            archive_candidates.append(asset)
    if len(archive_candidates) == 1:
        return archive_candidates[0]
    if archive_candidates:
        archive_candidates.sort(key=lambda item: int(item.get("size") or 0), reverse=True)
        return archive_candidates[0]
    return None


def main() -> int:
    _configure_stdio()
    args = _parse_args()
    releases = fetch_releases(args.repo)
    try:
        releases = _releases_before_tag(releases, args.before_tag)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    release = asset = None
    preferred_release = _find_release_by_tag(releases, args.prefer_tag)
    if preferred_release is not None:
        asset = _pick_full_python_asset(preferred_release)
        if asset is None:
            print(
                f"ERROR: Preferred release {args.prefer_tag} exists, "
                "but it has no full Python asset named PythonBuild-*.zip/.7z."
            )
            return 1
        release = preferred_release
        print(f"Using pinned runtime baseline tag: {args.prefer_tag}")
    else:
        found = find_previous_python_full_asset(
            releases,
            channel=args.channel,
            exclude_tags=args.exclude_tag,
        )
        if found is not None:
            release, asset = found

    if release is None or asset is None:
        print(
            "ERROR: Не найден предыдущий опубликованный full Python release с asset вида "
            "'PythonBuild-vX.Y.Z.zip/.7z'. Сборка не может восстановить libs/ автоматически."
        )
        return 1

    source_tag = str(release.get("tag_name") or "")
    source_name = str(asset.get("name") or "")
    download_url = str(asset.get("browser_download_url") or "")
    if not download_url:
        print(f"ERROR: У asset {source_name} нет browser_download_url.")
        return 1

    archive_path = temp_download_path(source_name)
    download_asset(download_url, archive_path)
    print(f"Bootstrap runtime source: {source_tag} / {source_name}")
    print(f"Downloaded archive: {archive_path}")

    extract_root = Path(tempfile.mkdtemp(prefix="neuromita_runtime_bootstrap_"))
    tester_code = _resolve_tester_code(args.tester_code)
    try:
        try:
            extract_archive(archive_path, extract_root, password=tester_code)
        except PasswordError:
            print(
                "ERROR: Runtime baseline archive is encrypted, but no valid tester code was provided. "
                "Pass --tester-code or set BOOTSTRAP_TESTER_CODE/TESTER_CODE in the environment."
            )
            return 1

        normalized_root = _collapse_single_root(extract_root)
        libs_dir = normalized_root / "libs"
        if not libs_dir.is_dir():
            print(
                "ERROR: В исходном full-архиве не найдена папка libs/. "
                f"Root preview: {_preview_entries(normalized_root)}"
            )
            return 1

        target = Path(args.target).resolve()
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(libs_dir, target)

        python_exe = target / "python" / "python.exe"
        if not python_exe.exists():
            print(
                "ERROR: Runtime bootstrap завершился без libs/python/python.exe. "
                f"Target preview: {_preview_entries(target)}"
            )
            return 1

        print(f"Restored runtime into: {target}")
        print(f"Runtime check passed: {python_exe}")
        return 0
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
