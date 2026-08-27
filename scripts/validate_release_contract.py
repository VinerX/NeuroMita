from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from release_contract import (  # noqa: E402
    PYTHON_FULL_KIND,
    PYTHON_PATCH_KIND,
    UNITY_KIND,
    classify_asset_name,
    download_asset,
    explain_release_fallbacks,
    fetch_release,
    fetch_releases,
    temp_download_path,
    validate_archive_contract,
    validate_local_release,
    validate_release_assets,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Проверяет release contract для архивов, которые используются лаунчером "
            "NeuroMita при обновлении."
        )
    )
    parser.add_argument("--tag", required=True, help="Тег релиза, например v1.2.3.")
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help=(
            "Путь до локального asset-архива. Аргумент можно указывать несколько раз. "
            "Подходит для ручной проверки до загрузки в GitHub Release."
        ),
    )
    parser.add_argument(
        "--repo",
        help=(
            "GitHub repo в формате owner/name. Если указан, скрипт проверяет опубликованный "
            "релиз по тегу. Можно комбинировать с --check-archives."
        ),
    )
    parser.add_argument(
        "--check-archives",
        action="store_true",
        help="Для опубликованного релиза скачать подходящие архивы и проверить их содержимое.",
    )
    parser.add_argument(
        "--channel",
        choices=("stable", "beta"),
        default="stable",
        help="Канал релизов для объяснения fallback-логики. По умолчанию stable.",
    )
    return parser.parse_args()


def _print_issue(prefix: str, message: str) -> None:
    print(f"{prefix} {message}")


def _print_result(result) -> None:
    print(f"Проверка release contract для {result.tag}")
    print(f"Статус: {'OK' if result.ok else 'FAIL'}")

    if not result.issues and not result.assets:
        print("Нет данных для проверки.")
        return

    if result.issues:
        print("\nОбщие выводы:")
        for issue in result.issues:
            prefix = {
                "error": "[ERROR]",
                "warning": "[WARN ]",
                "info": "[INFO ]",
            }.get(issue.level, "[NOTE ]")
            _print_issue(prefix, issue.message)

    if result.assets:
        print("\nПроверка asset-архивов:")
        for asset in result.assets:
            print(f"- {asset.name} [{asset.kind}]")
            if asset.inspected_files:
                print(f"  inspected_files={asset.inspected_files}")
            if not asset.issues:
                print("  [OK] Архив прошел проверку.")
                continue
            for issue in asset.issues:
                prefix = {
                    "error": "  [ERROR]",
                    "warning": "  [WARN ]",
                    "info": "  [INFO ]",
                }.get(issue.level, "  [NOTE ]")
                print(f"{prefix} {issue.message}")


def _validate_remote_release(
    repo: str,
    tag: str,
    check_archives: bool,
    channel: str,
):
    raw_release = fetch_release(repo, tag)
    all_releases = fetch_releases(repo)
    current_assets = list(raw_release.get("assets") or [])
    asset_names = [str(asset.get("name") or "") for asset in current_assets]
    result = validate_release_assets(tag, asset_names)

    other_releases = [item for item in all_releases if str(item.get("tag_name") or "") != tag]
    explain_release_fallbacks(result, asset_names, other_releases, channel=channel)

    if check_archives:
        for asset in current_assets:
            asset_name = str(asset.get("name") or "")
            kind = classify_asset_name(asset_name, tag)
            if kind not in (PYTHON_FULL_KIND, PYTHON_PATCH_KIND, UNITY_KIND):
                continue

            url = str(asset.get("browser_download_url") or "")
            if not url:
                continue

            local_path = temp_download_path(asset_name)
            download_asset(url, local_path)
            result.assets.append(validate_archive_contract(local_path, kind))

    return result


def main() -> int:
    args = _parse_args()

    if not args.asset and not args.repo:
        print("Нужно указать либо хотя бы один --asset, либо --repo для проверки опубликованного релиза.")
        return 2

    if args.asset and args.repo:
        print("Одновременно проверять локальные архивы и опубликованный релиз не нужно. Выберите один режим.")
        return 2

    if args.asset:
        asset_paths = [Path(value).expanduser().resolve() for value in args.asset]
        result = validate_local_release(args.tag, asset_paths)
    else:
        result = _validate_remote_release(
            repo=args.repo,
            tag=args.tag,
            check_archives=bool(args.check_archives),
            channel=args.channel,
        )

    _print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
