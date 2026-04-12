"""
Проверка и применение обновлений с GitHub Releases.

Управляется через features.env:
  AUTO_UPDATE=0    — только уведомление о новой версии (по умолчанию)
  AUTO_UPDATE=1    — автоматическое скачивание и распаковка
  UPDATE_REPO=Atm4x/NeuroMita  — репозиторий с релизами
"""

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def _get_repo() -> str:
    return os.environ.get("UPDATE_REPO", "Atm4x/NeuroMita")


def _get_current_version() -> str:
    try:
        from _version import __version__
        return __version__
    except Exception:
        return "0.0.0.0"


def _fetch_latest_release(repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "NeuroMita-Updater/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return None
    except Exception:
        return None


def _parse_version(tag: str) -> tuple:
    """Преобразует строку вида 'v2026.04.12.1' → (2026, 4, 12, 1)."""
    clean = tag.lstrip("v")
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            pass
    return tuple(parts)


def _is_newer(remote_tag: str, local_version: str) -> bool:
    return _parse_version(remote_tag) > _parse_version(local_version)


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "NeuroMita-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def _extract_zip(zip_path: Path, target: Path) -> None:
    """
    Распаковывает zip в target.
    Если внутри один корневой каталог (ci_build/) — прозрачно убирает его.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        # Определяем общий префикс (вложенную папку) если она есть
        first_parts = {n.split("/")[0] for n in names if n}
        if len(first_parts) == 1:
            prefix = first_parts.pop() + "/"
            for member in z.infolist():
                if not member.filename.startswith(prefix):
                    continue
                relative = member.filename[len(prefix):]
                if not relative:
                    continue
                dest_path = target / relative
                if member.filename.endswith("/"):
                    dest_path.mkdir(parents=True, exist_ok=True)
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(dest_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            z.extractall(target)


def check_for_updates(base_dir: str | None = None, logger=None) -> None:
    """
    Проверяет наличие обновлений. Вызывать при старте приложения.

    Args:
        base_dir: корневая папка игры (куда распаковывать обновление)
        logger:   объект логгера с методами info/warning/success/notify
    """
    def log(msg: str, level: str = "info") -> None:
        if logger:
            getattr(logger, level, logger.info)(msg)
        else:
            print(f"[updater] {msg}")

    repo = _get_repo()
    local_version = _get_current_version()
    auto_update = os.environ.get("AUTO_UPDATE", "0") == "1"

    log(f"Проверка обновлений ({repo}) ...")

    release = _fetch_latest_release(repo)
    if release is None:
        log("Не удалось подключиться к GitHub для проверки обновлений", "warning")
        return

    remote_tag = release.get("tag_name", "")
    if not remote_tag:
        return

    if not _is_newer(remote_tag, local_version):
        log(f"Версия актуальна: {local_version}")
        return

    log(f"Доступна новая версия: {remote_tag} (текущая: {local_version})", "notify")

    if not auto_update:
        log(
            "Автообновление выключено (AUTO_UPDATE=0). "
            "Включите AUTO_UPDATE=1 в features.env для автоматической установки."
        )
        return

    # Ищем zip-файл среди assets релиза
    assets = release.get("assets", [])
    zip_asset = next((a for a in assets if a["name"].endswith(".zip")), None)
    if not zip_asset:
        log("ZIP-архив в релизе не найден", "warning")
        return

    download_url = zip_asset["browser_download_url"]
    asset_name = zip_asset["name"]
    log(f"Скачиваю {asset_name} ...")

    if base_dir is None:
        # Внутри .pyz: sys.argv[0] — путь к .pyz, его родитель — папка игры
        base_dir = str(Path(sys.argv[0]).parent)

    base_path = Path(base_dir)
    temp_zip = base_path / "_update_download.zip"

    try:
        _download(download_url, temp_zip)
        log(f"Скачано. Применяю обновление в {base_path} ...")
        _extract_zip(temp_zip, base_path)
        temp_zip.unlink(missing_ok=True)
        log(
            f"Обновление {remote_tag} успешно установлено. "
            "Перезапустите программу.",
            "success",
        )
    except Exception as e:
        log(f"Ошибка при обновлении: {e}", "error")
        temp_zip.unlink(missing_ok=True)
