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
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from utils.archive_utils import PasswordError, extract_archive, format_bytes, make_logger, wipe_dir

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
    stop_event=None,
) -> None:
    """Stream url to dest (atomic replace via .part file).

    on_progress(downloaded_bytes, total_bytes) is called periodically.
    stop_event: threading.Event — set it to cancel the download.
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
                        if stop_event is not None and stop_event.is_set():
                            raise RuntimeError("Cancelled")
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
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("Cancelled") from e
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"Download failed after {retries} attempts: {last_err}")


# ── Archive extraction ────────────────────────────────────────────────────────



# ── Directory wipe (with user_data backup) ────────────────────────────────────



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
    log = make_logger(logger, _LOG_PREFIX)

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
                extract_archive(temp_archive, base_path, tester_code)
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
                wipe_dir(base_path)
                extract_archive(full_archive, base_path, tester_code)
                full_archive.unlink(missing_ok=True)
        else:
            wipe_dir(base_path)
            extract_archive(temp_archive, base_path, tester_code)
            temp_archive.unlink(missing_ok=True)

        log(f"Update {remote_tag} installed successfully. Restarting ...", "success")
        # Exit code 42 signals launch.py / run.bat to restart.
        # Continuing from stale .pyz offsets would cause ZipImportError.
        sys.exit(42)

    except PasswordError:
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
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    auto_update: Optional[bool] = None,
    stop_event=None,
) -> None:
    """Check for Unity-part updates. Apply automatically if AUTO_UPDATE_UNITY=1.

    The Unity part is installed adjacent to the Python part by default
    (parent_dir/NeuroMita-Unity), or in the path specified by unity_dir.

    Does NOT call sys.exit(42): Unity runs as a separate process, no Python
    restart is needed after a Unity update.

    Args:
        base_dir:           Game root directory (Python part).
        logger:             Logger with info/warning/success/notify methods.
        unity_dir:          Override path for the Unity install directory.
        channel:            "stable" or "beta".
        tester_code:        Password for encrypted test archives.
        on_progress:        Callback(downloaded_bytes, total_bytes) for download progress.
        on_extract_progress: Callback(extracted_bytes, total_bytes) for extraction progress.
        auto_update:        Force auto-apply behavior instead of reading env/config only.
        stop_event:         threading.Event — set to cancel download.
    """
    log = make_logger(logger, _LOG_PREFIX)

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
            f"({format_bytes(temp_archive.stat().st_size)})"
        )
    else:
        log(f"Downloading Unity {unity_name} to {temp_archive} ...")
        try:
            _download(unity_url, temp_archive, on_progress=on_progress, stop_event=stop_event)
        except RuntimeError as e:
            if stop_event is not None and stop_event.is_set():
                log("Unity download cancelled by user.", "warning")
                temp_archive.unlink(missing_ok=True)
                return
            log(f"Unity download failed: {e}", "error")
            temp_archive.unlink(missing_ok=True)
            return
        except Exception as e:
            log(f"Unity download failed: {e}", "error")
            temp_archive.unlink(missing_ok=True)
            return

    archive_size = temp_archive.stat().st_size if temp_archive.exists() else 0
    log(
        f"Installing Unity update to {unity_path} "
        f"from {temp_archive.name} ({format_bytes(archive_size)}, suffix={temp_archive.suffix.lower()}) ..."
    )
    try:
        log("Stage 1/3: cleaning target directory")
        wipe_dir(unity_path, logger=logger)
        log("Stage 2/3: extracting archive")
        extract_archive(temp_archive, unity_path, tester_code, logger=logger, on_extract_progress=on_extract_progress)
        log("Stage 3/3: writing installed version marker")
        unity_path.mkdir(parents=True, exist_ok=True)
        version_file.write_text(remote_tag, encoding="utf-8")
        temp_archive.unlink(missing_ok=True)
        log(f"Unity update {remote_tag} installed successfully.", "success")
    except PasswordError:
        # Архив валидный, просто нет пароля — оставляем для следующей попытки.
        log("Unity archive is password-protected. Set TESTER_CODE in settings.", "error")
        log(f"Archive kept for retry: {temp_archive}")
    except Exception as e:
        log(f"Unity update failed: {e}", "error")
        temp_archive.unlink(missing_ok=True)
