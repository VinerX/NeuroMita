from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect, QVBoxLayout
from PyQt6.QtGui import QPainter, QColor, QPaintEvent

class OverlayWidget(QWidget):
    """Универсальный overlay виджет для отображения контента поверх основного интерфейса"""
    
    closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")
        
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0)
        
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(250)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_widget = None
        self.locked = False
        
        self.hide()
        
    def set_content(self, widget, locked=False):
        """Установить виджет контента
        
        Args:
            widget: Виджет для отображения
            locked: Если True, клик вне виджета не закроет overlay
        """
        if self.content_widget:
            self.layout.removeWidget(self.content_widget)
            self.content_widget.deleteLater()
        
        self.content_widget = widget
        self.layout.addWidget(widget)
        self.locked = locked
        
    def show_animated(self):
        """Показать overlay с анимацией"""
        self.show()
        self.raise_()
        
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.start()

    def show_immediate(self):
        """Show the overlay fully rendered without waiting for an animation."""
        self.fade_animation.stop()
        self.opacity_effect.setOpacity(1.0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        
    def hide_animated(self):
        """Скрыть overlay с анимацией"""
        self.fade_animation.setStartValue(1)
        self.fade_animation.setEndValue(0)
        self.fade_animation.finished.connect(self._on_hide_finished)
        self.fade_animation.start()
        
    def _on_hide_finished(self):
        """Вызывается после завершения анимации скрытия"""
        self.hide()
        self.fade_animation.finished.disconnect()
        self.closed.emit()
        
    def mousePressEvent(self, event):
        """Закрыть при клике на фон"""
        if not self.locked and event.button() == Qt.MouseButton.LeftButton:
            if self.content_widget and not self.content_widget.geometry().contains(event.pos()):
                self.hide_animated()
        super().mousePressEvent(event)
