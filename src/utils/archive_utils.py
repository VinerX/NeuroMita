from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from core.task_supervisor import task_supervisor


class PasswordError(Exception):
    """Archive is encrypted and the provided password is missing or wrong."""


class ArchiveCancelled(RuntimeError):
    """Archive extraction was cancelled before the target became active."""


def _validate_member_names(names: list[str]) -> None:
    for raw_name in names:
        normalized = str(raw_name or "").replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe archive member path: {raw_name}")


def _archive_format(archive: Path) -> str:
    """Detect supported archive formats by signature, then fall back to extension."""
    try:
        with archive.open("rb") as source:
            signature = source.read(8)
    except OSError:
        signature = b""
    if signature.startswith(b"7z\xbc\xaf'\x1c"):
        return ".7z"
    if signature.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ".zip"
    if signature.startswith(b"Rar!\x1a\x07"):
        return ".rar"
    return archive.suffix.lower()


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(max(0, size))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0


def make_logger(logger, prefix: str | None = None):
    def log(msg: str, level: str = "info") -> None:
        if logger:
            getattr(logger, level, logger.info)(msg)
        else:
            print(f"{prefix} {msg}" if prefix else msg)

    return log


def _find_existing_executable(candidates: list[str]) -> Optional[Path]:
    seen: set[str] = set()
    for candidate in candidates:
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen:
            continue
        seen.add(norm)
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def find_7z_executable() -> Optional[Path]:
    candidates: list[str] = []
    for name in ("7z", "7z.exe", "7za", "7za.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        for rel in ("7-Zip\\7z.exe", "7-Zip\\7za.exe"):
            candidates.append(str(Path(base) / rel))

    return _find_existing_executable(candidates)


def find_winrar_executable() -> Optional[Path]:
    candidates: list[str] = []
    for name in ("WinRAR", "WinRAR.exe", "UnRAR", "UnRAR.exe", "rar", "rar.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        for rel in ("WinRAR\\WinRAR.exe", "WinRAR\\UnRAR.exe", "WinRAR\\Rar.exe"):
            candidates.append(str(Path(base) / rel))

    return _find_existing_executable(candidates)


def _looks_like_password_error(output: str) -> bool:
    hay = (output or "").lower()
    needles = (
        "password",
        "wrong password",
        "encrypted",
        "can not open encrypted archive",
        "cannot open encrypted archive",
    )
    return any(needle in hay for needle in needles)


def _run_command_with_heartbeat(
    cmd: list[str],
    *,
    archive_name: str,
    description: str,
    logger=None,
    interval_sec: float = 10.0,
    stop_event=None,
) -> tuple[int, str]:
    log = make_logger(logger)
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    next_heartbeat = started + max(1.0, interval_sec)
    while proc.poll() is None:
        if stop_event is not None and stop_event.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3.0)
            proc.communicate()
            raise ArchiveCancelled(f"Extraction cancelled: {archive_name}")
        now = time.monotonic()
        if now >= next_heartbeat:
            elapsed = int(now - started)
            log(f"{description} still running: {archive_name}, elapsed={elapsed}s")
            next_heartbeat = now + max(1.0, interval_sec)
        time.sleep(0.2)

    output, _ = proc.communicate()
    return proc.returncode or 0, output or ""


def _extract_with_7z(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
    stop_event=None,
) -> bool:
    log = make_logger(logger)
    exe = find_7z_executable()
    if exe is None:
        log("External 7z executable not found, skipping.")
        return False

    stage_dir = target.parent / f".{target.name}.7z_tmp"
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(exe),
        "x",
        str(archive),
        f"-o{stage_dir}",
        "-y",
        "-bb0",
        "-bso0",
        "-bsp0",
    ]
    if password:
        cmd.append(f"-p{password}")

    log(f"Using external 7z extractor: {exe}")
    try:
        code, output = _run_command_with_heartbeat(
            cmd,
            archive_name=archive.name,
            description="External 7z extraction",
            logger=logger,
            stop_event=stop_event,
        )
        if code != 0:
            if _looks_like_password_error(output):
                raise PasswordError("Archive is password-protected")
            summary = output.strip().splitlines()
            tail = summary[-1] if summary else f"exit code {code}"
            log(f"External 7z extractor failed: {tail}.", "warning")
            shutil.rmtree(stage_dir, ignore_errors=True)
            return False

        for child in list(stage_dir.iterdir()):
            shutil.move(str(child), str(target / child.name))
        log(f"External 7z extraction finished: {archive.name}")
        return True
    except (PasswordError, ArchiveCancelled):
        raise
    except Exception as exc:
        log(f"External 7z extractor failed with exception: {exc}.", "warning")
        shutil.rmtree(stage_dir, ignore_errors=True)
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _extract_with_winrar(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
    stop_event=None,
) -> bool:
    log = make_logger(logger)
    exe = find_winrar_executable()
    if exe is None:
        log("WinRAR executable not found, skipping.")
        return False

    stage_dir = target.parent / f".{target.name}.winrar_tmp"
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(exe),
        "x",
        "-y",
        "-ibck",
        str(archive),
        str(stage_dir) + os.sep,
    ]
    if password:
        cmd.insert(2, f"-p{password}")

    log(f"Using WinRAR extractor: {exe}")
    try:
        code, output = _run_command_with_heartbeat(
            cmd,
            archive_name=archive.name,
            description="WinRAR extraction",
            logger=logger,
            stop_event=stop_event,
        )
        if code != 0:
            if _looks_like_password_error(output):
                raise PasswordError("Archive is password-protected")
            summary = output.strip().splitlines()
            tail = summary[-1] if summary else f"exit code {code}"
            log(f"WinRAR extractor failed: {tail}.", "warning")
            shutil.rmtree(stage_dir, ignore_errors=True)
            return False

        for child in list(stage_dir.iterdir()):
            shutil.move(str(child), str(target / child.name))
        log(f"WinRAR extraction finished: {archive.name}")
        return True
    except (PasswordError, ArchiveCancelled):
        raise
    except Exception as exc:
        log(f"WinRAR extractor failed with exception: {exc}.", "warning")
        shutil.rmtree(stage_dir, ignore_errors=True)
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _extract_zip_with_expand_archive(
    archive: Path,
    target: Path,
    logger=None,
    stop_event=None,
) -> bool:
    log = make_logger(logger)
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        log("PowerShell executable not found for Expand-Archive, skipping.")
        return False

    stage_dir = target.parent / f".{target.name}.expand_archive_tmp"
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    archive_arg = str(archive).replace("'", "''")
    stage_dir_arg = str(stage_dir).replace("'", "''")
    script = (
        "Expand-Archive "
        f"-LiteralPath '{archive_arg}' "
        f"-DestinationPath '{stage_dir_arg}' "
        "-Force"
    )
    cmd = [powershell, "-NoProfile", "-NonInteractive", "-Command", script]

    log("Using PowerShell Expand-Archive extractor.")
    try:
        code, output = _run_command_with_heartbeat(
            cmd,
            archive_name=archive.name,
            description="Expand-Archive extraction",
            logger=logger,
            stop_event=stop_event,
        )
        if code != 0:
            summary = output.strip().splitlines()
            tail = summary[-1] if summary else f"exit code {code}"
            log(f"Expand-Archive failed: {tail}.", "warning")
            shutil.rmtree(stage_dir, ignore_errors=True)
            return False

        for child in list(stage_dir.iterdir()):
            shutil.move(str(child), str(target / child.name))
        log(f"Expand-Archive extraction finished: {archive.name}")
        return True
    except ArchiveCancelled:
        raise
    except Exception as exc:
        log(f"Expand-Archive failed with exception: {exc}.", "warning")
        shutil.rmtree(stage_dir, ignore_errors=True)
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def _extract_zip_python(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_event=None,
) -> None:
    pwd = password.encode("utf-8") if password else None
    log = make_logger(logger)
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [member for member in zf.infolist() if not member.is_dir()]
            total_entries = len(zf.infolist())
            total_size = sum(max(0, int(member.file_size or 0)) for member in members)
            extracted_size = 0
            last_log = time.monotonic()

            log(
                f"ZIP extraction started: {archive.name}, files={len(members)}, "
                f"uncompressed={format_bytes(total_size)}"
            )
            try:
                for index, member in enumerate(zf.infolist(), start=1):
                    if stop_event is not None and stop_event.is_set():
                        raise ArchiveCancelled(f"Extraction cancelled: {archive.name}")
                    out_path = target / member.filename
                    if member.is_dir():
                        out_path.mkdir(parents=True, exist_ok=True)
                        continue

                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, pwd=pwd) as src, open(out_path, "wb") as dst:
                        while True:
                            if stop_event is not None and stop_event.is_set():
                                raise ArchiveCancelled(f"Extraction cancelled: {archive.name}")
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)

                    extracted_size += max(0, int(member.file_size or 0))
                    now = time.monotonic()
                    if on_progress and total_size > 0:
                        on_progress(extracted_size, total_size)
                    if index == 1 or index == total_entries or (now - last_log) >= 5.0:
                        pct = int(extracted_size * 100 / total_size) if total_size > 0 else 0
                        log(
                            f"ZIP extraction progress: {index}/{total_entries} entries, "
                            f"{format_bytes(extracted_size)} / {format_bytes(total_size)} ({pct}%)"
                        )
                        last_log = now
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "password" in msg or "encrypted" in msg:
                    raise PasswordError(str(exc)) from exc
                raise
            log(f"ZIP extraction finished: {archive.name}")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Bad zip: {archive.name}") from exc


def _extract_7z_python(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
    stop_event=None,
) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise RuntimeError("py7zr is not installed; cannot open .7z archives") from exc

    log = make_logger(logger)
    heartbeat_stop = threading.Event()

    def heartbeat():
        started = time.monotonic()
        while not heartbeat_stop.wait(10.0):
            elapsed = int(time.monotonic() - started)
            log(f"7z extraction still running: {archive.name}, elapsed={elapsed}s")

    try:
        task_supervisor().start_thread(
            heartbeat_stop,
            f"7z-heartbeat:{archive.name}",
            heartbeat,
            cancel_event=heartbeat_stop,
        )
        if stop_event is not None and stop_event.is_set():
            raise ArchiveCancelled(f"Extraction cancelled: {archive.name}")
        with py7zr.SevenZipFile(archive, mode="r", password=password or None) as zf:
            if zf.needs_password() and not password:
                raise PasswordError("Archive is password-protected")
            try:
                entries = zf.list()
                file_entries = [entry for entry in entries if not getattr(entry, "is_directory", False)]
                total_size = sum(max(0, int(getattr(entry, "uncompressed", 0) or 0)) for entry in file_entries)
                log(
                    f"7z extraction started: {archive.name}, files={len(file_entries)}, "
                    f"uncompressed={format_bytes(total_size)}"
                )
            except Exception:
                log(f"7z extraction started: {archive.name}")
            zf.extractall(path=target)
        if stop_event is not None and stop_event.is_set():
            raise ArchiveCancelled(f"Extraction cancelled: {archive.name}")
        log(f"7z extraction finished: {archive.name}")
    except py7zr.exceptions.PasswordRequired as exc:
        raise PasswordError(str(exc)) from exc
    except py7zr.exceptions.Bad7zFile as exc:
        if password:
            raise PasswordError("Wrong tester code") from exc
        raise ValueError(f"Bad 7z: {archive.name}") from exc
    finally:
        heartbeat_stop.set()
        task_supervisor().cancel_owner(heartbeat_stop, timeout=0.5)


def _flatten_single_root(dest: Path, logger=None) -> None:
    log = make_logger(logger)
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
            target = dest / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    try:
                        target.unlink()
                    except OSError:
                        pass
            shutil.move(str(item), str(target))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"Flattening finished for: {dest}")


def extract_archive(
    archive: Path,
    target: Path,
    password: Optional[str] = None,
    logger=None,
    on_extract_progress: Optional[Callable[[int, int], None]] = None,
    stop_event=None,
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    suffix = _archive_format(archive)
    declared_suffix = archive.suffix.lower()
    if suffix != declared_suffix:
        make_logger(logger)(
            f"Archive format detected as {suffix} despite {declared_suffix or 'missing'} extension: "
            f"{archive.name}"
        )

    if suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            _validate_member_names([item.filename for item in source.infolist()])
    elif suffix == ".7z":
        try:
            import py7zr

            with py7zr.SevenZipFile(archive, mode="r", password=password or None) as source:
                _validate_member_names([str(item.filename) for item in source.list()])
        except ImportError:
            pass
        except py7zr.exceptions.PasswordRequired as exc:
            raise PasswordError(str(exc)) from exc
        except py7zr.exceptions.Bad7zFile as exc:
            if password:
                raise PasswordError("Wrong tester code") from exc
            raise ValueError(f"Bad 7z: {archive.name}") from exc

    if suffix == ".zip":
        if not _extract_with_7z(archive, target, password, logger=logger, stop_event=stop_event):
            if not _extract_with_winrar(archive, target, password, logger=logger, stop_event=stop_event):
                if not _extract_zip_with_expand_archive(archive, target, logger=logger, stop_event=stop_event):
                    _extract_zip_python(
                        archive,
                        target,
                        password,
                        logger=logger,
                        on_progress=on_extract_progress,
                        stop_event=stop_event,
                    )
    elif suffix == ".7z":
        if not _extract_with_7z(archive, target, password, logger=logger, stop_event=stop_event):
            if not _extract_with_winrar(archive, target, password, logger=logger, stop_event=stop_event):
                _extract_7z_python(archive, target, password, logger=logger, stop_event=stop_event)
    elif suffix == ".rar":
        if not _extract_with_7z(archive, target, password, logger=logger, stop_event=stop_event):
            if not _extract_with_winrar(archive, target, password, logger=logger, stop_event=stop_event):
                raise RuntimeError("No available extractor for .rar archives")
    else:
        raise ValueError(f"Unsupported archive type: {archive.name}")

    _flatten_single_root(target, logger=logger)


def wipe_dir(target: Path, logger=None) -> None:
    log = make_logger(logger)
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
