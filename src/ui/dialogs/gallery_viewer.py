import qtawesome as qta
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from localization.live import language_changed_signal, tr_set
from styles.gallery import get_gallery_stylesheet
from styles.main_styles import get_stylesheet
from styles.theme import get_theme
from ui.widgets.gallery_grid import photo_date_text
from ui.widgets.loading_spinner import LoadingSpinner
from utils import _


class GalleryImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GalleryImageView")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit = True
        self._item = None

    def set_image(self, image):
        self.scene().clear()
        self._item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self._item.boundingRect())
        self.fit_image()

    def fit_image(self):
        self._fit = True
        if self._item is not None:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.fit_image()

    def zoom(self, factor):
        if self._item is None:
            return
        scale = self.transform().m11() * factor
        if 0.03 <= scale <= 12:
            self._fit = False
            self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()


class GalleryViewer(QDialog):
    photo_requested = pyqtSignal(object)

    def __init__(self, photos, index, parent=None):
        super().__init__(parent)
        self.setObjectName("GalleryViewer")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(get_stylesheet() + get_gallery_stylesheet())
        tr_set(self, "Просмотр фотографии", "Photo viewer", "setWindowTitle")
        self.setWindowIcon(qta.icon("fa6s.images", color=get_theme()["accent"]))
        self.photos = tuple(photos)
        self.index = index
        self._dimensions = ""
        self._error = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        copy = QVBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setMinimumWidth(0)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.metadata = QLabel()
        self.metadata.setObjectName("GalleryMuted")
        copy.addWidget(self.title)
        copy.addWidget(self.metadata)
        header.addLayout(copy, 1)
        external = self._button(
            "fa6s.arrow-up-right-from-square", "Открыть оригинал", "Open original"
        )
        external.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.photos[self.index].path))
            )
        )
        header.addWidget(external)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        loading = QWidget()
        waiting = QVBoxLayout(loading)
        waiting.addStretch()
        self.spinner = LoadingSpinner()
        waiting.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        waiting.addWidget(self.message)
        waiting.addStretch()
        self.stack.addWidget(loading)
        self.image_view = GalleryImageView()
        self.stack.addWidget(self.image_view)
        layout.addWidget(self.stack, 1)
        toolbar = QHBoxLayout()
        self.previous = self._button(
            "fa6s.chevron-left", "Предыдущее фото", "Previous photo"
        )
        self.next = self._button("fa6s.chevron-right", "Следующее фото", "Next photo")
        self.previous.clicked.connect(lambda: self.navigate(-1))
        self.next.clicked.connect(lambda: self.navigate(1))
        toolbar.addWidget(self.previous)
        self.counter = QLabel()
        toolbar.addWidget(self.counter)
        toolbar.addWidget(self.next)
        toolbar.addStretch()
        fit = self._button("fa6s.expand", "Вписать в окно", "Fit to window")
        fit.clicked.connect(self.image_view.fit_image)
        toolbar.addWidget(fit)
        close = tr_set(QPushButton(), "Закрыть", "Close")
        close.clicked.connect(self.close)
        toolbar.addWidget(close)
        layout.addLayout(toolbar)
        for key, direction in (("Left", -1), ("Right", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda d=direction: self.navigate(d))
        language_changed_signal().connect(self._update_metadata)
        screen = self.screen().availableGeometry()
        self.resize(
            min(1200, int(screen.width() * 0.88)), min(850, int(screen.height() * 0.88))
        )

    def _button(self, icon, ru, en):
        button = tr_set(QPushButton(), ru, en)
        button.setObjectName("SecondaryButton")
        button.setIcon(qta.icon(icon, color=get_theme()["text"]))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def load_current(self):
        photo = self.photos[self.index]
        self._dimensions = ""
        self._error = ""
        self.title.setText(photo.path.name)
        self.counter.setText(f"{self.index + 1} / {len(self.photos)}")
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(self.photos) - 1)
        self._update_metadata()
        self.message.setText(_("Загрузка фотографии…", "Loading photo…"))
        self.spinner.show()
        self.stack.setCurrentIndex(0)
        self.photo_requested.emit(photo)

    def navigate(self, delta):
        new_index = self.index + delta
        if 0 <= new_index < len(self.photos):
            self.index = new_index
            self.load_current()

    def show_image(self, effect):
        if effect.photo != self.photos[self.index]:
            return
        if effect.error or effect.image is None or effect.image.isNull():
            self.spinner.hide()
            self._error = effect.error or _(
                "Не удалось прочитать фото", "Could not read photo"
            )
            self._update_metadata()
            return
        self.image_view.set_image(effect.image)
        self._dimensions = f"{effect.image.width()} × {effect.image.height()}"
        self._update_metadata()
        self.stack.setCurrentIndex(1)

    def _update_metadata(self, *_args):
        photo = self.photos[self.index]
        self.message.setText(
            _("Не удалось прочитать фото", "Could not read photo") + "\n" + self._error
            if self._error
            else _("Загрузка фотографии…", "Loading photo…")
        )
        self.metadata.setText(
            " · ".join(
                filter(
                    None,
                    (
                        photo_date_text(photo),
                        self._dimensions,
                        f"{photo.size_bytes / 1024 / 1024:.1f} MB",
                    ),
                )
            )
        )
