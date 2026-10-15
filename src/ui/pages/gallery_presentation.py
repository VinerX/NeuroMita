from dataclasses import dataclass
from pathlib import Path

from services.photo_gallery import GalleryPhoto
from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class GalleryState:
    directory: Path | None = None
    photos: tuple[GalleryPhoto, ...] = ()
    loading: bool = False
    error: str = ""
    revision: int = 0


@dataclass(frozen=True, slots=True)
class RefreshGallery(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class OpenGalleryFolder(UiIntent):
    pass


@dataclass(frozen=True, slots=True)
class LoadGalleryPhoto(UiIntent):
    photo: GalleryPhoto


@dataclass(frozen=True, slots=True)
class GalleryPhotoLoaded(UiEffect):
    photo: GalleryPhoto
    image: object
    error: str = ""


@dataclass(frozen=True, slots=True)
class GalleryThumbnailsLoaded(UiEffect):
    images: tuple


@dataclass(frozen=True, slots=True)
class GalleryFolderReady(UiEffect):
    directory: Path
