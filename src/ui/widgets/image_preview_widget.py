from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRect
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QScrollArea, QPushButton
from PyQt6.QtGui import QPixmap, QPainter, QPaintEvent, QBrush, QPen, QColor, QRegion
import qtawesome as qta
import base64
import io
from PIL import Image
from styles.theme import get_theme

class ImageThumbnail(QFrame):
    """Отдельная миниатюра изображения"""
    
    clicked = pyqtSignal(object)  # Передаем данные изображения
    remove_clicked = pyqtSignal(int)  # Передаем индекс
    
    def __init__(self, image_data, index, parent=None):
        super().__init__(parent)
        self._theme = get_theme()
        self.image_data = image_data
        self.index = index
        self.pixmap = None
        
        self.setFixedSize(48, 48)  # Уменьшили размер
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            ImageThumbnail {{
                background-color: {self._theme["settings_panel_bg"]};
                border: 2px solid rgba({self._theme["sidebar_panel_rgb"]}, 0.98);
                border-radius: 6px;
            }}
            ImageThumbnail:hover {{
                border: 2px solid {self._theme["accent_alt"]};
                background-color: rgba({self._theme["accent_rgb"]}, 0.10);
            }}
        """)
        
        # Кнопка удаления
        self.remove_btn = QPushButton(qta.icon('fa5s.times', color='white', scale_factor=0.6), '', self)
        self.remove_btn.setFixedSize(16, 16)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(229, 115, 115, 200);
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(239, 83, 80, 220);
            }
            QPushButton:pressed {
                background-color: rgba(244, 67, 54, 255);
            }
        """)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.index))
        self.remove_btn.move(self.width() - 18, 2)  # Позиция в правом верхнем углу
        self.remove_btn.hide()  # Скрыта по умолчанию
        
        self._load_thumbnail()
        
    def _load_thumbnail(self):
        """Загрузить миниатюру из данных изображения"""
        try:
            # Декодируем base64 если нужно
            if isinstance(self.image_data, str) and self.image_data.startswith("data:image"):
                base64_data = self.image_data.split(",")[1]
                img_bytes = base64.b64decode(base64_data)
            elif isinstance(self.image_data, bytes):
                img_bytes = self.image_data
            else:
                return
                
            # Создаем миниатюру с обрезкой для квадрата
            image = Image.open(io.BytesIO(img_bytes))
            
            # Обрезаем до квадрата (центральная часть)
            width, height = image.size
            if width > height:
                left = (width - height) // 2
                right = left + height
                image = image.crop((left, 0, right, height))
            elif height > width:
                top = (height - width) // 2
                bottom = top + width
                image = image.crop((0, top, width, bottom))
            
            # Масштабируем до размера виджета
            image = image.resize((44, 44), Image.Resampling.LANCZOS)
            
            # Конвертируем в QPixmap
            img_bytes_io = io.BytesIO()
            image.save(img_bytes_io, format='PNG')
            img_bytes_io.seek(0)
            
            self.pixmap = QPixmap()
            self.pixmap.loadFromData(img_bytes_io.getvalue())
            
        except Exception as e:
            print(f"Ошибка загрузки миниатюры: {e}")
            
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Создаем скругленный путь обрезки
        path = QPainter()
        rect = QRect(2, 2, self.width() - 4, self.height() - 4)
        painter.setClipRect(rect)
        
        # Рисуем фон
        painter.fillRect(rect, QColor(self._theme["settings_panel_bg"]))
        
        # Рисуем изображение на весь квадрат
        if self.pixmap:
            painter.drawPixmap(2, 2, self.width() - 4, self.height() - 4, self.pixmap)
            
    def enterEvent(self, event):
        """При наведении показываем кнопку удаления"""
        self.remove_btn.show()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """При уходе курсора скрываем кнопку"""
        self.remove_btn.hide()
        super().leaveEvent(event)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Проверяем, что клик не на кнопке удаления
            if not self.remove_btn.geometry().contains(event.pos()):
                self.clicked.emit(self.image_data)
        super().mousePressEvent(event)


class ImagePreviewBar(QWidget):
    """Панель с превью прикрепленных изображений"""
    
    thumbnail_clicked = pyqtSignal(object)
    remove_requested = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnails = []
        self.setup_ui()
        
    def setup_ui(self):
        self.setMaximumHeight(64)  # Уменьшили высоту
        self.setStyleSheet("""
            ImagePreviewBar {
                background-color: transparent;
            }
        """)
        
        # Основной layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 4, 0, 4)
        main_layout.setSpacing(0)
        
        # ScrollArea для миниатюр
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(56)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:horizontal {
                height: 8px;
            }
        """)
        
        # Контейнер для миниатюр
        self.thumbnail_container = QWidget()
        self.thumbnail_layout = QHBoxLayout(self.thumbnail_container)
        self.thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        self.thumbnail_layout.setSpacing(6)
        self.thumbnail_layout.addStretch()
        
        scroll.setWidget(self.thumbnail_container)
        main_layout.addWidget(scroll)
        
    def add_images(self, image_data_list):
        """Добавить изображения в превью"""
        for i, img_data in enumerate(image_data_list):
            self.add_image(img_data)
            
    def add_image(self, image_data):
        """Добавить одно изображение"""
        index = len(self.thumbnails)
        thumbnail = ImageThumbnail(image_data, index)
        thumbnail.clicked.connect(self.thumbnail_clicked.emit)
        thumbnail.remove_clicked.connect(self._on_remove_requested)
        
        # Вставляем перед stretch
        self.thumbnail_layout.insertWidget(self.thumbnail_layout.count() - 1, thumbnail)
        self.thumbnails.append(thumbnail)
        
    def _on_remove_requested(self, index):
        """Обработка запроса на удаление"""
        self.remove_requested.emit(index)
        
    def clear(self):
        """Очистить все миниатюры"""
        for thumb in self.thumbnails:
            thumb.deleteLater()
        self.thumbnails.clear()
        
    def remove_at(self, index):
        """Удалить миниатюру по индексу"""
        if 0 <= index < len(self.thumbnails):
            thumb = self.thumbnails.pop(index)
            thumb.deleteLater()
            
            # Обновляем индексы оставшихся
            for i, thumb in enumerate(self.thumbnails):
                thumb.index = i
