from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtGui import QPixmap, QPainter
import qtawesome as qta

class ImageViewerWidget(QWidget):
    """Виджет для отображения полноразмерного изображения"""
    
    close_requested = pyqtSignal()
    
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.original_pixmap = pixmap
        self.setObjectName("ImageViewerWidget")
        self.setup_ui()
        
    def setup_ui(self):
        # Стили
        self.setStyleSheet("""
            #ImageViewerWidget {
                background-color: #2c2c2c;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
            }
            #CloseButton {
                background-color: rgba(229, 115, 115, 200);
                border-radius: 15px;
                min-width: 30px;
                max-width: 30px;
                min-height: 30px;
                max-height: 30px;
            }
            #CloseButton:hover {
                background-color: rgba(239, 83, 80, 220);
            }
            #CloseButton:pressed {
                background-color: rgba(244, 67, 54, 255);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Контейнер для изображения и кнопки
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        
        # Кнопка закрытия
        close_btn = QPushButton(qta.icon('fa5s.times', color='white'), '')
        close_btn.setObjectName("CloseButton")
        close_btn.clicked.connect(self.close_requested.emit)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Layout для кнопки (в правом верхнем углу)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        container_layout.addLayout(btn_layout)
        
        # Label для изображения
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #1e1e1e; border-radius: 4px;")
        
        # Масштабируем изображение чтобы оно помещалось на экран
        self._scale_pixmap_to_fit()
        
        container_layout.addWidget(self.image_label)
        layout.addWidget(container)
        
    def _scale_pixmap_to_fit(self):
        """Масштабировать изображение чтобы оно помещалось на экран"""
        # Получаем размер экрана с отступами
        screen = self.screen()
        if screen:
            screen_size = screen.availableGeometry().size()
            max_width = int(screen_size.width() * 0.9)  # 90% ширины экрана
            max_height = int(screen_size.height() * 0.85)  # 85% высоты экрана
        else:
            max_width = 1600
            max_height = 900
            
        # Вычитаем отступы и рамки
        max_width -= 60
        max_height -= 100
        
        # Масштабируем изображение с сохранением пропорций
        scaled_pixmap = self.original_pixmap
        if (self.original_pixmap.width() > max_width or 
            self.original_pixmap.height() > max_height):
            scaled_pixmap = self.original_pixmap.scaled(
                max_width, max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        
        self.image_label.setPixmap(scaled_pixmap)
        
        # Устанавливаем размер виджета
        self.setFixedSize(
            scaled_pixmap.width() + 40,
            scaled_pixmap.height() + 80
        )