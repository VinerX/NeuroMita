"""Auto-update from GitHub Releases.

Controlled via features.env or Settings/settings.json:
  AUTO_UPDATE=0|1          — notify only / auto-apply Python part (default 0)
  AUTO_UPDATE_UNITY=0|1    — same for Unity part (default 0)
  UPDATE_REPO              — release repository (default Atm4x/NeuroMita)
  UPDATE_CHANNEL           — stable|beta (default stable)
  TESTER_CODE              — password for encrypted test archives

Exit code 42 signals launch.py / run.bat to restart after Python update.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

_USER_AGENT = "NeuroMita-Updater/2.0"
_LOG_PREFIX = "[updater]"


# ── Repo / version helpers ────────────────────────────────────────────────────

def _get_repo() -> str:
    return os.environ.get("UPDATE_REPO", "Atm4x/NeuroMita")


def _get_current_version() -> str:
    try:
        from _version import __version__
        return __version__
    except Exception:
        return "0.0.0.0"


def _parse_version(tag: str) -> tuple:
    """Parses 'v2026.04.12.1' → (2026, 4, 12, 1)."""
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


def _find_unity_executable(unity_dir: Path) -> Optional[Path]:
    if not unity_dir.exists() or not unity_dir.is_dir():
        return None

    exe_files = list(unity_dir.glob("*.exe"))
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


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(max(0, size))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0


def _make_logger(logger):
    def log(msg: str, level: str = "info") -> None:
        if logger:
            getattr(logger, level, logger.info)(msg)
        else:
            print(f"{_LOG_PREFIX} {msg}")

    return log


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


def _select_release(repo: str, channel: str) -> Optional[dict]:
    """Return newest release suitable for the given channel."""
    if channel == "beta":
        releases = _fetch_releases(repo)
        return releases[0] if releases else None
    return _fetch_latest_release(repo)


# ── Download ──────────────────────────────────────────────────────────────────

def _download(
    url: str,
    dest: Path,
    on_progress: Optional[Callable[[int, int], None]] = None,
    retries: int = 3,
) -> None:
    """Stream url to dest (atomic replace via .part file).

    on_progress(downloaded_bytes, total_bytes) is called periodically.
    """
    import requests  # already in requirements.txt

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    chunk_size = 1 << 16

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(
                url, stream=True, timeout=30, headers={"User-Agent": _USER_AGENT}
            ) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                downloaded = 0
                last_report = time.monotonic()
                with open(tmp, "wb") as f:
                    for piece in r.iter_content(chunk_size=chunk_size):
                        if not piece:
                            continue
                        f.write(piece)
                        downloaded += len(piece)
                        now = time.monotonic()
                        if on_progress and (now - last_report) >= 0.2:
                            on_progress(downloaded, total)
                            last_report = now
                if on_progress:
                    on_progress(downloaded, total or downloaded)
            tmp.replace(dest)
            return
        except Exception as e:
            last_err = e
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"Download failed after {retries} attempts: {last_err}")


# ── Archive extraction ────────────────────────────────────────────────────────

class _PasswordError(Exception):
    """Archive is encrypted and the provided password is missing or wrong."""


def _extract_zip(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
) -> None:
    pwd = password.encode("utf-8") if password else None
    log = _make_logger(logger)
    try:
        with zipfile.ZipFile(archive) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            total_members = len(members)
            total_size = sum(max(0, int(m.file_size or 0)) for m in members)
            extracted_size = 0
            last_log = time.monotonic()

            log(
                f"ZIP extraction started: {archive.name}, files={total_members}, "
                f"uncompressed={_format_bytes(total_size)}"
            )
            try:
                for index, member in enumerate(z.infolist(), start=1):
                    out_path = target / member.filename
                    if member.is_dir():
                        out_path.mkdir(parents=True, exist_ok=True)
                        continue

                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member, pwd=pwd) as src, open(out_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)

                    extracted_size += max(0, int(member.file_size or 0))
                    now = time.monotonic()
                    if index == 1 or index == len(z.infolist()) or (now - last_log) >= 5.0:
                        pct = int(extracted_size * 100 / total_size) if total_size > 0 else 0
                        log(
                            f"ZIP extraction progress: {index}/{len(z.infolist())} entries, "
                            f"{_format_bytes(extracted_size)} / {_format_bytes(total_size)} ({pct}%)"
                        )
                        last_log = now
            except RuntimeError as e:
                msg = str(e).lower()
                if "password" in msg or "encrypted" in msg:
                    raise _PasswordError(str(e)) from e
                raise
            log(f"ZIP extraction finished: {archive.name}")
    except zipfile.BadZipFile as e:
        raise ValueError(f"Bad zip: {archive.name}") from e


def _extract_7z(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
) -> None:
    try:
        import py7zr
    except ImportError as e:
        raise RuntimeError("py7zr is not installed; cannot open .7z archives") from e

    log = _make_logger(logger)
    stop_event = threading.Event()

    def heartbeat():
        started = time.monotonic()
        while not stop_event.wait(10.0):
            elapsed = int(time.monotonic() - started)
            log(f"7z extraction still running: {archive.name}, elapsed={elapsed}s")

    try:
        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()
        with py7zr.SevenZipFile(archive, mode="r", password=password or None) as z:
            if z.needs_password() and not password:
                raise _PasswordError("Archive is password-protected")
            try:
                entries = z.list()
                file_entries = [e for e in entries if not getattr(e, "is_directory", False)]
                total_size = sum(max(0, int(getattr(e, "uncompressed", 0) or 0)) for e in file_entries)
                log(
                    f"7z extraction started: {archive.name}, files={len(file_entries)}, "
                    f"uncompressed={_format_bytes(total_size)}"
                )
            except Exception:
                log(f"7z extraction started: {archive.name}")
            z.extractall(path=target)
        log(f"7z extraction finished: {archive.name}")
    except py7zr.exceptions.PasswordRequired as e:
        raise _PasswordError(str(e)) from e
    except py7zr.exceptions.Bad7zFile as e:
        if password:
            raise _PasswordError("Wrong tester code") from e
        raise ValueError(f"Bad 7z: {archive.name}") from e
    finally:
        stop_event.set()


def _extract_archive(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
) -> None:
    """Dispatch extraction to zip or 7z handler, then flatten single root."""
    target.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        _extract_zip(archive, target, password, logger=logger)
    elif suffix == ".7z":
        _extract_7z(archive, target, password, logger=logger)
    else:
        raise ValueError(f"Unsupported archive type: {archive.name}")
    _flatten_single_root(target, logger=logger)


def _flatten_single_root(dest: Path, logger=None) -> None:
    """If archive extracted into a single root folder, move its contents up."""
    log = _make_logger(logger)
    try:
        children = list(dest.iterdir())
    except OSError:
        return
    if len(children) != 1 or not children[0].is_dir():
        return
    only = children[0]
    log(f"Flattening extracted root folder: {only.name}")
    tmp = dest.parent / f".{dest.name}.unwrap"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.move(str(only), str(tmp))
    try:
        for item in tmp.iterdir():
            tgt = dest / item.name
            if tgt.exists():
                if tgt.is_dir():
                    shutil.rmtree(tgt, ignore_errors=True)
                else:
                    try:
                        tgt.unlink()
                    except OSError:
                        pass
            shutil.move(str(item), str(tgt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"Flattening finished for: {dest}")


# ── Directory wipe (with user_data backup) ────────────────────────────────────

def _wipe_dir(target: Path, logger=None) -> None:
    """Remove everything in target, backing up user_data/ if present."""
    log = _make_logger(logger)
    if not target.exists():
        log(f"Unity target directory does not exist yet, creating: {target}")
        target.mkdir(parents=True, exist_ok=True)
        return

    user_data = target / "user_data"
    backup: Optional[Path] = None
    if user_data.exists():
        backup = target.parent / f".{target.name}.user_data.bak"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        log(f"Preserving user_data backup: {backup}")
        shutil.move(str(user_data), str(backup))

    children = list(target.iterdir())
    total_children = len(children)
    log(f"Cleaning Unity target directory: {target} ({total_children} top-level entries)")
    for index, child in enumerate(children, start=1):
        if index == 1 or index == total_children or index % 10 == 0:
            log(f"Removing {index}/{total_children}: {child.name}")
        if child.is_dir():
            try:
                shutil.rmtree(child)
            except Exception as exc:
                log(f"Failed to remove directory {child}: {exc}", "warning")
        else:
            try:
                child.unlink()
            except OSError as exc:
                log(f"Failed to remove file {child}: {exc}", "warning")

    if backup and backup.exists():
        log(f"Restoring preserved user_data to {user_data}")
        shutil.move(str(backup), str(user_data))
    log(f"Unity target directory cleanup finished: {target}")


# ── Asset selection ───────────────────────────────────────────────────────────

def _pick_assets(release: dict):
    """Parse a GitHub release dict using release_assets module."""
    try:
        from utils.release_assets import parse_release, pick_from_release
        return pick_from_release(parse_release(release))
    except Exception:
        return None


def _fetch_full_fallback_asset(repo: str, channel: str):
    """Walk releases to find the latest full Python asset for patch fallback."""
    try:
        from utils.release_assets import parse_release, find_latest_python_full
        releases = [parse_release(r) for r in _fetch_releases(repo)]
        _, full_asset = find_latest_python_full(releases, channel)
        return full_asset
    except Exception:
        pass

    # Plain fallback: first .zip in the first non-patch release
    for r in _fetch_releases(repo):
        if channel == "stable" and r.get("prerelease"):
            continue
        hay = f"{r.get('tag_name','')} {r.get('name','')}".lower()
        if "patch" in hay:
            continue
        a = next((x for x in r.get("assets", []) if x.get("name","").endswith(".zip")), None)
        if a:
            # Return as a simple namespace to match ReleaseAsset interface
            class _A:
                url = a["browser_download_url"]
                name = a["name"]
            return _A()
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_python_update_info(
    base_dir: Optional[str] = None,
    channel: str = "stable",
) -> dict:
    """Return current/latest Python update information without installing."""
    repo = _get_repo()
    local_version = _get_current_version()
    channel = (channel or os.environ.get("UPDATE_CHANNEL", "stable")).lower()

    release = _select_release(repo, channel)
    if release is None:
        return {
            "ok": False,
            "component": "python",
            "current_version": local_version,
            "error": "Could not reach GitHub to check for updates",
        }

    remote_tag = str(release.get("tag_name", "") or "")
    available = bool(remote_tag) and _is_newer(remote_tag, local_version)
    return {
        "ok": True,
        "component": "python",
        "repo": repo,
        "channel": channel,
        "current_version": local_version,
        "latest_version": remote_tag,
        "available": available,
        "prerelease": bool(release.get("prerelease", False)),
        "name": str(release.get("name", "") or ""),
        "body": str(release.get("body", "") or ""),
        "published_at": str(release.get("published_at", "") or ""),
        "html_url": str(release.get("html_url", "") or ""),
    }


def get_unity_update_info(
    base_dir: Optional[str] = None,
    unity_dir: Optional[str] = None,
    channel: str = "stable",
) -> dict:
    """Return current/latest Unity update information without installing."""
    repo = _get_repo()
    channel = (channel or os.environ.get("UPDATE_CHANNEL", "stable")).lower()

    if base_dir is None:
        base_dir = str(Path(sys.argv[0]).parent)
    base_path = Path(base_dir)
    unity_path = Path(unity_dir) if unity_dir else base_path.parent / "NeuroMita-Unity"
    version_file = unity_path / "_version.txt"
    install_complete = _find_unity_executable(unity_path) is not None
    local_version = (
        version_file.read_text(encoding="utf-8").strip()
        if version_file.exists()
        else "0.0.0.0"
    )

    release = _select_release(repo, channel)
    if release is None:
        return {
            "ok": False,
            "component": "unity",
            "current_version": local_version,
            "error": "Could not reach GitHub to check for Unity updates",
        }

    remote_tag = str(release.get("tag_name", "") or "")
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
        "prerelease": bool(release.get("prerelease", False)),
        "name": str(release.get("name", "") or ""),
        "body": str(release.get("body", "") or ""),
        "published_at": str(release.get("published_at", "") or ""),
        "html_url": str(release.get("html_url", "") or ""),
    }

def check_for_updates(
    base_dir: Optional[str] = None,
    logger=None,
    channel: str = "stable",
    tester_code: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    auto_update: Optional[bool] = None,
) -> None:
    """Check for Python-part updates. Apply automatically if AUTO_UPDATE=1.

    Args:
        base_dir:    Game root directory (where NeuroMita.pyz lives).
        logger:      Logger with info/warning/success/notify methods.
        channel:     "stable" or "beta".
        tester_code: Password for encrypted test archives.
        on_progress: Callback(downloaded_bytes, total_bytes) for UI progress.
        auto_update: Force auto-apply behavior instead of reading env/config only.
    """
    log = _make_logger(logger)

    repo = _get_repo()
    local_version = _get_current_version()
    if auto_update is None:
        auto_update = os.environ.get("AUTO_UPDATE", "0") == "1"
    channel = (channel or os.environ.get("UPDATE_CHANNEL", "stable")).lower()
    tester_code = tester_code or os.environ.get("TESTER_CODE") or None

    log(f"Checking for updates ({repo}, channel={channel}) ...")

    release = _select_release(repo, channel)
    if release is None:
        log("Could not reach GitHub to check for updates", "warning")
        return

    remote_tag = release.get("tag_name", "")
    if not remote_tag:
        return

    if not _is_newer(remote_tag, local_version):
        log(f"Up to date: {local_version}")
        return

    log(f"New version available: {remote_tag} (current: {local_version})", "notify")

    if not auto_update:
        log("Auto-update is disabled (AUTO_UPDATE=0). Set AUTO_UPDATE=1 in features.env to enable.")
        return

    # Select best Python asset
    picked = _pick_assets(release)
    is_patch = False
    python_asset = None

    if picked is not None:
        if picked.python_patch is not None:
            python_asset = picked.python_patch
            is_patch = True
        elif picked.python_full is not None:
            python_asset = picked.python_full

    if python_asset is None:
        # Plain fallback: first .zip in assets
        raw = next((a for a in release.get("assets", []) if a.get("name", "").endswith(".zip")), None)
        if raw is None:
            log("No suitable Python asset found in release", "warning")
            return
        class _A:
            url = raw["browser_download_url"]
            name = raw["name"]
        python_asset = _A()

    if base_dir is None:
        base_dir = str(Path(sys.argv[0]).parent)
    base_path = Path(base_dir)
    dl_dir = base_path / "_update_download"
    dl_dir.mkdir(parents=True, exist_ok=True)
    temp_archive = dl_dir / python_asset.name

    if temp_archive.exists() and temp_archive.stat().st_size > 0:
        log(f"Cached archive found, skipping download: {temp_archive}")
    else:
        log(f"Downloading {python_asset.name} ...")
        try:
            _download(python_asset.url, temp_archive, on_progress=on_progress)
        except Exception as e:
            log(f"Download failed: {e}", "error")
            temp_archive.unlink(missing_ok=True)
            return

    log(f"Applying update to {base_path} ...")
    try:
        if is_patch:
            try:
                _extract_archive(temp_archive, base_path, tester_code)
            except Exception as e:
                log(f"Patch failed ({e}), falling back to full update ...", "warning")
                temp_archive.unlink(missing_ok=True)
                full_asset = _fetch_full_fallback_asset(repo, channel)
                if full_asset is None:
                    log("No full release found for fallback", "error")
                    return
                full_archive = dl_dir / full_asset.name
                log(f"Downloading full release {full_asset.name} ...")
                _download(full_asset.url, full_archive, on_progress=on_progress)
                _wipe_dir(base_path)
                _extract_archive(full_archive, base_path, tester_code)
                full_archive.unlink(missing_ok=True)
        else:
            _wipe_dir(base_path)
            _extract_archive(temp_archive, base_path, tester_code)
            temp_archive.unlink(missing_ok=True)

        log(f"Update {remote_tag} installed successfully. Restarting ...", "success")
        # Exit code 42 signals launch.py / run.bat to restart.
        # Continuing from stale .pyz offsets would cause ZipImportError.
        sys.exit(42)

    except _PasswordError:
        # Архив валидный, пароль не установлен — не выкидываем, юзер вернётся
        # с TESTER_CODE и не качает заново.
        log("Archive is password-protected. Set TESTER_CODE in settings to unlock.", "error")
        log(f"Archive kept for retry: {temp_archive}")
    except Exception as e:
        log(f"Update failed: {e}", "error")
        temp_archive.unlink(missing_ok=True)


def check_for_unity_updates(
    base_dir: Optional[str] = None,
    logger=None,
    unity_dir: Optional[str] = None,
    channel: str = "stable",
    tester_code: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    auto_update: Optional[bool] = None,
) -> None:
    """Check for Unity-part updates. Apply automatically if AUTO_UPDATE_UNITY=1.

    The Unity part is installed adjacent to the Python part by default
    (parent_dir/NeuroMita-Unity), or in the path specified by unity_dir.

    Does NOT call sys.exit(42): Unity runs as a separate process, no Python
    restart is needed after a Unity update.

    Args:
        base_dir:    Game root directory (Python part).
        logger:      Logger with info/warning/success/notify methods.
        unity_dir:   Override path for the Unity install directory.
        channel:     "stable" or "beta".
        tester_code: Password for encrypted test archives.
        on_progress: Callback(downloaded_bytes, total_bytes) for UI progress.
        auto_update: Force auto-apply behavior instead of reading env/config only.
    """
    log = _make_logger(logger)

    repo = _get_repo()
    if auto_update is None:
        auto_update = os.environ.get("AUTO_UPDATE_UNITY", "0") == "1"
    channel = (channel or os.environ.get("UPDATE_CHANNEL", "stable")).lower()
    tester_code = tester_code or os.environ.get("TESTER_CODE") or None

    if base_dir is None:
        base_dir = str(Path(sys.argv[0]).parent)
    base_path = Path(base_dir)

    unity_path = Path(unity_dir) if unity_dir else base_path.parent / "NeuroMita-Unity"

    version_file = unity_path / "_version.txt"
    install_complete = _find_unity_executable(unity_path) is not None
    local_version = (
        version_file.read_text(encoding="utf-8").strip()
        if version_file.exists()
        else "0.0.0.0"
    )

    log(f"Checking Unity updates ({repo}, channel={channel}) ...")

    release = _select_release(repo, channel)
    if release is None:
        log("Could not reach GitHub to check for Unity updates", "warning")
        return

    remote_tag = release.get("tag_name", "")
    if not remote_tag:
        return

    if not _is_newer(remote_tag, local_version) and install_complete:
        log(f"Unity up to date: {local_version}")
        return
    if not install_complete:
        log("Unity installation is incomplete or missing executable. Reinstalling current release.", "warning")

    log(f"New Unity version available: {remote_tag} (current: {local_version})", "notify")

    if not auto_update:
        log("Unity auto-update is disabled (AUTO_UPDATE_UNITY=0). Enable in settings.")
        return

    # Select Unity asset
    picked = _pick_assets(release)
    unity_url = None
    unity_name = None

    if picked is not None and picked.unity is not None:
        unity_url = picked.unity.url
        unity_name = picked.unity.name
    else:
        raw = next(
            (a for a in release.get("assets", [])
             if "unity" in a.get("name", "").lower()
             and a.get("name", "").lower().endswith((".zip", ".7z"))),
            None,
        )
        if raw is None:
            log("No Unity asset found in release", "warning")
            return
        unity_url = raw["browser_download_url"]
        unity_name = raw["name"]

    dl_dir = base_path / "_update_download"
    dl_dir.mkdir(parents=True, exist_ok=True)
    temp_archive = dl_dir / unity_name

    # Если архив уже скачан (например прошлый запуск свалился из-за
    # отсутствия TESTER_CODE) — переиспользуем его, не качаем 392 МБ повторно.
    if temp_archive.exists() and temp_archive.stat().st_size > 0:
        log(
            f"Cached archive found, skipping download: {temp_archive} "
            f"({_format_bytes(temp_archive.stat().st_size)})"
        )
    else:
        log(f"Downloading Unity {unity_name} to {temp_archive} ...")
        try:
            _download(unity_url, temp_archive, on_progress=on_progress)
        except Exception as e:
            log(f"Unity download failed: {e}", "error")
            temp_archive.unlink(missing_ok=True)
            return

    archive_size = temp_archive.stat().st_size if temp_archive.exists() else 0
    log(
        f"Installing Unity update to {unity_path} "
        f"from {temp_archive.name} ({_format_bytes(archive_size)}, suffix={temp_archive.suffix.lower()}) ..."
    )
    try:
        log("Stage 1/3: cleaning target directory")
        _wipe_dir(unity_path, logger=logger)
        log("Stage 2/3: extracting archive")
        _extract_archive(temp_archive, unity_path, tester_code, logger=logger)
        log("Stage 3/3: writing installed version marker")
        unity_path.mkdir(parents=True, exist_ok=True)
        version_file.write_text(remote_tag, encoding="utf-8")
        temp_archive.unlink(missing_ok=True)
        log(f"Unity update {remote_tag} installed successfully.", "success")
    except _PasswordError:
        # Архив валидный, просто нет пароля — оставляем для следующей попытки.
        log("Unity archive is password-protected. Set TESTER_CODE in settings.", "error")
        log(f"Archive kept for retry: {temp_archive}")
    except Exception as e:
        log(f"Unity update failed: {e}", "error")
        temp_archive.unlink(missing_ok=True)
