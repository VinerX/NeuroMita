"""Auto-update from GitHub Releases.

Controlled via features.env or Settings/settings.json:
  AUTO_UPDATE=0|1          — notify only / auto-apply Python part (default 0)
  AUTO_UPDATE_UNITY=0|1    — same for Unity part (default 0)
  UPDATE_CONTOUR           — test|release; persisted in Settings/settings.json
                            fresh installs bootstrap from Settings/distribution.json
                            test -> Atm4x/NeuroMita releases
                            release -> VinerX/NeuroMita releases
  TESTER_CODE              — password for encrypted test archives

Exit code 42 signals launch.py / run.bat to restart after Python update.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from services.update_transaction import (
    DirectoryInstallTransaction,
    UpdateTransactionError,
    atomic_write_json,
    build_install_manifest,
    file_sha256,
    install_manifest_name,
    read_json,
    verify_install_manifest,
    write_install_manifest,
)
from utils.archive_utils import (
    ArchiveCancelled,
    PasswordError,
    extract_archive,
    format_bytes,
    make_logger,
    wipe_dir,
)
from services.update_contour import (
    UpdateTarget,
    infer_initial_contour,
    normalize_contour,
    target_for_contour,
)
from utils.release_assets import (
    Release,
    ReleaseAsset,
    find_latest_python_full,
    find_latest_unity_asset,
    parse_release,
    pick_from_release,
    raw_release_has_python_assets,
)

_USER_AGENT = "NeuroMita-Updater/2.0"
_LOG_PREFIX = "[updater]"


class UpdateCancelled(RuntimeError):
    pass


class UpdateFilesLocked(RuntimeError):
    def __init__(self, paths: list[Path]) -> None:
        self.paths = tuple(paths)
        preview = ", ".join(str(path) for path in self.paths[:3])
        super().__init__(f"Could not apply {len(self.paths)} locked staged file(s): {preview}")


@dataclass(frozen=True, slots=True)
class UpdateResult:
    component: str
    ok: bool
    status: str
    changed: bool = False
    cancelled: bool = False
    restart_required: bool = False
    version: str = ""
    error: str = ""
    archive_sha256: str = ""
    recovered: bool = False

    def __bool__(self) -> bool:
        return bool(self.ok and self.changed)

    def as_dict(self) -> dict:
        return {
            "component": self.component,
            "ok": self.ok,
            "status": self.status,
            "changed": self.changed,
            "cancelled": self.cancelled,
            "restart_required": self.restart_required,
            "version": self.version,
            "error": self.error,
            "archive_sha256": self.archive_sha256,
            "recovered": self.recovered,
        }


def _copy_file_over(
    src: Path,
    dst: Path,
    log,
    *,
    locked_retry_seconds: float = 0.0,
) -> bool:
    """Скопировать src поверх dst, переживая занятый файл. True — если записан."""
    if dst.is_dir():
        shutil.rmtree(dst, ignore_errors=True)
    deadline = time.monotonic() + max(0.0, float(locked_retry_seconds))
    while True:
        try:
            shutil.copy2(src, dst)
            return True
        except OSError as exc:
            is_locked = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32, 33}
            if not is_locked:
                raise
            if time.monotonic() >= deadline:
                log(f"Could not overwrite {dst}: {exc}")
                return False
            time.sleep(0.25)


def _overlay_dir(
    staging: Path,
    base_path: Path,
    log,
    preserve_prompts: bool = False,
    *,
    locked_retry_seconds: float = 0.0,
) -> None:
    """Наложить содержимое staging поверх base_path как diff.

    Пишем только реально изменившиеся файлы и НИКОГДА не удаляем то, чего нет
    в архиве. Благодаря этому переживают апдейт:
      * libs/python — встроенный питон с уже установленными зависимостями
        (иначе run.py заново ставит весь requirements.txt, а управляемый
        перезапуск падает — питона, который крутит цикл, больше нет);
      * .req_hash, Settings, Histories, Logs и прочие локальные файлы.

    Идентичные файлы пропускаются (сравнение по размеру и содержимому), так что
    обновление по сути диффовое: переписывается только то, что изменилось.

    preserve_prompts=True — НЕ перезаписываем уже существующие файлы внутри
    папки Prompts (правки пользователя выигрывают), но новые промпты из релиза
    всё равно добавляются.
    """
    copied = skipped = preserved = 0
    failed: list[Path] = []
    for root, _dirs, files in os.walk(staging):
        rel = Path(root).relative_to(staging)
        dst_root = base_path / rel
        dst_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            if not rel.parts and name == install_manifest_name():
                continue
            src = Path(root) / name
            dst = dst_root / name
            if (
                preserve_prompts
                and rel.parts
                and rel.parts[0].lower() == "prompts"
                and dst.exists()
            ):
                preserved += 1
                continue
            try:
                if dst.exists() and not dst.is_dir() and filecmp.cmp(src, dst, shallow=False):
                    skipped += 1
                    continue
            except OSError:
                pass
            if _copy_file_over(
                src,
                dst,
                log,
                locked_retry_seconds=locked_retry_seconds,
            ):
                copied += 1
            else:
                failed.append(dst)
    if failed:
        raise UpdateFilesLocked(failed)
    msg = f"Overlay update into {base_path}: {copied} written, {skipped} unchanged"
    if preserve_prompts:
        msg += f", {preserved} prompts kept"
    log(msg + ".")


def _full_replace(staging: Path, base_path: Path, log, preserve_prompts: bool = False) -> None:
    """Полная перезапись: стереть base_path (кроме user_data) и перенести релиз.

    preserve_prompts=True — локальная папка Prompts откладывается до wipe и
    возвращается поверх релизной (локальные версии файлов выигрывают, новые
    промпты из релиза остаются).
    """
    prompts_backup: Optional[Path] = None
    local_prompts = base_path / "Prompts"
    if preserve_prompts and local_prompts.is_dir():
        prompts_backup = Path(tempfile.gettempdir()) / "neuromita_prompts_backup"
        if prompts_backup.exists():
            shutil.rmtree(prompts_backup, ignore_errors=True)
        shutil.move(str(local_prompts), str(prompts_backup))
        log("Backed up local Prompts before full replace")

    wipe_dir(base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    for item in staging.iterdir():
        if item.name == install_manifest_name():
            continue
        target = base_path / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                try:
                    target.unlink()
                except OSError:
                    pass
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    if prompts_backup and prompts_backup.exists():
        # Локальные промпты накладываем поверх релизных — локальные версии
        # выигрывают, релизные-новые остаются.
        _overlay_dir(prompts_backup, base_path / "Prompts", log)
        shutil.rmtree(prompts_backup, ignore_errors=True)
        log("Restored local Prompts (local versions kept)")
    log(f"Full replace into {base_path} finished.")


def _verify_python_application(
    staging: Path,
    base_path: Path,
    *,
    preserve_prompts: bool,
) -> None:
    manifest = verify_install_manifest(staging)
    files = manifest.get("files") or {}
    for relative, record in files.items():
        relative_path = Path(str(relative))
        if preserve_prompts and relative_path.parts and relative_path.parts[0].casefold() == "prompts":
            continue
        target = base_path / relative_path
        if not target.is_file():
            raise UpdateTransactionError(f"Applied Python file is missing: {relative}")
        expected_size = int(record.get("size") or 0)
        if target.stat().st_size != expected_size:
            raise UpdateTransactionError(f"Applied Python file size mismatch: {relative}")
        if file_sha256(target) != str(record.get("sha256") or "").lower():
            raise UpdateTransactionError(f"Applied Python file hash mismatch: {relative}")


def _install_full_archive(
    archive: Path,
    base_path: Path,
    password,
    log,
    mode: str = "diff",
    preserve_prompts: bool = False,
    *,
    staging: Path | None = None,
    archive_sha256: str = "",
    logger=None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    on_stage_ready: Optional[Callable[[], None]] = None,
    on_apply_started: Optional[Callable[[], None]] = None,
    locked_retry_seconds: float = 0.0,
    stop_event=None,
) -> None:
    """Установка обновления. Распаковка идёт в чистую временную папку (там
    надёжно срабатывает выравнивание единственного корневого каталога — иначе
    из-за логов в base_path обновление разворачивалось во вложенную папку), а
    дальше — по выбранному режиму:

      mode="diff" (по умолчанию) — наложение поверх существующей папки: пишутся
        только изменившиеся файлы, ничего не удаляется. libs/python с
        зависимостями, .req_hash и локальные файлы переживают апдейт.
      mode="full" — полная перезапись (wipe + перенос релиза), как раньше.

    preserve_prompts — сохранять локальные промпты (см. _overlay_dir/_full_replace).
    """
    staging = staging or (Path(tempfile.gettempdir()) / "neuromita_update_extract")
    marker = staging.parent / f".{staging.name}.ready.json"
    marker_state = read_json(marker)
    reusable = bool(
        staging.is_dir()
        and archive_sha256
        and str(marker_state.get("archive_sha256") or "") == archive_sha256
    )
    if reusable:
        try:
            verify_install_manifest(staging)
        except Exception:
            reusable = False
    if not reusable:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        marker.unlink(missing_ok=True)
        staging.mkdir(parents=True, exist_ok=True)
    try:
        if not reusable:
            extract_archive(
                archive,
                staging,
                password,
                logger=logger,
                on_extract_progress=on_extract_progress,
                stop_event=stop_event,
            )
            manifest = build_install_manifest(
                staging,
                component="python",
                version="",
                archive_sha256=archive_sha256,
            )
            write_install_manifest(staging, manifest)
            atomic_write_json(
                marker,
                {
                    "schema": 1,
                    "archive": str(archive),
                    "archive_sha256": archive_sha256,
                    "created_at": int(time.time()),
                },
            )
        if on_stage_ready is not None:
            on_stage_ready()
        if stop_event is not None and stop_event.is_set():
            raise UpdateCancelled("Installation cancelled")
        if on_apply_started is not None:
            on_apply_started()
        base_path.mkdir(parents=True, exist_ok=True)
        if mode == "full":
            _full_replace(staging, base_path, log, preserve_prompts)
        else:
            _overlay_dir(
                staging,
                base_path,
                log,
                preserve_prompts,
                locked_retry_seconds=locked_retry_seconds,
            )
        _verify_python_application(
            staging,
            base_path,
            preserve_prompts=preserve_prompts,
        )
        log(f"Installed update contents into {base_path}")
    except Exception:
        if not marker.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


# ── Repo / version helpers ────────────────────────────────────────────────────

def _get_update_target() -> UpdateTarget:
    # Lazy imports avoid coupling the updater module to GUI/settings startup.
    # Before SettingsManager is initialized we still honor legacy tester hints
    # once, so the transitional build does not jump testers to VinerX early.
    try:
        from core.app_paths import settings_path
        from managers.settings_manager import SettingsManager

        contour = normalize_contour(SettingsManager.get("UPDATE_CONTOUR", None))
        if contour is None:
            legacy = {
                "UPDATE_REPO": SettingsManager.get("UPDATE_REPO", os.environ.get("UPDATE_REPO", "")),
                "UPDATE_CHANNEL": SettingsManager.get(
                    "UPDATE_CHANNEL", os.environ.get("UPDATE_CHANNEL", "")
                ),
                "TESTER_CODE": SettingsManager.get("TESTER_CODE", os.environ.get("TESTER_CODE", "")),
            }
            contour, _reason = infer_initial_contour(
                legacy,
                config_path=str(settings_path("settings.json")),
            )
    except Exception:
        contour = "release"
    return target_for_contour(contour)


def get_update_target() -> dict[str, str]:
    """Public read-only description used by the settings UI and diagnostics."""
    target = _get_update_target()
    return {
        "contour": target.contour,
        "repo": target.repo,
        "channel": target.channel,
    }


def _get_repo() -> str:
    # Compatibility helper for old internal callers. Repository is no longer
    # independently configurable: UPDATE_CONTOUR is the single source of truth.
    return _get_update_target().repo


def _get_current_version() -> str:
    try:
        from _version import __version__
        return __version__
    except Exception:
        return "0.0.0.0"


def _parse_version(tag: str) -> tuple:
    """Parses 'v2026.04.12.1' → (2026, 4, 12, 1), 'v2026.05.10_Full' → (2026, 5, 10).

    Берём все числовые группы из тега. Раньше split('.') ломался на суффиксах
    вроде '_Full' ('12_Full' не парсился в int и компонент терялся).
    """
    import re
    return tuple(int(n) for n in re.findall(r"\d+", tag or ""))


def _is_newer(remote_tag: str, local_version: str) -> bool:
    return _parse_version(remote_tag) > _parse_version(local_version)


def _find_unity_executable(unity_dir: Path) -> Optional[Path]:
    if not unity_dir.exists() or not unity_dir.is_dir():
        return None

    # Ищем в корне и на один уровень вглубь (например UnityBuild/).
    exe_files = list(unity_dir.glob("*.exe")) + list(unity_dir.glob("*/*.exe"))
    if not exe_files:
        return None

    preferred_names = ("NeuroMita.exe", "NeuroMita-Unity.exe", "Unity.exe")
    lower_map = {path.name.lower(): path for path in exe_files}
    for name in preferred_names:
        found = lower_map.get(name.lower())
        if found is not None:
            return found

    for path in exe_files:
        low = path.name.lower()
        if "neuromita" in low or "unity" in low:
            return path
    return exe_files[0]


# ── GitHub API ────────────────────────────────────────────────────────────────

def _api_get(url: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _fetch_latest_release(repo: str) -> Optional[dict]:
    return _api_get(f"https://api.github.com/repos/{repo}/releases/latest")


def _fetch_releases(repo: str, per_page: int = 20) -> list[dict]:
    data = _api_get(f"https://api.github.com/repos/{repo}/releases?per_page={per_page}")
    return data if isinstance(data, list) else []


def _published_sort_key(release: dict) -> str:
    """Ключ сортировки релизов по дате публикации (свежие — первыми).

    published_at в ISO-8601, поэтому строковое сравнение = хронологическое.
    Падаем на created_at, если publish-даты нет.
    """
    return str(release.get("published_at") or release.get("created_at") or "")


def _select_python_release(repo: str, channel: str) -> Optional[Release]:
    """Return newest release that actually ships a Python build for the channel.

    Судим по РЕАЛЬНОМУ наличию Python-ассета (full/patch), а не по любому
    launcher-ассету: Unity-only релиз (напр. v2026.07.12 с единственным
    UnityBuild) не должен восприниматься как доступное Python-обновление.

    stable: последний опубликованный НЕ-prerelease с Python-сборкой.
    beta:   то же самое, но с учётом prerelease — берём самый свежий по
            published_at. Список из /releases GitHub отдаёт в порядке
            created_at (дата тега), из-за чего более старый по публикации
            релиз может оказаться первым; поэтому пересортировываем сами.
    """
    raws = [
        r for r in _fetch_releases(repo)
        if not r.get("draft") and raw_release_has_python_assets(r)
    ]
    if channel == "stable":
        raws = [r for r in raws if not r.get("prerelease")]
    if not raws:
        return None
    raws.sort(key=_published_sort_key, reverse=True)
    return parse_release(raws[0])


# ── Download ──────────────────────────────────────────────────────────────────

def _expected_sha256(digest: str | None) -> str:
    text = str(digest or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if re.fullmatch(r"[0-9a-f]{64}", text) else ""


def _archive_meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def _validate_cached_archive(
    path: Path,
    *,
    url: str,
    expected_size: int,
    expected_sha256: str,
) -> str:
    if not path.is_file():
        return ""
    actual_size = path.stat().st_size
    if expected_size > 0 and actual_size != expected_size:
        return ""
    meta = read_json(_archive_meta_path(path))
    cached_hash = str(meta.get("sha256") or "").lower()
    actual_hash = file_sha256(path)
    if expected_sha256 and actual_hash != expected_sha256:
        return ""
    if cached_hash and cached_hash != actual_hash:
        _archive_meta_path(path).unlink(missing_ok=True)
    atomic_write_json(
        _archive_meta_path(path),
        {"schema": 1, "url": url, "size": actual_size, "sha256": actual_hash},
    )
    return actual_hash


def _download(
    url: str,
    dest: Path,
    on_progress: Optional[Callable[[int, int], None]] = None,
    retries: int = 3,
    stop_event=None,
    *,
    expected_size: int = 0,
    expected_sha256: str = "",
) -> str:
    """Resume a streamed download and atomically publish a verified archive."""
    import requests

    expected_size = max(0, int(expected_size or 0))
    expected_sha256 = _expected_sha256(expected_sha256)
    cached_hash = _validate_cached_archive(
        dest,
        url=url,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    if cached_hash:
        if on_progress is not None:
            size = dest.stat().st_size
            on_progress(size, expected_size or size)
        return cached_hash

    if dest.exists():
        dest.unlink(missing_ok=True)
        _archive_meta_path(dest).unlink(missing_ok=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial_meta_path = _archive_meta_path(partial)
    partial_meta = read_json(partial_meta_path)
    if partial.exists() and str(partial_meta.get("url") or "") != str(url):
        partial.unlink(missing_ok=True)
        partial_meta_path.unlink(missing_ok=True)

    chunk_size = 1 << 16
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if stop_event is not None and stop_event.is_set():
            raise UpdateCancelled("Download cancelled")
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            partial_meta = read_json(partial_meta_path)
            headers = {"User-Agent": _USER_AGENT}
            if offset > 0:
                headers["Range"] = f"bytes={offset}-"
                validator = str(partial_meta.get("etag") or partial_meta.get("last_modified") or "")
                if validator:
                    headers["If-Range"] = validator

            with requests.get(url, stream=True, timeout=30, headers=headers) as response:
                if response.status_code != 416:
                    response.raise_for_status()
                    resumed = response.status_code == 206 and offset > 0
                    if not resumed:
                        offset = 0
                    content_range = str(response.headers.get("Content-Range") or "")
                    match = re.search(r"/(\d+)$", content_range)
                    response_total = int(match.group(1)) if match else 0
                    if response_total <= 0:
                        content_length = int(response.headers.get("Content-Length") or 0)
                        response_total = content_length + offset if resumed else content_length
                    total = expected_size or response_total
                    atomic_write_json(
                        partial_meta_path,
                        {
                            "schema": 1,
                            "url": url,
                            "expected_size": expected_size,
                            "etag": str(response.headers.get("ETag") or partial_meta.get("etag") or ""),
                            "last_modified": str(
                                response.headers.get("Last-Modified")
                                or partial_meta.get("last_modified")
                                or ""
                            ),
                        },
                    )
                    downloaded = offset
                    last_report = time.monotonic()
                    with partial.open("ab" if resumed else "wb") as output:
                        for piece in response.iter_content(chunk_size=chunk_size):
                            if stop_event is not None and stop_event.is_set():
                                raise UpdateCancelled("Download cancelled")
                            if not piece:
                                continue
                            output.write(piece)
                            downloaded += len(piece)
                            now = time.monotonic()
                            if on_progress is not None and (now - last_report) >= 0.2:
                                on_progress(downloaded, total)
                                last_report = now
                    if on_progress is not None:
                        on_progress(downloaded, total or downloaded)
                elif not (expected_size > 0 and offset == expected_size):
                    response.raise_for_status()

            actual_size = partial.stat().st_size if partial.exists() else 0
            if expected_size > 0 and actual_size != expected_size:
                raise RuntimeError(f"Downloaded size mismatch: {actual_size} != {expected_size}")
            actual_hash = file_sha256(partial)
            if expected_sha256 and actual_hash != expected_sha256:
                partial.unlink(missing_ok=True)
                partial_meta_path.unlink(missing_ok=True)
                raise RuntimeError("Downloaded archive SHA-256 mismatch")
            os.replace(partial, dest)
            partial_meta_path.unlink(missing_ok=True)
            atomic_write_json(
                _archive_meta_path(dest),
                {"schema": 1, "url": url, "size": actual_size, "sha256": actual_hash},
            )
            return actual_hash
        except UpdateCancelled:
            raise
        except Exception as error:
            last_error = error
            if stop_event is not None and stop_event.is_set():
                raise UpdateCancelled("Download cancelled") from error
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"Download failed after {retries} attempts: {last_error}")


# ── Archive extraction ────────────────────────────────────────────────────────



# ── Directory wipe (with user_data backup) ────────────────────────────────────



# ── Asset selection ───────────────────────────────────────────────────────────

def _fetch_full_fallback_asset(repo: str, channel: str) -> Optional[ReleaseAsset]:
    """Walk releases to find the latest full Python asset for patch fallback."""
    releases = [parse_release(r) for r in _fetch_releases(repo)]
    _, full_asset = find_latest_python_full(releases, channel)
    return full_asset


def _fetch_latest_unity_release_asset(
    repo: str, channel: str
) -> tuple[Optional[Release], Optional[ReleaseAsset]]:
    """Find the latest Unity asset, even if newer releases are Python-only."""
    releases = [parse_release(r) for r in _fetch_releases(repo)]
    return find_latest_unity_asset(releases, channel)


def _normalized_install_path(base_path: Path) -> str:
    resolved = str(base_path.resolve(strict=False))
    return os.path.normcase(resolved) if os.name == "nt" else resolved


def _python_installation_id(base_path: Path) -> str:
    return hashlib.sha256(
        _normalized_install_path(base_path).encode("utf-8")
    ).hexdigest()[:16]


def _updater_cache_root() -> Path:
    override = os.environ.get("NEUROMITA_UPDATE_CACHE_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "NeuroMita" / "Updater"
    return Path(tempfile.gettempdir()) / "NeuroMita" / "Updater"


def _python_workspace(base_path: Path) -> Path:
    return _updater_cache_root() / _python_installation_id(base_path) / "python"


def _python_journal_path(base_path: Path) -> Path:
    return _python_workspace(base_path) / "operation.json"


def _python_staging_path(base_path: Path) -> Path:
    return _python_workspace(base_path) / "stage"


def _python_stage_marker(staging: Path) -> Path:
    if staging.name == "stage" and staging.parent.name == "python":
        return staging.parent / ".stage.ready.json"
    return staging.parent / f".{staging.name}.ready.json"


def _python_download_dir(base_path: Path) -> Path:
    return _python_workspace(base_path) / "download"


def _legacy_python_journal_path(base_path: Path) -> Path:
    return base_path.parent / f".{base_path.name}.update-state" / "python" / "operation.json"


def _legacy_python_staging_path(base_path: Path) -> Path:
    return base_path.parent / f".{base_path.name}.python-update-stage"


def _legacy_python_download_dir(base_path: Path) -> Path:
    return base_path.parent / f".{base_path.name}.update-download"


def _python_state_matches_target(state: dict, base_path: Path) -> bool:
    target = str(state.get("target") or "")
    if not target:
        return False
    return _normalized_install_path(Path(target)) == _normalized_install_path(base_path)


def _python_state_is_resumable(state: dict) -> bool:
    if not state:
        return False
    phase = str(state.get("phase") or "")
    if phase in {"", "completed", "cancelled"}:
        return False
    if phase == "failed":
        return "Could not apply" in str(state.get("error") or "")
    return True


def _python_active_journal_path(base_path: Path) -> Path:
    current = _python_journal_path(base_path)
    if current.is_file():
        return current
    legacy = _legacy_python_journal_path(base_path)
    legacy_state = read_json(legacy)
    if _python_state_is_resumable(legacy_state) and _python_state_matches_target(
        legacy_state, base_path
    ):
        return legacy
    return current


def _set_python_operation_phase(
    base_path: Path,
    phase: str,
    *,
    journal_path: Optional[Path] = None,
    **changes,
) -> dict:
    journal = journal_path or _python_journal_path(base_path)
    state = read_json(journal)
    state.update(changes)
    state.update(
        {
            "schema": 1,
            "component": "python",
            "target": str(base_path.resolve()),
            "phase": str(phase),
            "updated_at": int(time.time()),
        }
    )
    state.setdefault("created_at", int(time.time()))
    atomic_write_json(journal, state)
    return state


def _begin_python_operation(
    base_path: Path,
    *,
    version: str,
    asset: ReleaseAsset,
    mode: str,
    preserve_prompts: bool,
    is_patch: bool,
) -> dict:
    journal = _python_journal_path(base_path)
    previous = read_json(journal)
    same_operation = (
        str(previous.get("version") or "") == str(version)
        and str(previous.get("archive_url") or "") == str(asset.url)
    )
    created_at = int(previous.get("created_at") or time.time()) if same_operation else int(time.time())
    state = {
        "schema": 1,
        "component": "python",
        "target": str(base_path.resolve()),
        "phase": "created",
        "authorized": True,
        "version": str(version),
        "archive_name": str(asset.name),
        "archive_url": str(asset.url),
        "archive_size": int(asset.size or 0),
        "archive_digest": str(asset.digest or ""),
        "archive_path": str(_python_download_dir(base_path) / asset.name),
        "staging": str(_python_staging_path(base_path)),
        "mode": str(mode),
        "preserve_prompts": bool(preserve_prompts),
        "is_patch": bool(is_patch),
        "created_at": created_at,
        "updated_at": int(time.time()),
    }
    if same_operation:
        for key in ("archive_sha256", "error"):
            if previous.get(key):
                state[key] = previous[key]
    atomic_write_json(journal, state)
    return state


def _python_stage_is_reusable(staging: Path, archive_sha256: str) -> bool:
    marker = read_json(_python_stage_marker(staging))
    if not staging.is_dir() or not archive_sha256:
        return False
    if str(marker.get("archive_sha256") or "") != str(archive_sha256):
        return False
    try:
        verify_install_manifest(staging)
        return True
    except Exception:
        return False


def _cleanup_python_reserve(
    *,
    journal: Path,
    archive: Optional[Path],
    staging: Path,
    logger=None,
) -> None:
    """Best-effort cleanup after a terminally completed Python update."""
    log = make_logger(logger, _LOG_PREFIX)
    files = [_python_stage_marker(staging)]
    if archive is not None:
        files.extend(
            [
                archive,
                _archive_meta_path(archive),
                archive.with_suffix(archive.suffix + ".part"),
                _archive_meta_path(archive.with_suffix(archive.suffix + ".part")),
            ]
        )
    cleanup_failed = False

    try:
        shutil.rmtree(staging, ignore_errors=True)
    except OSError as error:
        cleanup_failed = True
        log(f"Could not remove updater staging directory {staging}: {error}", "warning")
    if staging.exists():
        cleanup_failed = True

    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            cleanup_failed = True
            log(f"Could not remove updater artifact {path}: {error}", "warning")
        if path.exists():
            cleanup_failed = True

    if not cleanup_failed:
        try:
            journal.unlink(missing_ok=True)
        except OSError as error:
            cleanup_failed = True
            log(f"Could not remove updater journal {journal}: {error}", "warning")
        if journal.exists():
            cleanup_failed = True
    else:
        log(
            "Keeping the completed updater journal because cleanup left artifacts behind.",
            "warning",
        )

    cleanup_dirs = []
    if archive is not None:
        cleanup_dirs.append(archive.parent)
    cleanup_dirs.append(journal.parent)
    if staging.parent == journal.parent:
        cleanup_dirs.extend([journal.parent.parent, journal.parent.parent.parent])
    else:
        cleanup_dirs.append(journal.parent.parent)
    seen: set[Path] = set()
    for directory in cleanup_dirs:
        directory = directory.resolve(strict=False)
        if directory in seen:
            continue
        seen.add(directory)
        try:
            directory.rmdir()
        except OSError:
            pass


def _python_state_archive_path_for_journal(
    base_path: Path,
    state: dict,
    journal: Path,
) -> Optional[Path]:
    value = str(state.get("archive_path") or "")
    if value:
        return Path(value)
    name = str(state.get("archive_name") or "")
    if not name:
        return None
    download_dir = (
        _legacy_python_download_dir(base_path)
        if journal == _legacy_python_journal_path(base_path)
        else _python_download_dir(base_path)
    )
    return download_dir / name


def _python_state_staging_path_for_journal(
    base_path: Path,
    state: dict,
    journal: Path,
) -> Path:
    value = str(state.get("staging") or "")
    if value:
        return Path(value)
    if journal == _legacy_python_journal_path(base_path):
        return _legacy_python_staging_path(base_path)
    return _python_staging_path(base_path)


def _cleanup_completed_python_operation(
    base_path: Path,
    journal: Path,
    state: dict,
    logger=None,
) -> None:
    _cleanup_python_reserve(
        journal=journal,
        archive=_python_state_archive_path_for_journal(base_path, state, journal),
        staging=_python_state_staging_path_for_journal(base_path, state, journal),
        logger=logger,
    )


def _cleanup_terminal_legacy_python_reserve(base_path: Path, logger=None) -> None:
    journal = _legacy_python_journal_path(base_path)
    state = read_json(journal)
    if not state or not _python_state_matches_target(state, base_path):
        return
    if str(state.get("phase") or "") != "completed":
        return
    cleanup_state = dict(state)
    cleanup_state.setdefault("staging", str(_legacy_python_staging_path(base_path)))
    if not cleanup_state.get("archive_path") and cleanup_state.get("archive_name"):
        cleanup_state["archive_path"] = str(
            _legacy_python_download_dir(base_path) / str(cleanup_state["archive_name"])
        )
    _cleanup_completed_python_operation(base_path, journal, cleanup_state, logger=logger)


# Максимум detached-перезапусков подряд для одной залоченной установки. Обычная
# перезапись залоченного Launcher.exe снимается за один detached-хэндофф; если же
# занят сам работающий python.exe, его нельзя переписать из своего же процесса —
# сколько ни перезапускай, файл останется locked. Без ограничителя bootstrap
# спавнил бы detached-процесс бесконечно.
_MAX_LOCKED_RESTART_ATTEMPTS = 3


def note_locked_restart_attempt(
    base_dir: Optional[str] = None,
    *,
    limit: int = _MAX_LOCKED_RESTART_ATTEMPTS,
) -> tuple[int, bool]:
    """Засчитать попытку detached-перезапуска для залоченной установки.

    Возвращает ``(номер_попытки, исчерпано)``. При исчерпании лимита переводит
    операцию в терминальный ``failed`` с не-«locked» текстом ошибки — тогда
    ``resume_pending_python_update`` перестаёт сигналить ``waiting_for_restart``,
    и цикл detached-перезапусков останавливается (вместо вечного спавна).
    """
    base_path = Path(base_dir) if base_dir else Path(sys.argv[0]).parent
    journal = _python_active_journal_path(base_path)
    state = read_json(journal)
    attempts = int(state.get("restart_attempts") or 0) + 1
    limit = max(1, int(limit))
    exhausted = attempts >= limit
    if exhausted:
        _set_python_operation_phase(
            base_path,
            "failed",
            journal_path=journal,
            restart_attempts=attempts,
            error=(
                "Update aborted: launcher files stayed locked after "
                f"{attempts} restart attempts; a manual reinstall is required."
            ),
        )
    else:
        _set_python_operation_phase(
            base_path,
            str(state.get("phase") or "waiting_for_restart"),
            journal_path=journal,
            restart_attempts=attempts,
        )
    return attempts, exhausted


# ── Public API ────────────────────────────────────────────────────────────────

def get_python_update_info(
    base_dir: Optional[str] = None,
    channel: str = "stable",
) -> dict:
    """Return current/latest Python update information without installing."""
    target = _get_update_target()
    repo = target.repo
    local_version = _get_current_version()
    channel = target.channel

    release = _select_python_release(repo, channel)
    if release is None:
        return {
            "ok": False,
            "component": "python",
            "current_version": local_version,
            "error": "Could not reach GitHub to check for updates",
        }

    remote_tag = str(release.tag or "")
    available = bool(remote_tag) and _is_newer(remote_tag, local_version)
    picked = pick_from_release(release)
    python_asset = picked.python_patch or picked.python_full
    return {
        "ok": True,
        "component": "python",
        "repo": repo,
        "channel": channel,
        "current_version": local_version,
        "latest_version": remote_tag,
        "available": available,
        "prerelease": bool(release.prerelease),
        "name": str(release.name or ""),
        "body": str(release.body or ""),
        "published_at": str(release.published_at or ""),
        "html_url": str(release.html_url or ""),
        "asset_name": python_asset.name if python_asset is not None else "",
        "asset_size": int(python_asset.size or 0) if python_asset is not None else 0,
        "asset_digest": str(python_asset.digest or "") if python_asset is not None else "",
    }


def get_unity_update_info(
    base_dir: Optional[str] = None,
    unity_dir: Optional[str] = None,
    channel: str = "stable",
) -> dict:
    """Return current/latest Unity update information without installing."""
    target = _get_update_target()
    repo = target.repo
    channel = target.channel

    if base_dir is None:
        base_dir = str(Path(sys.argv[0]).parent)
    base_path = Path(base_dir)
    unity_path = Path(unity_dir) if unity_dir else base_path / "NeuroMita-Unity"
    version_file = unity_path / "_version.txt"
    install_complete = _find_unity_executable(unity_path) is not None
    local_version = (
        version_file.read_text(encoding="utf-8").strip()
        if version_file.exists()
        else "0.0.0.0"
    )

    release, unity_asset = _fetch_latest_unity_release_asset(repo, channel)
    if release is None:
        return {
            "ok": False,
            "component": "unity",
            "current_version": local_version,
            "error": "Could not find a Unity release asset to check for updates",
        }

    remote_tag = str(release.tag or "")
    available = bool(remote_tag) and (_is_newer(remote_tag, local_version) or not install_complete)
    return {
        "ok": True,
        "component": "unity",
        "repo": repo,
        "channel": channel,
        "current_version": local_version,
        "latest_version": remote_tag,
        "available": available,
        "install_complete": install_complete,
        "prerelease": bool(release.prerelease),
        "name": str(release.name or ""),
        "body": str(release.body or ""),
        "published_at": str(release.published_at or ""),
        "html_url": str(release.html_url or ""),
        "asset_name": getattr(unity_asset, "name", "") if unity_asset is not None else "",
        "asset_size": int(getattr(unity_asset, "size", 0) or 0) if unity_asset is not None else 0,
        "asset_digest": str(getattr(unity_asset, "digest", "") or "") if unity_asset is not None else "",
    }

def check_for_updates(
    base_dir: Optional[str] = None,
    logger=None,
    channel: str = "stable",
    tester_code: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    on_stage: Optional[Callable[[str, int, int, bool], None]] = None,
    auto_update: Optional[bool] = None,
    restart_on_success: bool = True,
    update_mode: str = "diff",
    preserve_prompts: bool = False,
    stop_event=None,
) -> UpdateResult:
    """Check and optionally install the Python component update.

    The result distinguishes availability, completed installation, cancellation,
    missing credentials, and a real failure. UI callers keep
    ``restart_on_success`` false so they can offer a controlled restart.
    """
    log = make_logger(logger, _LOG_PREFIX)

    target = _get_update_target()
    repo = target.repo
    local_version = _get_current_version()
    if auto_update is None:
        auto_update = os.environ.get("AUTO_UPDATE", "0") == "1"
    channel = target.channel
    tester_code = tester_code or os.environ.get("TESTER_CODE") or None
    update_mode = (update_mode or os.environ.get("UPDATE_MODE", "diff")).lower()
    if update_mode not in ("diff", "full"):
        update_mode = "diff"
    preserve_prompts = preserve_prompts or os.environ.get("UPDATE_PRESERVE_PROMPTS", "0") == "1"

    log(f"Update contour: {target.contour} ({repo}, {channel})")
    log(f"Checking for updates ({repo}, channel={channel}, mode={update_mode}) ...")

    release = _select_python_release(repo, channel)
    if release is None:
        message = "Could not reach GitHub to check for updates"
        log(message, "warning")
        return UpdateResult(component="python", ok=False, status="check_failed", error=message)

    remote_tag = release.tag
    if not remote_tag:
        return UpdateResult(component="python", ok=False, status="check_failed", error="Release tag is empty")

    if not _is_newer(remote_tag, local_version):
        log(f"Up to date: {local_version}")
        return UpdateResult(component="python", ok=True, status="current", version=local_version)

    log(f"New version available: {remote_tag} (current: {local_version})", "notify")

    if not auto_update:
        log(f"Python update {remote_tag} is available; waiting for user selection.")
        return UpdateResult(component="python", ok=True, status="available", version=remote_tag)

    # _select_python_release only returns releases with a Python archive.
    picked = pick_from_release(release)
    is_patch = False
    python_asset = None

    if picked.python_patch is not None:
        python_asset = picked.python_patch
        is_patch = True
    elif picked.python_full is not None:
        python_asset = picked.python_full

    if python_asset is None:
        # Plain fallback: first .zip that не является Unity-сборкой (иначе можно
        # ошибочно скачать 300+ МБ UnityBuild как Python-обновление).
        python_asset = next(
            (
                a for a in release.assets
                if a.name.lower().endswith(".zip") and "unitybuild" not in a.name.lower()
            ),
            None,
        )
        if python_asset is None:
            message = "No suitable Python asset found in release"
            log(message, "warning")
            return UpdateResult(component="python", ok=False, status="check_failed", error=message)

    if base_dir is None:
        base_dir = str(Path(sys.argv[0]).parent)
    base_path = Path(base_dir)
    legacy_state = read_json(_legacy_python_journal_path(base_path))
    if _python_state_is_resumable(legacy_state) and _python_state_matches_target(
        legacy_state, base_path
    ):
        pending_phase = str(legacy_state.get("phase") or "waiting_for_restart")
        return UpdateResult(
            component="python",
            ok=False,
            status=(
                pending_phase
                if pending_phase in {"waiting_for_credentials", "waiting_for_restart"}
                else "pending"
            ),
            restart_required=pending_phase == "waiting_for_restart",
            version=str(legacy_state.get("version") or ""),
            error=str(legacy_state.get("error") or "A previous update is pending recovery"),
        )
    _cleanup_terminal_legacy_python_reserve(base_path, logger=logger)
    dl_dir = _python_download_dir(base_path)
    dl_dir.mkdir(parents=True, exist_ok=True)
    temp_archive = dl_dir / python_asset.name

    staging = _python_staging_path(base_path)
    active_archive = temp_archive
    archive_hash = ""
    _begin_python_operation(
        base_path,
        version=remote_tag,
        asset=python_asset,
        mode="diff" if is_patch else update_mode,
        preserve_prompts=preserve_prompts,
        is_patch=is_patch,
    )

    def stage_ready() -> None:
        _set_python_operation_phase(
            base_path,
            "stage_ready",
            archive_sha256=archive_hash,
            archive_path=str(active_archive),
        )

    def apply_started() -> None:
        _set_python_operation_phase(
            base_path,
            "applying",
            archive_sha256=archive_hash,
            archive_path=str(active_archive),
        )
        _emit_stage(on_stage, "Applying update", 3, 4, False)

    try:
        _set_python_operation_phase(base_path, "downloading")
        _emit_stage(on_stage, "Downloading", 1, 4, True)
        archive_hash = _download(
            python_asset.url,
            temp_archive,
            on_progress=on_progress,
            stop_event=stop_event,
            expected_size=int(python_asset.size or 0),
            expected_sha256=_expected_sha256(python_asset.digest),
        )
        _set_python_operation_phase(
            base_path,
            "archive_verified",
            archive_sha256=archive_hash,
            archive_path=str(temp_archive),
        )
        _emit_stage(on_stage, "Extracting", 2, 4, True)
        log(f"Applying update to {base_path} ...")
        if is_patch:
            try:
                _set_python_operation_phase(base_path, "extracting")
                _install_full_archive(
                    temp_archive, base_path, tester_code, log,
                    mode="diff", preserve_prompts=preserve_prompts,
                    staging=staging,
                    archive_sha256=archive_hash,
                    logger=logger,
                    on_extract_progress=on_extract_progress,
                    on_stage_ready=stage_ready,
                    on_apply_started=apply_started,
                    stop_event=stop_event,
                )
            except (PasswordError, ArchiveCancelled, UpdateCancelled):
                raise
            except Exception as e:
                log(f"Patch failed ({e}), falling back to full update ...", "warning")
                temp_archive.unlink(missing_ok=True)
                _archive_meta_path(temp_archive).unlink(missing_ok=True)
                full_asset = _fetch_full_fallback_asset(repo, channel)
                if full_asset is None:
                    raise RuntimeError("No full release found for fallback")
                full_archive = dl_dir / full_asset.name
                active_archive = full_archive
                _begin_python_operation(
                    base_path,
                    version=remote_tag,
                    asset=full_asset,
                    mode=update_mode,
                    preserve_prompts=preserve_prompts,
                    is_patch=False,
                )
                _set_python_operation_phase(base_path, "downloading")
                log(f"Downloading full release {full_asset.name} ...")
                archive_hash = _download(
                    full_asset.url,
                    full_archive,
                    on_progress=on_progress,
                    stop_event=stop_event,
                    expected_size=int(full_asset.size or 0),
                    expected_sha256=_expected_sha256(full_asset.digest),
                )
                _set_python_operation_phase(
                    base_path,
                    "archive_verified",
                    archive_sha256=archive_hash,
                    archive_path=str(full_archive),
                )
                _set_python_operation_phase(base_path, "extracting")
                _install_full_archive(
                    full_archive, base_path, tester_code, log,
                    mode=update_mode, preserve_prompts=preserve_prompts,
                    staging=staging,
                    archive_sha256=archive_hash,
                    logger=logger,
                    on_extract_progress=on_extract_progress,
                    on_stage_ready=stage_ready,
                    on_apply_started=apply_started,
                    stop_event=stop_event,
                )
        else:
            _set_python_operation_phase(base_path, "extracting")
            _install_full_archive(
                temp_archive, base_path, tester_code, log,
                mode=update_mode, preserve_prompts=preserve_prompts,
                staging=staging,
                archive_sha256=archive_hash,
                logger=logger,
                on_extract_progress=on_extract_progress,
                on_stage_ready=stage_ready,
                on_apply_started=apply_started,
                stop_event=stop_event,
            )
        _set_python_operation_phase(
            base_path,
            "completed",
            completed_at=int(time.time()),
            archive_sha256=archive_hash,
        )
        try:
            _cleanup_python_reserve(
                journal=_python_journal_path(base_path),
                archive=active_archive,
                staging=staging,
                logger=logger,
            )
        except Exception as cleanup_error:
            log(
                f"Update installed successfully, but updater cache cleanup failed: {cleanup_error}",
                "warning",
            )
        _emit_stage(on_stage, "Completed", 4, 4, False)

        if restart_on_success:
            log(f"Update {remote_tag} installed successfully. Restarting ...", "success")
            sys.exit(42)

        log(f"Update {remote_tag} installed successfully. Restart required.", "success")
        return UpdateResult(
            component="python",
            ok=True,
            status="installed",
            changed=True,
            restart_required=True,
            version=remote_tag,
            archive_sha256=archive_hash,
        )

    except UpdateFilesLocked as error:
        _set_python_operation_phase(base_path, "waiting_for_restart", error=str(error))
        log(
            "Running launcher files will be replaced during the controlled restart.",
            "warning",
        )
        if restart_on_success:
            raise SystemExit(42)
        return UpdateResult(
            component="python",
            ok=True,
            status="waiting_for_restart",
            changed=True,
            restart_required=True,
            version=remote_tag,
            error=str(error),
            archive_sha256=archive_hash,
        )
    except (UpdateCancelled, ArchiveCancelled) as error:
        _set_python_operation_phase(base_path, "cancelled", error=str(error))
        log("Python update cancelled; downloaded data was kept for resume.", "warning")
        return UpdateResult(
            component="python",
            ok=False,
            status="cancelled",
            cancelled=True,
            version=remote_tag,
            error=str(error),
            archive_sha256=archive_hash,
        )
    except PasswordError as error:
        _set_python_operation_phase(base_path, "waiting_for_credentials", error=str(error))
        log("Archive is password-protected. Set TESTER_CODE in settings to unlock.", "error")
        log(f"Archive kept for retry: {active_archive}")
        return UpdateResult(
            component="python",
            ok=False,
            status="waiting_for_credentials",
            version=remote_tag,
            error=str(error),
            archive_sha256=archive_hash,
        )
    except Exception as error:
        _set_python_operation_phase(base_path, "failed", error=str(error))
        log(f"Update failed: {error}", "error")
        return UpdateResult(
            component="python",
            ok=False,
            status="failed",
            version=remote_tag,
            error=str(error),
            archive_sha256=archive_hash,
        )


def resume_pending_python_update(
    *,
    base_dir: Optional[str] = None,
    tester_code: Optional[str] = None,
    logger=None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    on_stage: Optional[Callable[[str, int, int, bool], None]] = None,
    stop_event=None,
) -> UpdateResult:
    """Finish a previously authorized Python install from its durable reserve."""
    base_path = Path(base_dir) if base_dir else Path(sys.argv[0]).parent
    journal = _python_active_journal_path(base_path)
    state = read_json(journal)
    phase = str(state.get("phase") or "")
    if phase == "completed":
        _cleanup_completed_python_operation(base_path, journal, state, logger=logger)
        _cleanup_terminal_legacy_python_reserve(base_path, logger=logger)
        return UpdateResult(component="python", ok=True, status="no_pending_operation")
    if not state:
        _cleanup_terminal_legacy_python_reserve(base_path, logger=logger)
        return UpdateResult(component="python", ok=True, status="no_pending_operation")
    failed_from_locked_file = phase == "failed" and "Could not apply" in str(
        state.get("error") or ""
    )
    if phase in {"", "cancelled"} or (
        phase == "failed" and not failed_from_locked_file
    ):
        return UpdateResult(component="python", ok=True, status="no_pending_operation")
    if (
        (phase == "waiting_for_restart" or failed_from_locked_file)
        and os.environ.get("NEUROMITA_DETACHED_RESTART") != "1"
    ):
        return UpdateResult(
            component="python",
            ok=False,
            status="waiting_for_restart",
            restart_required=True,
            version=str(state.get("version") or ""),
            error=str(state.get("error") or "Running launcher files are locked"),
            archive_sha256=str(state.get("archive_sha256") or ""),
            recovered=True,
        )

    effective_tester_code = tester_code or os.environ.get("TESTER_CODE") or None
    if phase == "waiting_for_credentials" and not effective_tester_code:
        return UpdateResult(
            component="python",
            ok=False,
            status="waiting_for_credentials",
            version=str(state.get("version") or ""),
            error=str(state.get("error") or "Tester code is required"),
        )

    asset = ReleaseAsset(
        name=str(state.get("archive_name") or ""),
        url=str(state.get("archive_url") or ""),
        size=int(state.get("archive_size") or 0),
        digest=str(state.get("archive_digest") or ""),
    )
    version = str(state.get("version") or "")
    if not asset.name or not asset.url or not version:
        return UpdateResult(
            component="python",
            ok=False,
            status="failed",
            error="Pending Python update journal is incomplete",
        )

    archive = Path(
        str(state.get("archive_path") or (_python_download_dir(base_path) / asset.name))
    )
    staging = Path(str(state.get("staging") or _python_staging_path(base_path)))
    archive_hash = str(state.get("archive_sha256") or "")
    log = make_logger(logger, _LOG_PREFIX)

    def stage_ready() -> None:
        _set_python_operation_phase(
            base_path,
            "stage_ready",
            journal_path=journal,
            archive_sha256=archive_hash,
            archive_path=str(archive),
        )

    def apply_started() -> None:
        _set_python_operation_phase(
            base_path,
            "applying",
            journal_path=journal,
            archive_sha256=archive_hash,
            archive_path=str(archive),
        )
        _emit_stage(on_stage, "Applying update", 3, 4, False)

    try:
        if not _python_stage_is_reusable(staging, archive_hash):
            _set_python_operation_phase(base_path, "downloading", journal_path=journal)
            _emit_stage(on_stage, "Downloading", 1, 4, True)
            archive_hash = _download(
                asset.url,
                archive,
                on_progress=on_progress,
                stop_event=stop_event,
                expected_size=int(asset.size or 0),
                expected_sha256=_expected_sha256(asset.digest),
            )
            _set_python_operation_phase(
                base_path,
                "archive_verified",
                journal_path=journal,
                archive_sha256=archive_hash,
                archive_path=str(archive),
            )
        _set_python_operation_phase(base_path, "extracting", journal_path=journal)
        _emit_stage(on_stage, "Extracting", 2, 4, True)
        _install_full_archive(
            archive,
            base_path,
            effective_tester_code,
            log,
            mode=str(state.get("mode") or "diff"),
            preserve_prompts=bool(state.get("preserve_prompts", False)),
            staging=staging,
            archive_sha256=archive_hash,
            logger=logger,
            on_extract_progress=on_extract_progress,
            on_stage_ready=stage_ready,
            on_apply_started=apply_started,
            locked_retry_seconds=5.0,
            stop_event=stop_event,
        )
        _set_python_operation_phase(
            base_path,
            "completed",
            journal_path=journal,
            completed_at=int(time.time()),
            archive_sha256=archive_hash,
        )
        try:
            _cleanup_python_reserve(
                journal=journal,
                archive=archive,
                staging=staging,
                logger=logger,
            )
        except Exception as cleanup_error:
            log(
                f"Update installed successfully, but updater cache cleanup failed: {cleanup_error}",
                "warning",
            )
        _emit_stage(on_stage, "Completed", 4, 4, False)
        log(f"Recovered Python update {version}; restart required.", "success")
        return UpdateResult(
            component="python",
            ok=True,
            status="installed",
            changed=True,
            restart_required=True,
            version=version,
            archive_sha256=archive_hash,
            recovered=True,
        )
    except UpdateFilesLocked as error:
        _set_python_operation_phase(
            base_path,
            "waiting_for_restart",
            journal_path=journal,
            error=str(error),
        )
        return UpdateResult(
            component="python",
            ok=False,
            status="waiting_for_restart",
            restart_required=True,
            version=version,
            error=str(error),
            archive_sha256=archive_hash,
            recovered=True,
        )
    except (UpdateCancelled, ArchiveCancelled) as error:
        _set_python_operation_phase(
            base_path,
            "cancelled",
            journal_path=journal,
            error=str(error),
        )
        return UpdateResult(
            component="python",
            ok=False,
            status="cancelled",
            cancelled=True,
            version=version,
            error=str(error),
            archive_sha256=archive_hash,
            recovered=True,
        )
    except PasswordError as error:
        _set_python_operation_phase(
            base_path,
            "waiting_for_credentials",
            journal_path=journal,
            error=str(error),
        )
        return UpdateResult(
            component="python",
            ok=False,
            status="waiting_for_credentials",
            version=version,
            error=str(error),
            archive_sha256=archive_hash,
            recovered=True,
        )
    except Exception as error:
        _set_python_operation_phase(
            base_path,
            "failed",
            journal_path=journal,
            error=str(error),
        )
        log(f"Python update recovery failed: {error}", "error")
        return UpdateResult(
            component="python",
            ok=False,
            status="failed",
            version=version,
            error=str(error),
            archive_sha256=archive_hash,
            recovered=True,
        )


def _emit_stage(
    callback: Optional[Callable[[str, int, int, bool], None]],
    name: str,
    index: int,
    total: int,
    can_cancel: bool,
) -> None:
    if callback is not None:
        callback(str(name), int(index), int(total), bool(can_cancel))


def _copy_preserved_unity_data(source: Path, stage: Path) -> None:
    user_data = source / "user_data"
    if not user_data.is_dir():
        return
    destination = stage / "user_data"
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(user_data, destination)


def _unity_transaction(base_path: Path, unity_path: Path, log) -> DirectoryInstallTransaction:
    return DirectoryInstallTransaction(
        component="unity",
        target=unity_path,
        state_root=base_path / "_update_state",
        logger=log,
    )


def _verify_unity_install(path: Path, on_progress=None) -> dict:
    manifest = verify_install_manifest(path, on_progress=on_progress)
    if _find_unity_executable(path) is None:
        raise UpdateTransactionError("Verified Unity staging has no executable")
    version_file = path / "_version.txt"
    expected_version = str(manifest.get("version") or "")
    actual_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if not expected_version or actual_version != expected_version:
        raise UpdateTransactionError("Installed Unity version marker does not match the manifest")
    return manifest


def _install_unity_asset(
    *,
    base_path: Path,
    unity_path: Path,
    version: str,
    asset: ReleaseAsset,
    tester_code: Optional[str],
    logger,
    on_progress: Optional[Callable[[int, int], None]],
    on_extract_progress: Optional[Callable[[int, int], None]],
    on_verify_progress: Optional[Callable[[int, int], None]],
    on_stage: Optional[Callable[[str, int, int, bool], None]],
    stop_event,
    recovered: bool = False,
) -> UpdateResult:
    log = make_logger(logger, _LOG_PREFIX)
    archive = base_path / "_update_download" / asset.name
    transaction = _unity_transaction(base_path, unity_path, log)
    transaction.begin(
        {
            "version": str(version),
            "archive_url": str(asset.url),
            "archive_name": str(asset.name),
            "archive_path": str(archive),
            "archive_size": int(asset.size or 0),
            "archive_digest": str(asset.digest or ""),
        }
    )

    try:
        initial_phase = transaction.phase
        if initial_phase in {"commit_prepared", "target_backed_up", "activated"}:
            _emit_stage(on_stage, "Recovering installation", 6, 6, False)
            if transaction.recover_commit(
                lambda target: _verify_unity_install(target, on_verify_progress)
            ):
                archive.unlink(missing_ok=True)
                _archive_meta_path(archive).unlink(missing_ok=True)
                log(f"Unity update {version} recovered successfully.", "success")
                return UpdateResult(
                    component="unity",
                    ok=True,
                    status="installed",
                    changed=True,
                    version=version,
                    recovered=True,
                )

        stage_ready = initial_phase in {"stage_ready", "commit_prepared"} and transaction.paths.stage.is_dir()
        archive_hash = str(transaction.state.get("archive_sha256") or "")
        if not stage_ready:
            cached_hash = _validate_cached_archive(
                archive,
                url=asset.url,
                expected_size=int(asset.size or 0),
                expected_sha256=_expected_sha256(asset.digest),
            )
            if not cached_hash:
                transaction.set_phase("downloading")
                _emit_stage(on_stage, "Downloading", 1, 6, True)
                log(f"Downloading Unity {asset.name} to {archive} ...")
                archive_hash = _download(
                    asset.url,
                    archive,
                    on_progress=on_progress,
                    stop_event=stop_event,
                    expected_size=int(asset.size or 0),
                    expected_sha256=_expected_sha256(asset.digest),
                )
            else:
                archive_hash = cached_hash
                log(f"Verified cached archive: {archive} ({format_bytes(archive.stat().st_size)})")
            transaction.set_phase("archive_verified", archive_sha256=archive_hash)

        if stop_event is not None and stop_event.is_set():
            raise UpdateCancelled("Installation cancelled")

        if stage_ready:
            try:
                _emit_stage(on_stage, "Verifying staged files", 4, 6, False)
                _verify_unity_install(transaction.paths.stage, on_verify_progress)
            except Exception:
                stage_ready = False

        if not stage_ready:
            transaction.set_phase("extracting")
            stage = transaction.reset_stage()
            _emit_stage(on_stage, "Extracting", 2, 6, True)
            extract_archive(
                archive,
                stage,
                tester_code,
                logger=logger,
                on_extract_progress=on_extract_progress,
                stop_event=stop_event,
            )
            if stop_event is not None and stop_event.is_set():
                raise UpdateCancelled("Installation cancelled")
            if _find_unity_executable(stage) is None:
                raise UpdateTransactionError("Unity archive does not contain an executable")
            _copy_preserved_unity_data(unity_path, stage)
            (stage / "_version.txt").write_text(version, encoding="utf-8")

            transaction.set_phase("verifying_stage")
            _emit_stage(on_stage, "Verifying staged files", 3, 6, False)
            manifest = build_install_manifest(
                stage,
                component="unity",
                version=version,
                archive_sha256=archive_hash,
                on_progress=on_verify_progress,
                excluded_roots={"user_data"},
            )
            write_install_manifest(stage, manifest)
            transaction.mark_stage_ready(tree_sha256=str(manifest.get("tree_sha256") or ""))

        _emit_stage(on_stage, "Applying update", 5, 6, False)
        transaction.commit(lambda target: _verify_unity_install(target, on_verify_progress))
        _emit_stage(on_stage, "Completed", 6, 6, False)
        archive.unlink(missing_ok=True)
        _archive_meta_path(archive).unlink(missing_ok=True)
        log(f"Unity update {version} installed and verified successfully.", "success")
        return UpdateResult(
            component="unity",
            ok=True,
            status="installed",
            changed=True,
            version=version,
            archive_sha256=archive_hash,
            recovered=recovered,
        )
    except (UpdateCancelled, ArchiveCancelled) as error:
        transaction.set_phase("cancelled", error=str(error))
        log("Unity installation cancelled; downloaded data was kept for resume.", "warning")
        return UpdateResult(
            component="unity",
            ok=False,
            status="cancelled",
            cancelled=True,
            version=version,
            error=str(error),
            archive_sha256=str(transaction.state.get("archive_sha256") or ""),
        )
    except PasswordError as error:
        transaction.set_phase("waiting_for_credentials", error=str(error))
        log("Unity archive is password-protected. Set TESTER_CODE in settings.", "error")
        log(f"Archive kept for retry: {archive}")
        return UpdateResult(
            component="unity",
            ok=False,
            status="waiting_for_credentials",
            version=version,
            error=str(error),
            archive_sha256=str(transaction.state.get("archive_sha256") or ""),
        )
    except Exception as error:
        if transaction.phase != "rolled_back":
            transaction.set_phase("failed", error=str(error))
        log(f"Unity update failed: {error}", "error")
        return UpdateResult(
            component="unity",
            ok=False,
            status="failed",
            version=version,
            error=str(error),
            archive_sha256=str(transaction.state.get("archive_sha256") or ""),
        )


def resume_pending_unity_update(
    *,
    base_dir: Optional[str] = None,
    unity_dir: Optional[str] = None,
    tester_code: Optional[str] = None,
    logger=None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    on_verify_progress: Optional[Callable[[int, int], None]] = None,
    on_stage: Optional[Callable[[str, int, int, bool], None]] = None,
    stop_event=None,
) -> UpdateResult:
    base_path = Path(base_dir) if base_dir else Path(sys.argv[0]).parent
    journal_state = read_json(base_path / "_update_state" / "unity" / "operation.json")
    recorded_target = str(journal_state.get("target") or "")
    target = (
        Path(recorded_target)
        if recorded_target
        else Path(unity_dir) if unity_dir else base_path / "NeuroMita-Unity"
    )
    transaction = _unity_transaction(base_path, target, make_logger(logger, _LOG_PREFIX))
    state = transaction.state
    phase = str(state.get("phase") or "")
    if not state or phase in {"", "completed", "rolled_back", "cancelled", "failed"}:
        return UpdateResult(component="unity", ok=True, status="no_pending_operation")
    effective_tester_code = tester_code or os.environ.get("TESTER_CODE") or None
    if phase == "waiting_for_credentials" and not effective_tester_code:
        return UpdateResult(
            component="unity",
            ok=False,
            status="waiting_for_credentials",
            version=str(state.get("version") or ""),
            error=str(state.get("error") or "Tester code is required"),
        )
    asset = ReleaseAsset(
        name=str(state.get("archive_name") or ""),
        url=str(state.get("archive_url") or ""),
        size=int(state.get("archive_size") or 0),
        digest=str(state.get("archive_digest") or ""),
    )
    if not asset.name or not asset.url or not state.get("version"):
        return UpdateResult(
            component="unity",
            ok=False,
            status="failed",
            error="Pending Unity update journal is incomplete",
        )
    return _install_unity_asset(
        base_path=base_path,
        unity_path=target,
        version=str(state.get("version") or ""),
        asset=asset,
        tester_code=effective_tester_code,
        logger=logger,
        on_progress=on_progress,
        on_extract_progress=on_extract_progress,
        on_verify_progress=on_verify_progress,
        on_stage=on_stage,
        stop_event=stop_event,
        recovered=True,
    )


def check_for_unity_updates(
    base_dir: Optional[str] = None,
    logger=None,
    unity_dir: Optional[str] = None,
    channel: str = "stable",
    tester_code: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    on_verify_progress: Optional[Callable[[int, int], None]] = None,
    on_stage: Optional[Callable[[str, int, int, bool], None]] = None,
    auto_update: Optional[bool] = None,
    stop_event=None,
) -> UpdateResult:
    log = make_logger(logger, _LOG_PREFIX)
    target = _get_update_target()
    repo = target.repo
    if auto_update is None:
        auto_update = os.environ.get("AUTO_UPDATE_UNITY", "0") == "1"
    channel = target.channel
    tester_code = tester_code or os.environ.get("TESTER_CODE") or None
    base_path = Path(base_dir) if base_dir else Path(sys.argv[0]).parent
    unity_path = Path(unity_dir) if unity_dir else base_path / "NeuroMita-Unity"
    version_file = unity_path / "_version.txt"
    install_complete = _find_unity_executable(unity_path) is not None
    local_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "0.0.0.0"

    log(f"Update contour: {target.contour} ({repo}, {channel})")
    log(f"Checking Unity updates ({repo}, channel={channel}) ...")
    release, unity_asset = _fetch_latest_unity_release_asset(repo, channel)
    if release is None or unity_asset is None:
        message = "Could not find a Unity release asset to check for updates"
        log(message, "warning")
        return UpdateResult(component="unity", ok=False, status="check_failed", error=message)
    remote_tag = str(release.tag or "")
    if not remote_tag:
        return UpdateResult(component="unity", ok=False, status="check_failed", error="Release tag is empty")
    if not _is_newer(remote_tag, local_version) and install_complete:
        log(f"Unity up to date: {local_version}")
        return UpdateResult(component="unity", ok=True, status="current", version=local_version)
    if not auto_update:
        log(f"Unity update {remote_tag} is available; waiting for user selection.")
        return UpdateResult(component="unity", ok=True, status="available", version=remote_tag)

    return _install_unity_asset(
        base_path=base_path,
        unity_path=unity_path,
        version=remote_tag,
        asset=unity_asset,
        tester_code=tester_code,
        logger=logger,
        on_progress=on_progress,
        on_extract_progress=on_extract_progress,
        on_verify_progress=on_verify_progress,
        on_stage=on_stage,
        stop_event=stop_event,
    )
