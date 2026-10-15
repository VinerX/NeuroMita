from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.unity_installation import unity_install_dir


@dataclass(frozen=True, slots=True)
class GalleryPhoto:
    path: Path
    captured_at: datetime
    capture_time_known: bool
    size_bytes: int
    modified_ns: int

    @property
    def cache_key(self) -> tuple[Path, int, int]:
        return self.path, self.modified_ns, self.size_bytes


class PhotoGallery:
    extensions = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
    _capture_time = re.compile(r"^selfie_(\d{8}_\d{9})$", re.IGNORECASE)

    def directory(self, configured_unity_dir: str | None = None) -> Path:
        return (
            unity_install_dir(configured_unity_dir).expanduser().resolve() / "Gallery"
        )

    def scan(self, directory: Path) -> tuple[GalleryPhoto, ...]:
        if not directory.exists():
            return ()
        photos = []
        for path in directory.iterdir():
            if path.suffix.lower() not in self.extensions or not path.is_file():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            match = self._capture_time.fullmatch(path.stem)
            captured = None
            if match:
                try:
                    captured = datetime.strptime(match[1], "%Y%m%d_%H%M%S%f")
                except ValueError:
                    pass
            photos.append(
                GalleryPhoto(
                    path=path,
                    captured_at=captured or datetime.fromtimestamp(stat.st_mtime),
                    capture_time_known=captured is not None,
                    size_bytes=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                )
            )
        return tuple(
            sorted(
                photos,
                key=lambda photo: (photo.captured_at, photo.path.name),
                reverse=True,
            )
        )

    def ensure_directory(self, directory: Path) -> Path:
        directory.mkdir(exist_ok=True)
        return directory
