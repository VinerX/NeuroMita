from PyQt6.QtWidgets import QWidget, QHBoxLayout, QCheckBox
from PyQt6.QtCore import Qt
from utils import _


def apply_capture_visibility(gui, mode=None):
    """Показывать/скрывать индикаторы захвата экрана и камеры в зависимости от режима интерфейса."""
    try:
        from ui.widgets.settings_panel import normalize_mode
        m = normalize_mode(mode or gui.settings.get('INTERFACE_MODE'))
    except Exception:
        m = 'basic'
    visible = m in ('advanced', 'full')
    for attr in ('screen_capture_status_checkbox', 'camera_capture_status_checkbox'):
        w = getattr(gui, attr, None)
        if w is not None:
            w.setVisible(visible)


def create_status_indicators(gui, parent_layout):
    status_frame = QWidget()
    status_layout = QHBoxLayout(status_frame)
    status_layout.setContentsMargins(0, 0, 0, 0)
    status_layout.setSpacing(15) # Увеличим расстояние между индикаторами
    status_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    def create_indicator(text):
        checkbox = QCheckBox(text)
        checkbox.setObjectName("StatusIndicator")
        checkbox.setEnabled(False) # Нельзя кликать
        checkbox.setStyleSheet("color: #ffffff; spacing: 5px;") # Уменьшим расстояние между галкой и текстом
        return checkbox

    gui.game_status_checkbox = create_indicator(_('Игра', 'Game'))
    status_layout.addWidget(gui.game_status_checkbox)

    gui.silero_status_checkbox = create_indicator(_('Озвучка', 'Voice'))
    status_layout.addWidget(gui.silero_status_checkbox)

    gui.rag_status_checkbox = create_indicator(_('RAG', 'RAG'))
    status_layout.addWidget(gui.rag_status_checkbox)

    gui.mic_status_checkbox = create_indicator(_('Распознавание', 'Recognition'))
    status_layout.addWidget(gui.mic_status_checkbox)

    gui.screen_capture_status_checkbox = create_indicator(_('Захват экрана', 'Screen'))
    status_layout.addWidget(gui.screen_capture_status_checkbox)

    gui.camera_capture_status_checkbox = create_indicator(_('Камера', 'Camera'))
    status_layout.addWidget(gui.camera_capture_status_checkbox)

    status_layout.addStretch() # Добавляем растяжение, чтобы индикаторы не занимали всю ширину

    parent_layout.addWidget(status_frame)

    gui.update_status_colors()
    apply_capture_visibility(gui)

def create_status_indicators_inline(gui, layout):
    """Создает статус индикаторы для верхней панели чата"""
    def create_indicator(text):
        checkbox = QCheckBox(text)
        checkbox.setObjectName("StatusIndicator")
        checkbox.setEnabled(False)
        checkbox.setStyleSheet("color: #ffffff; spacing: 5px;")
        return checkbox

    gui.game_status_checkbox = create_indicator(_('Игра', 'Game'))
    layout.addWidget(gui.game_status_checkbox)

    gui.silero_status_checkbox = create_indicator(_('Озвучка', 'Voice'))
    layout.addWidget(gui.silero_status_checkbox)

    gui.rag_status_checkbox = create_indicator(_('RAG', 'RAG'))
    layout.addWidget(gui.rag_status_checkbox)

    gui.mic_status_checkbox = create_indicator(_('Распознавание', 'Recognition'))
    layout.addWidget(gui.mic_status_checkbox)

    gui.screen_capture_status_checkbox = create_indicator(_('Захват экрана', 'Screen'))
    layout.addWidget(gui.screen_capture_status_checkbox)

    gui.camera_capture_status_checkbox = create_indicator(_('Камера', 'Camera'))
    layout.addWidget(gui.camera_capture_status_checkbox)

    gui.update_status_colors()
    apply_capture_visibility(gui)