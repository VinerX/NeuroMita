"""
Image cleanup utilities for NeuroMita.

Provides:
  - get_image_stats()         — count / disk usage of stored images
  - scan_orphaned_images()    — files on disk not referenced in world.db
  - delete_orphaned_images()  — remove those orphans
"""
from __future__ import annotations
from core.error_utils import format_exception

import json
import os
import sqlite3
from pathlib import Path
from typing import NamedTuple

from main_logger import logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_histories_dir() -> Path:
    return Path(os.environ.get("NEUROMITA_HISTORIES_DIR", os.path.join(os.getcwd(), "Histories")))


def _get_world_db_path() -> Path:
    """Return the path to world.db (the single shared history DB)."""
    histories_dir = _get_histories_dir()
    # DatabaseManager uses NEUROMITA_HISTORIES_DIR / world.db by default.
    return histories_dir / "world.db"


def _collect_all_image_files(histories_dir: Path) -> list[Path]:
    """Return every image file found under Histories/*/Images/."""
    result: list[Path] = []
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bin"}
    for images_dir in histories_dir.glob("*/Images"):
        if images_dir.is_dir():
            for f in images_dir.iterdir():
                if f.is_file() and f.suffix.lower() in image_exts:
                    result.append(f)
    return result


def _collect_referenced_paths(db_path: Path) -> set[str]:
    """
    Query world.db and return a set of normalised image file paths
    that are referenced in any message's meta_data.
    """
    referenced: set[str] = set()
    if not db_path.exists():
        return referenced
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT meta_data FROM history WHERE meta_data IS NOT NULL")
        for (meta_raw,) in cur.fetchall():
            if not meta_raw:
                continue
            try:
                meta = json.loads(meta_raw)
                for part in meta.get("multimodal_parts") or []:
                    if not isinstance(part, dict):
                        continue
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and not str(url).startswith("data:") and not str(url).startswith("http"):
                        referenced.add(os.path.normcase(str(url)))
            except Exception:
                pass
        conn.close()
    except Exception as e:
        logger.warning(f"[image_cleanup] Failed to scan DB {db_path}: {format_exception(e)}")
    return referenced


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class CharStats(NamedTuple):
    files: int
    bytes: int


class ImageStats(NamedTuple):
    total_files: int
    total_bytes: int
    by_character: dict[str, CharStats]


def get_image_stats() -> ImageStats:
    """Return counts and disk usage of images stored in Histories/*/Images/."""
    histories_dir = _get_histories_dir()
    total_files = 0
    total_bytes = 0
    by_character: dict[str, CharStats] = {}

    for images_dir in histories_dir.glob("*/Images"):
        if not images_dir.is_dir():
            continue
        char_name = images_dir.parent.name
        char_files = 0
        char_bytes = 0
        for f in images_dir.iterdir():
            if f.is_file():
                size = f.stat().st_size
                char_files += 1
                char_bytes += size
                total_files += 1
                total_bytes += size
        by_character[char_name] = CharStats(files=char_files, bytes=char_bytes)

    return ImageStats(total_files=total_files, total_bytes=total_bytes, by_character=by_character)


def scan_orphaned_images() -> tuple[list[Path], int]:
    """
    Find image files in Histories/*/Images/ that are NOT referenced in world.db.
    Returns (orphan_paths, total_orphan_bytes).
    """
    histories_dir = _get_histories_dir()
    db_path = _get_world_db_path()

    all_files = _collect_all_image_files(histories_dir)
    referenced = _collect_referenced_paths(db_path)

    orphans: list[Path] = []
    total_bytes = 0
    for f in all_files:
        if os.path.normcase(str(f)) not in referenced:
            orphans.append(f)
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass

    return sorted(orphans), total_bytes


def delete_orphaned_images(dry_run: bool = False) -> tuple[int, int]:
    """
    Delete orphaned image files (those not referenced in world.db).
    Returns (count_deleted, bytes_freed).
    """
    orphans, _ = scan_orphaned_images()
    count = 0
    freed = 0
    for f in orphans:
        try:
            size = f.stat().st_size
            if not dry_run:
                f.unlink()
            freed += size
            count += 1
            logger.info(
                f"[image_cleanup] {'[dry-run] would delete' if dry_run else 'Deleted'} orphan: {f}"
            )
        except Exception as e:
            logger.warning(f"[image_cleanup] Failed to delete {f}: {format_exception(e)}")
    return count, freed


def format_bytes(n: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"
