from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

from utils import _
from localization.live import register_if_tr
from ui.settings.settings_access import settings_store


class StatusIndicatorChip(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._active = False
        self.setObjectName("StatusIndicatorChip")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.dot_label = QLabel()
        self.dot_label.setObjectName("StatusIndicatorDot")
        self.dot_label.setFixedSize(14, 14)
        layout.addWidget(self.dot_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text_label = QLabel(text)
        register_if_tr(self.text_label, text)
        self.text_label.setObjectName("StatusIndicatorText")
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setChecked(False)

    def setChecked(self, checked: bool):
        self._active = bool(checked)
        self.setProperty("active", self._active)
        self.dot_label.setProperty("active", self._active)
        self.text_label.setProperty("active", self._active)
        for widget in (self, self.dot_label, self.text_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def isChecked(self) -> bool:
        return self._active

    def setText(self, text: str):
        self.text_label.setText(text)

    def text(self) -> str:
        return self.text_label.text()


def apply_capture_visibility(gui, mode=None):
    # The capture indicators (screen / camera) live behind the "screen"
    # settings section. `mode` is kept for backward compatibility but ignored.
    try:
        from ui.widgets.settings_panel import is_section_enabled

        visible = is_section_enabled("screen", settings_store(gui))
    except Exception:
        visible = False

    registry = getattr(gui, "_status_indicator_registry", {})
    for attr in ("screen_capture_status_checkbox", "camera_capture_status_checkbox"):
        for widget in registry.get(attr, []):
            widget.setVisible(visible)

        w = getattr(gui, attr, None)
        if w is not None:
            w.setVisible(visible)


def _create_indicator(text):
    return StatusIndicatorChip(text)


def _register_indicator(gui, attr_name: str, widget: StatusIndicatorChip):
    registry = getattr(gui, "_status_indicator_registry", None)
    if registry is None:
        registry = {}
        gui._status_indicator_registry = registry

    registry.setdefault(attr_name, []).append(widget)
    setattr(gui, attr_name, widget)


def create_status_indicators(gui, parent_layout):
    status_frame = QWidget()
    status_frame.setObjectName("StatusIndicatorStrip")
    status_layout = QHBoxLayout(status_frame)
    status_layout.setContentsMargins(12, 10, 12, 10)
    status_layout.setSpacing(14)
    status_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    widget = _create_indicator(_("Игра", "Game"))
    _register_indicator(gui, "game_status_checkbox", widget)
    status_layout.addWidget(widget)

    widget = _create_indicator(_("Озвучка", "Voice"))
    _register_indicator(gui, "silero_status_checkbox", widget)
    status_layout.addWidget(widget)

    widget = _create_indicator(_("RAG", "RAG"))
    _register_indicator(gui, "rag_status_checkbox", widget)
    status_layout.addWidget(widget)

    widget = _create_indicator(_("Распознавание", "Recognition"))
    _register_indicator(gui, "mic_status_checkbox", widget)
    status_layout.addWidget(widget)

    widget = _create_indicator(_("Экран", "Screen"))
    _register_indicator(gui, "screen_capture_status_checkbox", widget)
    status_layout.addWidget(widget)

    widget = _create_indicator(_("Камера", "Camera"))
    _register_indicator(gui, "camera_capture_status_checkbox", widget)
    status_layout.addWidget(widget)

    status_layout.addStretch()
    parent_layout.addWidget(status_frame)

    gui.update_status_colors()
    apply_capture_visibility(gui)


def create_status_indicators_inline_legacy(gui, layout):
    widget = _create_indicator(_("Игра", "Game"))
    _register_indicator(gui, "game_status_checkbox", widget)
    layout.addWidget(widget)

    widget = _create_indicator(_("Озвучка", "Voice"))
    _register_indicator(gui, "silero_status_checkbox", widget)
    layout.addWidget(widget)

    widget = _create_indicator(_("RAG", "RAG"))
    _register_indicator(gui, "rag_status_checkbox", widget)
    layout.addWidget(widget)

    widget = _create_indicator(_("Распознавание", "Recognition"))
    _register_indicator(gui, "mic_status_checkbox", widget)
    layout.addWidget(widget)

    widget = _create_indicator(_("Экран", "Screen"))
    _register_indicator(gui, "screen_capture_status_checkbox", widget)
    layout.addWidget(widget)

    widget = _create_indicator(_("Камера", "Camera"))
    _register_indicator(gui, "camera_capture_status_checkbox", widget)
    layout.addWidget(widget)

    gui.update_status_colors()
    apply_capture_visibility(gui)


def create_status_indicators_inline(gui, layout):
    status_frame = QWidget()
    status_frame.setObjectName("InlineStatusIndicators")
    status_frame.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    status_layout = QGridLayout(status_frame)
    status_layout.setContentsMargins(0, 0, 0, 0)
    status_layout.setHorizontalSpacing(12)
    status_layout.setVerticalSpacing(6)

    widget = _create_indicator(_("Игра", "Game"))
    _register_indicator(gui, "game_status_checkbox", widget)
    status_layout.addWidget(widget, 0, 0)

    widget = _create_indicator(_("Озвучка", "Voice"))
    _register_indicator(gui, "silero_status_checkbox", widget)
    status_layout.addWidget(widget, 0, 1)

    widget = _create_indicator(_("RAG", "RAG"))
    _register_indicator(gui, "rag_status_checkbox", widget)
    status_layout.addWidget(widget, 0, 2)

    widget = _create_indicator(_("Распознавание", "Recognition"))
    _register_indicator(gui, "mic_status_checkbox", widget)
    status_layout.addWidget(widget, 1, 0)

    widget = _create_indicator(_("Экран", "Screen"))
    _register_indicator(gui, "screen_capture_status_checkbox", widget)
    status_layout.addWidget(widget, 1, 1)

    widget = _create_indicator(_("Камера", "Camera"))
    _register_indicator(gui, "camera_capture_status_checkbox", widget)
    status_layout.addWidget(widget, 1, 2)

    layout.addWidget(status_frame)

    gui.update_status_colors()
    apply_capture_visibility(gui)
