import qtawesome as qta
from PyQt6.QtCore import QFileSystemWatcher, QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from localization.live import language_changed_signal, tr_set
from styles.gallery import get_gallery_stylesheet
from styles.theme import get_theme
from ui.dialogs.gallery_viewer import GalleryViewer
from ui.pages.gallery_presentation import (
    GalleryFolderReady,
    GalleryPhotoLoaded,
    GalleryState,
    GalleryThumbnailsLoaded,
    OpenGalleryFolder,
    RefreshGallery,
)
from ui.widgets.gallery_grid import GalleryGrid, GalleryPhotoModel
from ui.widgets.loading_spinner import LoadingSpinner
from ui.widgets.tr_combobox import TRQComboBox
from utils import _


class GalleryPage(QWidget):
    def __init__(self, parent, view_model):
        super().__init__(parent)
        self.setObjectName("GalleryPage")
        self.setStyleSheet(get_gallery_stylesheet())
        self._view_model = view_model
        self._view_model.setParent(self)
        self._state = GalleryState()
        self._revision = -1
        self._active = False
        self._viewer = None
        self._watcher = QFileSystemWatcher(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)
        self._watcher.directoryChanged.connect(self._directory_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setObjectName("GalleryIcon")
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(
            qta.icon("fa6s.images", color=get_theme()["accent"]).pixmap(28, 28)
        )
        header.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = tr_set(QLabel(), "Галерея", "Gallery")
        title.setObjectName("GalleryTitle")
        text.addWidget(title)
        description = tr_set(
            QLabel(),
            "Фотографии, сделанные на телефон в игре.",
            "Photos taken with the in-game phone.",
        )
        description.setObjectName("GalleryMuted")
        description.setWordWrap(True)
        text.addWidget(description)
        header.addLayout(text, 1)
        self.refresh_button = self._button("fa6s.rotate-right", "Обновить", "Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        folder = self._button("fa6s.folder-open", "Открыть папку", "Open folder")
        folder.clicked.connect(lambda: self._view_model.dispatch(OpenGalleryFolder()))
        header.addWidget(folder)
        layout.addLayout(header)

        self.directory_label = QLabel()
        self.directory_label.setObjectName("GalleryMuted")
        self.directory_label.setMinimumWidth(0)
        self.directory_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.directory_label)
        filters = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("GalleryCount")
        filters.addWidget(self.count_label)
        filters.addStretch()
        self.order = TRQComboBox()
        self.order.add_tr_item("Сначала новые", "Newest first", value="newest")
        self.order.add_tr_item("Сначала старые", "Oldest first", value="oldest")
        self.order.setMinimumWidth(170)
        self.order.currentIndexChanged.connect(self._apply_order)
        filters.addWidget(self.order)
        layout.addLayout(filters)
        self.error_label = QLabel()
        self.error_label.setObjectName("GalleryError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.model = GalleryPhotoModel(self)
        self.model.thumbnail_requested.connect(self._view_model.request_thumbnail)
        self.grid = GalleryGrid(self)
        self.grid.setModel(self.model)
        self.grid.clicked.connect(self._open_photo)
        self.grid.activated.connect(self._open_photo)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        empty = QFrame()
        empty.setObjectName("GalleryEmpty")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setSpacing(12)
        empty_layout.addStretch()
        self.spinner = LoadingSpinner()
        empty_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_icon.setPixmap(
            qta.icon("fa6s.camera", color=get_theme()["accent"]).pixmap(52, 52)
        )
        empty_layout.addWidget(self.empty_icon)
        self.empty_title = QLabel()
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_description = QLabel()
        self.empty_description.setObjectName("GalleryMuted")
        self.empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_description.setWordWrap(True)
        empty_layout.addWidget(self.empty_description)
        empty_layout.addStretch()
        self.stack.addWidget(empty)
        layout.addWidget(self.stack, 1)

        view_model.state_changed.connect(self.render)
        view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda *_: view_model.close())
        language_changed_signal().connect(self._language_changed)
        self.render(view_model.state)

    def _button(self, icon, ru, en):
        button = tr_set(QPushButton(), ru, en)
        button.setObjectName("SecondaryButton")
        button.setIcon(qta.icon(icon, color=get_theme()["text"]))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def refresh(self):
        self._view_model.dispatch(RefreshGallery())

    def on_activated(self):
        self._active = True
        self.refresh()

    def on_deactivated(self):
        self._active = False
        self._refresh_timer.stop()

    def _directory_changed(self, *_):
        if self._active:
            self._refresh_timer.start()

    def render(self, state):
        self._state = state
        self.refresh_button.setEnabled(not state.loading)
        self.error_label.setText(
            _("Не удалось открыть галерею", "Could not open gallery")
            + ": "
            + state.error
            if state.error
            else ""
        )
        self.error_label.setVisible(bool(state.error and state.photos))
        self.count_label.setText(
            _("Фотографий: {count}", "Photos: {count}").format(count=len(state.photos))
        )
        self.order.setEnabled(bool(state.photos))
        if self._revision != state.revision:
            self._revision = state.revision
            self._apply_order()
        self.stack.setCurrentIndex(0 if state.photos else 1)
        self.spinner.setVisible(state.loading and not state.photos)
        self.empty_icon.setVisible(not state.loading)
        self.empty_title.setText(
            _("Загрузка фотографий…", "Loading photos…")
            if state.loading
            else (
                _("Не удалось открыть галерею", "Could not open gallery")
                if state.error
                else _("Пока нет фотографий", "No photos yet")
            )
        )
        self.empty_description.setText(
            ""
            if state.loading
            else state.error
            or _(
                "Сделайте снимок на телефон в игре — он появится здесь автоматически.",
                "Take a photo with the in-game phone — it will appear here automatically.",
            )
        )
        self._update_directory_text()
        paths = (
            [
                str(path)
                for path in (
                    state.directory,
                    state.directory.parent,
                    state.directory.parent.parent,
                )
                if path.is_dir()
            ]
            if state.directory
            else []
        )[:2]
        obsolete = set(self._watcher.directories()) - set(paths)
        if obsolete:
            self._watcher.removePaths(list(obsolete))
        new = set(paths) - set(self._watcher.directories())
        if new:
            self._watcher.addPaths(list(new))

    def _apply_order(self, *_):
        photos = self._state.photos
        self.model.set_photos(
            photos if self.order.currentData() != "oldest" else tuple(reversed(photos))
        )

    def _update_directory_text(self):
        path = str(self._state.directory or "")
        self.directory_label.setToolTip(path)
        self.directory_label.setText(
            self.directory_label.fontMetrics().elidedText(
                path, Qt.TextElideMode.ElideMiddle, self.width() - 56
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_directory_text()

    def _language_changed(self, *_):
        self.render(self._state)
        self.grid.viewport().update()

    def _open_photo(self, index):
        if not index.isValid():
            return
        if self._viewer is not None:
            self._viewer.raise_()
            self._viewer.activateWindow()
            return
        from ui.pages.gallery_presentation import LoadGalleryPhoto

        viewer = GalleryViewer(self.model.photos, index.row(), self)
        self._viewer = viewer
        viewer.photo_requested.connect(
            lambda photo: self._view_model.dispatch(LoadGalleryPhoto(photo))
        )
        viewer.finished.connect(lambda *_: setattr(self, "_viewer", None))
        viewer.show()
        viewer.load_current()

    def handle_effect(self, effect):
        if isinstance(effect, GalleryThumbnailsLoaded):
            self.model.apply_thumbnails(effect.images)
        elif isinstance(effect, GalleryPhotoLoaded) and self._viewer is not None:
            self._viewer.show_image(effect)
        elif isinstance(effect, GalleryFolderReady):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(effect.directory)))
            self.refresh()


def build_gallery_page(parent, view_model):
    return GalleryPage(parent, view_model)
