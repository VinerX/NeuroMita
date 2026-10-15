from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QImageReader

from controllers.gui.intent_view_model import IntentViewModel
from core.error_utils import format_exception
from main_logger import logger
from services.photo_gallery import PhotoGallery
from ui.pages.gallery_presentation import (
    GalleryFolderReady,
    GalleryPhotoLoaded,
    GalleryState,
    GalleryThumbnailsLoaded,
    LoadGalleryPhoto,
    OpenGalleryFolder,
    RefreshGallery,
)


def read_gallery_image(photo, *, thumbnail=False):
    reader = QImageReader(str(photo.path))
    reader.setAutoTransform(True)
    if thumbnail:
        size = reader.size()
        if size.isValid() and (size.width() > 640 or size.height() > 420):
            reader.setScaledSize(
                size.scaled(QSize(640, 420), Qt.AspectRatioMode.KeepAspectRatio)
            )
    image = reader.read()
    return image, "" if not image.isNull() else reader.errorString()


class GalleryPageViewModel(IntentViewModel[GalleryState]):
    def __init__(self, *, settings, gallery=None, parent=None):
        super().__init__(GalleryState(), parent)
        self._settings = settings
        self._gallery = gallery or PhotoGallery()
        self._pending_thumbnails = {}
        self._thumbnail_busy = False
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._load_thumbnails)

    def dispatch(self, intent):
        if self.is_closed:
            return
        if isinstance(intent, RefreshGallery):
            directory = self._gallery.directory(
                self._settings.get("UNITY_INSTALL_DIR") or None
            )
            changed = directory != self.state.directory
            if changed:
                self._pending_thumbnails.clear()
            self.update_state(
                directory=directory,
                loading=True,
                error="",
                photos=() if changed else self.state.photos,
                revision=self.state.revision + int(changed),
            )
            self.run_coalesced(
                "gallery-scan",
                lambda: self._gallery.scan(directory),
                lambda photos: self.update_state(
                    photos=photos,
                    loading=False,
                    error="",
                    revision=self.state.revision + 1,
                ),
                lambda error: self.update_state(
                    loading=False, error=format_exception(error)
                ),
            )
        elif isinstance(intent, OpenGalleryFolder):
            directory = self._gallery.directory(
                self._settings.get("UNITY_INSTALL_DIR") or None
            )
            self.run_exclusive(
                "gallery-folder",
                lambda: self._gallery.ensure_directory(directory),
                lambda path: self.emit_effect(GalleryFolderReady(path)),
                lambda error: self.update_state(error=format_exception(error)),
            )
        elif isinstance(intent, LoadGalleryPhoto):
            self.run_latest(
                "gallery-photo",
                lambda: read_gallery_image(intent.photo),
                lambda result: self.emit_effect(
                    GalleryPhotoLoaded(intent.photo, *result)
                ),
                lambda error: self.emit_effect(
                    GalleryPhotoLoaded(intent.photo, None, format_exception(error))
                ),
            )

    def request_thumbnail(self, photo):
        if self.is_closed:
            return
        self._pending_thumbnails[photo.cache_key] = photo
        if not self._thumbnail_busy and not self._thumbnail_timer.isActive():
            self._thumbnail_timer.start(0)

    def _load_thumbnails(self):
        if self.is_closed or not self._pending_thumbnails or self._thumbnail_busy:
            return
        photos = tuple(self._pending_thumbnails.values())[:12]
        for photo in photos:
            self._pending_thumbnails.pop(photo.cache_key, None)
        self._thumbnail_busy = True

        def worker():
            return tuple(
                (photo, *read_gallery_image(photo, thumbnail=True)) for photo in photos
            )

        def applied(images):
            self._thumbnail_busy = False
            for photo, image, error in images:
                if error:
                    logger.warning(
                        "[Gallery] Cannot read photo %s: %s", photo.path.name, error
                    )
            self.emit_effect(GalleryThumbnailsLoaded(images))
            self._thumbnail_timer.start(0)

        def failed(error):
            applied(tuple((photo, None, format_exception(error)) for photo in photos))

        self.run_exclusive("gallery-thumbnails", worker, applied, failed)

    def close(self):
        self._thumbnail_timer.stop()
        self._pending_thumbnails.clear()
        super().close()
