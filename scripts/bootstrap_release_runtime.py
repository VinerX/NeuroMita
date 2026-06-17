from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from release_contract import download_asset, fetch_releases, find_previous_python_full_asset, temp_download_path  # noqa: E402


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
    return parser.parse_args()


def _extract_archive(archive: Path, target: Path) -> None:
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        return
    if suffix == ".7z":
        try:
            import py7zr  # type: ignore
        except Exception as exc:
            raise RuntimeError("py7zr is not installed; cannot extract .7z runtime archive") from exc
        with py7zr.SevenZipFile(archive, mode="r") as zf:
            zf.extractall(path=target)
        return
    raise ValueError(f"Unsupported archive type: {archive.suffix}")


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


def main() -> int:
    _configure_stdio()
    args = _parse_args()
    releases = fetch_releases(args.repo)
    found = find_previous_python_full_asset(
        releases,
        channel=args.channel,
        exclude_tags=args.exclude_tag,
    )
    if found is None:
        print(
            "ERROR: Не найден предыдущий опубликованный full Python release с asset вида "
            "'PythonBuild-vX.Y.Z.zip/.7z'. Сборка не может восстановить libs/ автоматически."
        )
        return 1

    release, asset = found
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
    try:
        _extract_archive(archive_path, extract_root)
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
