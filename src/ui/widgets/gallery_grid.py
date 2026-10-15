from collections import OrderedDict

import qtawesome as qta
from PyQt6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from styles.theme import get_theme
from utils import _

PHOTO_ROLE = Qt.ItemDataRole.UserRole
ERROR_ROLE = Qt.ItemDataRole.UserRole + 1


def photo_date_text(photo):
    label = (
        _("Снято", "Taken")
        if photo.capture_time_known
        else _("Дата файла", "File date")
    )
    return f"{label}: {photo.captured_at:%d.%m.%Y · %H:%M:%S}"


class GalleryPhotoModel(QAbstractListModel):
    thumbnail_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.photos = ()
        self._rows = {}
        self._cache = OrderedDict()
        self._requested = set()

    def set_photos(self, photos):
        self.beginResetModel()
        self.photos = tuple(photos)
        self._rows = {photo.cache_key: row for row, photo in enumerate(self.photos)}
        self._requested.intersection_update(self._rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.photos)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.photos):
            return None
        photo = self.photos[index.row()]
        if role == PHOTO_ROLE:
            return photo
        if role == Qt.ItemDataRole.DisplayRole:
            return photo.path.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{photo.path.name}\n{photo_date_text(photo)}\n{photo.size_bytes / 1024 / 1024:.1f} MB"
        if role in (Qt.ItemDataRole.DecorationRole, ERROR_ROLE):
            key = photo.cache_key
            if key in self._cache:
                self._cache.move_to_end(key)
                pixmap, error = self._cache[key]
                return pixmap if role == Qt.ItemDataRole.DecorationRole else error
            if role == Qt.ItemDataRole.DecorationRole and key not in self._requested:
                self._requested.add(key)
                self.thumbnail_requested.emit(photo)
        return None

    def apply_thumbnails(self, images):
        for photo, image, error in images:
            key = photo.cache_key
            self._requested.discard(key)
            if key not in self._rows:
                continue
            pixmap = (
                QPixmap.fromImage(image)
                if image is not None and not image.isNull()
                else None
            )
            self._cache[key] = (pixmap, error)
            self._cache.move_to_end(key)
            while len(self._cache) > 160:
                self._cache.popitem(last=False)
            index = self.index(self._rows[key])
            self.dataChanged.emit(
                index, index, [Qt.ItemDataRole.DecorationRole, ERROR_ROLE]
            )


class GalleryPhotoDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme()
        self._placeholder = qta.icon("fa6s.image", color=self._theme["muted"])

    def sizeHint(self, option, index):
        return self.parent().gridSize()

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(option.rect).adjusted(6, 6, -6, -6)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(self._theme["control_bg"]))
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(rect.center())
            painter.drawPixmap(target.topLeft(), scaled)
        else:
            icon_rect = QRectF(0, 0, 36, 36)
            icon_rect.moveCenter(rect.center())
            self._placeholder.paint(painter, icon_rect.toRect())
            if index.data(ERROR_ROLE):
                painter.setPen(QColor(self._theme["warn_text"]))
                painter.drawText(
                    rect.adjusted(12, 44, -12, -12),
                    Qt.AlignmentFlag.AlignCenter,
                    _("Не удалось прочитать фото", "Could not read photo"),
                )

        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if hovered or selected:
            gradient = QLinearGradient(
                rect.left(), rect.bottom() - 78, rect.left(), rect.bottom()
            )
            gradient.setColorAt(0, QColor(8, 9, 18, 0))
            gradient.setColorAt(1, QColor(8, 9, 18, 240))
            painter.fillRect(rect, gradient)
            photo = index.data(PHOTO_ROLE)
            painter.setPen(QColor(self._theme["text"]))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(14, 0, -14, -32),
                Qt.AlignmentFlag.AlignBottom,
                photo_date_text(photo),
            )
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(self._theme["muted"]))
            name = painter.fontMetrics().elidedText(
                photo.path.name, Qt.TextElideMode.ElideMiddle, int(rect.width()) - 28
            )
            painter.drawText(
                rect.adjusted(14, 0, -14, -12), Qt.AlignmentFlag.AlignBottom, name
            )
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        border = (
            QColor(self._theme["accent"])
            if hovered or selected
            else QColor(40, 38, 54, 217)
        )
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 12, 12)
        painter.restore()


class GalleryGrid(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GalleryGrid")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(GalleryPhotoDelegate(self))
        self._update_grid()

    def _update_grid(self):
        available = max(220, self.viewport().width() - 16)
        columns = max(1, available // 290)
        width = available // columns
        self.setGridSize(QSize(width, int((width - 12) * 0.625) + 12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid()
