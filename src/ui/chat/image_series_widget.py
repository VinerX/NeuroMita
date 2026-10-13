from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
from utils import _
from core.tv_observation import normalize_tv_observation
from ui.chat.message_widget import ImageWidget


class ImageSeriesWidget(QFrame):
    def __init__(self, images, *, tv_observation=None, max_width=600, parent=None):
        super().__init__(parent)
        self.setObjectName("imageSeries")
        self.setMaximumWidth(max_width)
        self.setStyleSheet(
            "QFrame#imageSeries { border: 1px solid #665878; border-radius: 10px; background: #292431; }"
            "QFrame#imageSeries QLabel { color: #e4dce9; background: transparent; border: none; }"
            "QFrame#imageSeries QScrollArea, QFrame#imageSeries QWidget { background: transparent; }"
            "QFrame#imageSeries QPushButton { color: #e4dce9; background: #403348; border: 1px solid #665878; "
            "border-radius: 5px; padding: 5px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        tv = normalize_tv_observation(tv_observation)
        title = (_("Просмотр TV", "TV viewing") if tv else _("Серия изображений", "Image sequence"))
        title += f" · {len(images)} " + _("кадров", "frames")
        header = QLabel(title)
        header.setStyleSheet("font-weight: bold; color: #e0cbe9; border: none;")
        layout.addWidget(header)
        if tv:
            info = QLabel(f'{tv["title"]}\n{tv["author"] or _("Автор неизвестен", "Unknown author")} · '
                          f'{int(tv["time_seconds"]) // 60:02}:{int(tv["time_seconds"]) % 60:02}')
            info.setTextFormat(Qt.TextFormat.PlainText)
            info.setWordWrap(True)
            layout.addWidget(info)
        self._viewers = []
        if images:
            strip = QWidget()
            row = QHBoxLayout(strip)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            for index, image in enumerate(images):
                viewer = ImageWidget(image["url"], description=image.get("description", ""), parent=self)
                viewer.hide()
                self._viewers.append(viewer)
                tile = QWidget()
                tile_layout = QVBoxLayout(tile)
                tile_layout.setContentsMargins(0, 0, 0, 0)
                label = QLabel()
                label.setFixedSize(128, 80)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setPixmap(viewer._original_pixmap.scaled(128, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                                             Qt.TransformationMode.SmoothTransformation))
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                label.setToolTip(_("Открыть кадр", "Open frame"))
                label.mousePressEvent = lambda event, v=viewer: v._show_fullsize()
                tile_layout.addWidget(label)
                number = QLabel(str(index + 1))
                number.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tile_layout.addWidget(number)
                row.addWidget(tile)
            row.addStretch()
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFixedHeight(130)
            scroll.setWidget(strip)
            layout.addWidget(scroll)
        if tv and tv["subtitles"]:
            toggle = QPushButton(_("Показать субтитры", "Show subtitles"))
            toggle.setCheckable(True)
            text = QLabel(tv["subtitles"])
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            text.hide()
            def toggle_subtitles(checked):
                text.setVisible(checked)
                toggle.setText(_("Скрыть субтитры", "Hide subtitles") if checked else _("Показать субтитры", "Show subtitles"))
            toggle.toggled.connect(toggle_subtitles)
            layout.addWidget(toggle)
            layout.addWidget(text)
