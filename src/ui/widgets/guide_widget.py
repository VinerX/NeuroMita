# src/ui/widgets/guide_widget.py
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QRadioButton, QButtonGroup, QComboBox, QSizePolicy, QScrollArea, QMenu
from PyQt6.QtGui import QPixmap, QAction, QPainter, QPen, QColor
import qtawesome as qta
from abc import ABC, abstractmethod
from localization import available_languages, language_display_name, translate_for_language
from main_logger import logger
import os
import re
from styles.theme import get_theme
from utils import render_qss
from ui.settings.settings_access import get_setting, set_setting

class IGuidePage(ABC):
    min_mode: str = "basic"

    def __init__(self):
        self._highlight_target = None

    def set_highlight_target(self, target):
        """Store an optional UI target for callers that decorate guide steps."""
        self._highlight_target = target

    @abstractmethod
    def get_title_ru(self) -> str:
        pass

    @abstractmethod
    def get_title_en(self) -> str:
        pass

    @abstractmethod
    def get_description_ru(self) -> str:
        pass

    @abstractmethod
    def get_description_en(self) -> str:
        pass

    @abstractmethod
    def get_image_filename(self, language: str) -> str:
        pass

    def get_image_crop(self):
        """Optional normalized crop: (left, top, right, bottom)."""
        return None

    def get_wiki_target(self):
        """Optional local Wiki document related to this guide page."""
        return None


class GuideImageLabel(QLabel):
    """Pixmap label that can draw a lightweight focus rectangle over a guide target."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._focus_rect = None

    def set_focus_rect(self, normalized_rect):
        self._focus_rect = normalized_rect
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._focus_rect or self.pixmap() is None or self.pixmap().isNull():
            return
        left, top, width, height = self._focus_rect
        rect = QRectF(
            self.width() * left,
            self.height() * top,
            self.width() * width,
            self.height() * height,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect, QColor(222, 76, 145, 42))
        painter.setPen(QPen(QColor(238, 91, 157, 230), 2.0))
        painter.drawRoundedRect(rect, 6.0, 6.0)


class GuideWidget(QWidget):
    closed = pyqtSignal()

    _SECTION_NAMES = {
        "start": ("Начало", "Getting started"),
        "voice": ("Голос и ввод", "Voice & input"),
        "memory": ("Память", "Memory"),
        "vision": ("Экран и камера", "Screen & camera"),
        "tools": ("Модели и песочница", "Models & sandbox"),
        "finish": ("Готово", "Finish"),
    }

    # Normalized rectangles are relative to the cropped image shown on each page.
    # They intentionally cover the control itself rather than the red number label.
    _STEP_TARGETS = {
        "PresetGuidePage": {
            1: (0.88, 0.20, 0.10, 0.12), 2: (0.18, 0.22, 0.43, 0.10),
            3: (0.20, 0.67, 0.48, 0.09), 4: (0.03, 0.63, 0.18, 0.10),
            5: (0.05, 0.82, 0.82, 0.07), 6: (0.05, 0.89, 0.82, 0.07),
        },
        "VoiceoverGuidePage": {
            1: (0.91, 0.31, 0.08, 0.14), 2: (0.13, 0.43, 0.83, 0.10),
            3: (0.13, 0.78, 0.83, 0.10), 4: (0.90, 0.62, 0.09, 0.12),
        },
        "MemoryRagGuidePage": {
            1: (0.03, 0.13, 0.24, 0.10), 2: (0.05, 0.22, 0.88, 0.10),
            3: (0.05, 0.31, 0.30, 0.10), 4: (0.03, 0.42, 0.26, 0.10),
            5: (0.89, 0.52, 0.08, 0.10), 6: (0.89, 0.62, 0.08, 0.10),
            7: (0.89, 0.72, 0.08, 0.10),
        },
        "MemoryVectorGuidePage": {
            8: (0.03, 0.03, 0.28, 0.09), 9: (0.89, 0.08, 0.08, 0.09),
            10: (0.07, 0.14, 0.79, 0.08), 11: (0.06, 0.39, 0.86, 0.08),
            12: (0.08, 0.78, 0.18, 0.07), 13: (0.04, 0.77, 0.12, 0.08),
            14: (0.52, 0.86, 0.43, 0.07), 15: (0.05, 0.86, 0.45, 0.07),
        },
        "MemoryGraphGuidePage": {
            16: (0.03, 0.29, 0.32, 0.16), 17: (0.88, 0.43, 0.08, 0.15),
            18: (0.88, 0.62, 0.08, 0.15),
        },
        "ScreenCaptureGuidePage": {
            1: (0.04, 0.29, 0.39, 0.12), 2: (0.90, 0.40, 0.08, 0.15),
        },
        "CameraGuidePage": {
            3: (0.04, 0.50, 0.39, 0.12), 4: (0.90, 0.63, 0.08, 0.12),
            9: (0.17, 0.72, 0.77, 0.10),
        },
        "CameraDependenciesGuidePage": {
            5: (0.88, 0.26, 0.08, 0.10), 6: (0.39, 0.08, 0.20, 0.09),
            7: (0.02, 0.73, 0.19, 0.09), 8: (0.82, 0.64, 0.15, 0.09),
        },
    }

    def __init__(self, settings_view_model, parent=None, open_wiki=None):
        super().__init__(parent)
        self.settings_view_model = settings_view_model
        self._open_wiki_callback = open_wiki
        self.pages = []
        self.current_page_index = 0
        self.current_language = "ru"
        self._guide_level = "basic"
        self._filtered_pages = []
        self._lang_buttons: dict[str, QRadioButton] = {}
        self._level_group = None
        self._current_pixmap = None
        self._image_zoom = 1.0
        self._current_wiki_target = None
        from ui.widgets.settings_panel import normalize_mode
        saved = get_setting(self, "GUIDE_LEVEL")
        if saved in ("basic", "advanced", "full"):
            self._guide_level = saved
        else:
            iface = get_setting(self, "INTERFACE_MODE")
            self._guide_level = normalize_mode(iface)
            if self._guide_level not in ("basic", "advanced", "full"):
                self._guide_level = "basic"
        self.current_language = str(
            get_setting(self, "LANGUAGE", "RU") or "RU"
        ).strip().lower()
        self.setObjectName("GuideWidget")
        self.setup_ui()
        self._init_pages()

    def setup_ui(self):
        self.setStyleSheet(render_qss("""
            #GuideWidget {
                background-color: transparent;
            }
            #GuideContainer {
                background-color: rgba({settings_panel_rgb}, 1.0);
                border: 1px solid {border_soft};
                border-radius: 16px;
            }
            #GuideTitle {
                font-size: 18px;
                font-weight: 700;
                color: {text};
                padding: 6px 8px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            #GuideDescription {
                font-size: 13px;
                color: {text};
                padding: 6px;
                line-height: 1.45;
                background-color: transparent;
            }
            #ImageToolbarButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                border-radius: 8px;
                padding: 3px 8px;
                min-width: 24px;
                min-height: 24px;
                font-weight: 600;
            }
            #ImageToolbarButton:hover {
                background-color: {chip_hover};
            }
            #ImageZoomLabel {
                color: {muted};
                font-size: 11px;
                min-width: 42px;
            }
            #ImageScroll {
                background-color: transparent;
                border: none;
            }
            #GuideHelpButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            #GuideHelpButton:hover {
                background-color: {chip_hover};
            }
            #GuideProgressTrack,
            #GuideProgressSectionTrack {
                background-color: transparent;
                border: none;
            }
            #GuideSectionTab {
                background-color: {chip_bg};
                color: {muted_text};
                border: 1px solid {outline};
                border-radius: 8px;
                min-height: 24px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
                text-align: center;
            }
            #GuideSectionTab:hover {
                border: 1px solid {accent_alt};
                background-color: {chip_hover};
                color: {text};
            }
            #GuideSectionTab[progressState="done"] {
                background-color: rgba(171, 80, 133, 0.22);
                border: 1px solid {accent_border};
                color: {text};
            }
            #GuideSectionTab[progressState="current"] {
                background-color: rgba(214, 90, 149, 0.24);
                border: 1px solid {accent_alt};
                color: {text};
            }
            #GuideProgressSegment {
                background-color: {chip_bg};
                border: 1px solid {outline};
                border-radius: 4px;
                min-height: 8px;
                max-height: 8px;
                padding: 0;
            }
            #GuideProgressSegment:hover {
                border: 1px solid {accent_alt};
                background-color: {chip_hover};
            }
            #GuideProgressSegment[progressState="done"] {
                background-color: {accent_pressed};
                border: 1px solid {accent_border};
            }
            #GuideProgressSegment[progressState="current"] {
                background-color: {accent};
                border: 1px solid {accent_alt};
                min-height: 10px;
                max-height: 10px;
            }
            #GuideContentsButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                border-radius: 8px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 600;
            }
            #GuideContentsButton:hover {
                background-color: {chip_hover};
            }
            #NavigationButton {
                background-color: {accent};
                color: #ffffff;
                border: 1px solid {accent_border};
                padding: 8px 16px;
                font-weight: 600;
                border-radius: 10px;
                min-width: 48px;
            }
            #NavigationButton:hover {
                background-color: {accent_alt};
            }
            #NavigationButton:pressed {
                background-color: {accent_pressed};
            }
            #NavigationButton:disabled {
                background-color: {btn_disabled_bg};
                color: {btn_disabled_fg};
                border: 1px solid {outline};
            }
            #PageIndicator {
                color: {muted};
                font-size: 11px;
                padding: 4px 8px;
                border-radius: 6px;
                background-color: {chip_bg};
            }
            #ImageFrame {
                background-color: rgba({sandbox_bg_rgb}, 0.92);
                border: 1px solid {outline};
                border-radius: 12px;
            }
            #ImageLabel {
                color: {muted};
                background-color: transparent;
            }
            #DescriptionFrame {
                background-color: rgba({sidebar_panel_rgb}, 0.52);
                border: 1px solid {outline};
                border-radius: 12px;
            }
            #DescriptionFrame QScrollBar:vertical,
            #ImageFrame QScrollBar:vertical {
                width: 10px;
                margin: 4px;
            }
            #DescriptionFrame QScrollBar::handle:vertical,
            #ImageFrame QScrollBar::handle:vertical {
                background-color: {accent};
                border-radius: 5px;
                min-height: 24px;
            }
            #DescriptionFrame QScrollBar::add-line:vertical,
            #DescriptionFrame QScrollBar::sub-line:vertical,
            #ImageFrame QScrollBar::add-line:vertical,
            #ImageFrame QScrollBar::sub-line:vertical {
                height: 0;
            }
            QRadioButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                border-radius: 14px;
                padding: 5px 8px;
                font-size: 12px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.18);
                background-color: rgba({sidebar_panel_rgb}, 1.0);
                margin-right: 6px;
            }
            QRadioButton::indicator:checked {
                background-color: {accent};
                border: 1px solid {accent_alt};
            }
            QComboBox {
                min-width: 180px;
                padding: 6px 10px;
                border-radius: 10px;
                border: 1px solid {outline};
                background-color: {chip_bg};
                color: {text};
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid {outline};
                background-color: {sidebar_panel};
                color: {text};
                selection-background-color: {accent};
                selection-color: #ffffff;
            }
            #GuideMetaLabel {
                color: {muted};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            /* Раньше строка выбора уровня, подсказка и метка «Язык» не имели
               своей поверхности и читались как чёрный фон поверх тёмного
               контейнера (фидбэк Артёма). Даём им ту же лёгкую подложку, что и
               у заголовка. */
            #GuideLevelRow {
                background-color: {chip_bg};
                border-radius: 16px;
            }
            #GuideLevelHint {
                color: {muted};
                font-size: 12px;
                padding: 6px 12px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            #CloseButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                padding: 8px 16px;
                font-weight: 600;
                border-radius: 10px;
            }
            #CloseButton:hover {
                background-color: {chip_hover};
            }
            #CloseButton:pressed {
                background-color: {chip_pressed};
            }
        """, get_theme()))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("GuideContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        # Keep screenshot-heavy onboarding spacious while allowing free resizing.
        self.setMinimumSize(880, 640)
        self.setMaximumSize(16777215, 16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.resize(1100, 760)

        self._level_hint = None

        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setObjectName("GuideTitle")
        title_row.addWidget(self.title_label, 1)
        title_row.addStretch()

        self.close_button = QPushButton("Завершить")
        self.close_button.setObjectName("CloseButton")
        self.close_button.clicked.connect(self._on_close)
        title_row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(title_row)

        container_layout.addLayout(header_layout)
        # Keep the guide readable at a glance: controls above, screenshot and
        # explanation side by side, navigation by itself at the bottom.
        meta_row = QFrame()
        meta_row.setObjectName("GuideLevelRow")
        meta_layout = QHBoxLayout(meta_row)
        meta_layout.setContentsMargins(10, 6, 10, 6)
        meta_layout.setSpacing(8)

        self._level_group = QButtonGroup(self)
        self._level_group.setExclusive(True)
        self._level_buttons: dict[str, QRadioButton] = {}
        for key in ("basic", "advanced", "full"):
            rb = QRadioButton("")
            rb.setObjectName("GuideLevelButton")
            rb.setProperty("level_key", key)
            rb.setMinimumHeight(32)
            if key == self._guide_level:
                rb.setChecked(True)
            meta_layout.addWidget(rb)
            self._level_group.addButton(rb)
            self._level_buttons[key] = rb
        self._level_group.buttonClicked.connect(self._on_level_changed)
        self._update_level_texts()

        meta_layout.addStretch()
        self.lang_label = QLabel("")
        self.lang_label.setObjectName("GuideMetaLabel")
        meta_layout.addWidget(self.lang_label)
        self.lang_selector = QComboBox()
        self.lang_selector.blockSignals(True)
        for code in available_languages():
            lowered = code.lower()
            self.lang_selector.addItem(language_display_name(code), lowered)
            self._lang_buttons[lowered] = None

        if self.current_language not in self._lang_buttons:
            self.current_language = "ru"
        current_index = self.lang_selector.findData(self.current_language)
        if current_index >= 0:
            self.lang_selector.setCurrentIndex(current_index)
        self.lang_selector.blockSignals(False)
        self.lang_selector.currentIndexChanged.connect(self._on_language_changed)
        meta_layout.addWidget(self.lang_selector)
        self.help_button = QPushButton("")
        self.help_button.setObjectName("GuideHelpButton")
        self.help_button.clicked.connect(self._open_help)
        self.help_button.setVisible(False)
        meta_layout.addWidget(self.help_button)
        container_layout.addWidget(meta_row)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        self.image_frame = QFrame()
        self.image_frame.setObjectName("ImageFrame")
        image_layout = QVBoxLayout(self.image_frame)
        image_layout.setContentsMargins(10, 8, 10, 10)
        image_layout.setSpacing(6)

        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(5)
        zoom_layout.addStretch()
        self.zoom_out_button = QPushButton("\u2212")
        self.zoom_out_button.setObjectName("ImageToolbarButton")
        self.zoom_out_button.setFixedSize(30, 28)
        self.zoom_out_button.clicked.connect(lambda: self._change_image_zoom(-0.25))
        zoom_layout.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("ImageZoomLabel")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_layout.addWidget(self.zoom_label)
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("ImageToolbarButton")
        self.zoom_in_button.setFixedSize(30, 28)
        self.zoom_in_button.clicked.connect(lambda: self._change_image_zoom(0.25))
        zoom_layout.addWidget(self.zoom_in_button)
        self.zoom_fit_button = QPushButton("")
        self.zoom_fit_button.setObjectName("ImageToolbarButton")
        self.zoom_fit_button.setMinimumHeight(28)
        self.zoom_fit_button.clicked.connect(self._fit_image)
        zoom_layout.addWidget(self.zoom_fit_button)
        self.zoom_width_button = QPushButton("")
        self.zoom_width_button.setObjectName("ImageToolbarButton")
        self.zoom_width_button.setMinimumHeight(28)
        self.zoom_width_button.clicked.connect(self._fit_image_width)
        zoom_layout.addWidget(self.zoom_width_button)
        self.zoom_actual_button = QPushButton("1:1")
        self.zoom_actual_button.setObjectName("ImageToolbarButton")
        self.zoom_actual_button.setMinimumHeight(28)
        self.zoom_actual_button.clicked.connect(self._show_image_actual_size)
        zoom_layout.addWidget(self.zoom_actual_button)
        image_layout.addLayout(zoom_layout)

        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("ImageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.image_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label = GuideImageLabel()
        self.image_label.setObjectName("ImageLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.image_label.setMinimumSize(0, 0)
        self.image_scroll.setWidget(self.image_label)
        image_layout.addWidget(self.image_scroll, 1)
        content_layout.addWidget(self.image_frame, 5)

        self.description_frame = QFrame()
        self.description_frame.setObjectName("DescriptionFrame")
        description_layout = QVBoxLayout(self.description_frame)
        description_layout.setContentsMargins(12, 10, 12, 10)
        description_layout.setSpacing(8)
        self.description_label = QLabel("")
        self.description_label.setObjectName("GuideDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.description_label.setOpenExternalLinks(False)
        self.description_label.linkHovered.connect(self._on_step_link_hovered)
        self.description_label.linkActivated.connect(self._on_step_link_activated)
        self.description_label.setMinimumSize(0, 0)
        self.description_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.description_scroll = QScrollArea()
        self.description_scroll.setObjectName("DescriptionScroll")
        self.description_scroll.setWidgetResizable(True)
        self.description_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.description_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.description_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.description_scroll.setWidget(self.description_label)
        description_layout.addWidget(self.description_scroll, 1)
        content_layout.addWidget(self.description_frame, 3)
        container_layout.addLayout(content_layout, 1)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.contents_button = QPushButton("")
        self.contents_button.setObjectName("GuideContentsButton")
        self.contents_button.clicked.connect(self._show_contents_menu)
        progress_row.addWidget(self.contents_button, 0)

        self.progress_track = QFrame()
        self.progress_track.setObjectName("GuideProgressTrack")
        self.progress_tracks_layout = QVBoxLayout(self.progress_track)
        self.progress_tracks_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_tracks_layout.setSpacing(5)

        self.progress_section_track = QFrame()
        self.progress_section_track.setObjectName("GuideProgressSectionTrack")
        self.progress_section_layout = QHBoxLayout(self.progress_section_track)
        self.progress_section_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_section_layout.setSpacing(6)
        self.progress_tracks_layout.addWidget(self.progress_section_track)

        self.progress_segment_track = QFrame()
        self.progress_segment_track.setObjectName("GuideProgressTrack")
        self.progress_layout = QHBoxLayout(self.progress_segment_track)
        self.progress_layout.setContentsMargins(0, 1, 0, 1)
        self.progress_layout.setSpacing(3)
        self.progress_tracks_layout.addWidget(self.progress_segment_track)

        progress_row.addWidget(self.progress_track, 1)
        container_layout.addLayout(progress_row)

        self._progress_buttons = []
        self._progress_sections = []
        self._progress_section_buttons = []
        self._progress_section_ranges = []

        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(15)
        nav_layout.addStretch()
        self.prev_button = QPushButton(qta.icon('fa5s.angle-left', color='white'), '')
        self.prev_button.setObjectName("NavigationButton")
        self.prev_button.setFixedSize(48, 35)
        self.prev_button.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_button)
        self.page_indicator = QLabel("1 / 1")
        self.page_indicator.setObjectName("PageIndicator")
        self.page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_indicator.setMinimumWidth(64)
        nav_layout.addWidget(self.page_indicator)
        self.next_button = QPushButton(qta.icon('fa5s.angle-right', color='white'), '')
        self.next_button.setObjectName("NavigationButton")
        self.next_button.setFixedSize(48, 35)
        self.next_button.clicked.connect(self._next_page)
        nav_layout.addWidget(self.next_button)
        nav_layout.addStretch()
        container_layout.addLayout(nav_layout)

        self._update_language_label_text()
        self._update_close_button_text()
        self._update_auxiliary_texts()

        main_layout.addWidget(container)

    def _on_language_changed(self):
        code = self.lang_selector.currentData() if hasattr(self, "lang_selector") else None
        self.current_language = str(code or "ru")
        self._update_language_label_text()
        self._update_close_button_text()
        self._update_level_texts()
        self._update_auxiliary_texts()
        self._rebuild_progress_steps()
        self.show_page(self.current_page_index)
    # Подписи и пояснения уровней (локализуются под выбранный язык).
    _LEVEL_LABELS = {
        "basic": ("Быстрый старт", "Quick start"),
        "advanced": ("Голос и ввод", "Voice & input"),
        "full": ("Все возможности", "Everything"),
    }
    _LEVEL_HINTS = {
        "basic": ("Подключение модели и запуск общения.",
                  "Connect a model and start chatting."),
        "advanced": ("Быстрый старт + озвучка и микрофон.",
                     "Quick start + voiceover and microphone."),
        "full": ("Все разделы: память, изображения, модели и песочница.",
                 "All sections: memory, images, models, and sandbox."),
    }
    def _update_level_texts(self):
        for key, rb in getattr(self, "_level_buttons", {}).items():
            ru, en = self._LEVEL_LABELS.get(key, (key, key))
            rb.setText(translate_for_language(self.current_language, ru, en))
            hru, hen = self._LEVEL_HINTS.get(key, ("", ""))
            rb.setToolTip(translate_for_language(self.current_language, hru, hen))
        hint = getattr(self, "_level_hint", None)
        if hint is not None:
            hru, hen = self._LEVEL_HINTS.get(self._guide_level, ("", ""))
            hint.setText(translate_for_language(self.current_language, hru, hen))

    def _update_language_label_text(self):
        self.lang_label.setText(
            translate_for_language(self.current_language, "Язык", "Language")
        )

    def _update_close_button_text(self):
        self.close_button.setText(
            translate_for_language(self.current_language, "Завершить", "Finish")
        )

    def _update_auxiliary_texts(self):
        if hasattr(self, "zoom_fit_button"):
            self.zoom_fit_button.setText(
                translate_for_language(self.current_language, "\u0412\u043f\u0438\u0441\u0430\u0442\u044c", "Fit")
            )
            self.zoom_fit_button.setToolTip(
                translate_for_language(
                    self.current_language,
                    "\u0412\u043f\u0438\u0441\u0430\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0446\u0435\u043b\u0438\u043a\u043e\u043c \u0432 \u043e\u0431\u043b\u0430\u0441\u0442\u044c \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0430",
                    "Fit the full image into the viewport",
                )
            )
        if hasattr(self, "zoom_width_button"):
            self.zoom_width_button.setText(
                translate_for_language(self.current_language, "\u041f\u043e \u0448\u0438\u0440\u0438\u043d\u0435", "Width")
            )
            self.zoom_width_button.setToolTip(
                translate_for_language(
                    self.current_language,
                    "\u0423\u0432\u0435\u043b\u0438\u0447\u0438\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0434\u043e \u0448\u0438\u0440\u0438\u043d\u044b \u043e\u0431\u043b\u0430\u0441\u0442\u0438 \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0430",
                    "Fit the image to viewport width",
                )
            )
        if hasattr(self, "zoom_actual_button"):
            self.zoom_actual_button.setToolTip(
                translate_for_language(
                    self.current_language,
                    "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0432 \u0438\u0441\u0445\u043e\u0434\u043d\u043e\u043c \u0440\u0430\u0437\u043c\u0435\u0440\u0435",
                    "Show the image at its original pixel size",
                )
            )
        if hasattr(self, "zoom_out_button"):
            self.zoom_out_button.setToolTip(translate_for_language(self.current_language, "\u0423\u043c\u0435\u043d\u044c\u0448\u0438\u0442\u044c", "Zoom out"))
        if hasattr(self, "zoom_in_button"):
            self.zoom_in_button.setToolTip(translate_for_language(self.current_language, "\u0423\u0432\u0435\u043b\u0438\u0447\u0438\u0442\u044c", "Zoom in"))
        if hasattr(self, "contents_button"):
            self.contents_button.setText(
                translate_for_language(self.current_language, "\u0420\u0430\u0437\u0434\u0435\u043b\u044b", "Contents")
            )
            self.contents_button.setToolTip(
                translate_for_language(
                    self.current_language,
                    "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u043a \u043b\u044e\u0431\u043e\u043c\u0443 \u0448\u0430\u0433\u0443 \u0440\u0443\u043a\u043e\u0432\u043e\u0434\u0441\u0442\u0432\u0430",
                    "Jump to any guide step",
                )
            )
        if hasattr(self, "help_button"):
            self.help_button.setText(translate_for_language(self.current_language, "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0435\u0435 \u0432 Wiki \u2192", "Read more in Wiki \u2192"))

    @staticmethod
    def _page_section_key(page):
        name = type(page).__name__
        if name in ("WelcomeGuidePage", "PresetGuidePage"):
            return "start"
        if name in ("VoiceoverGuidePage", "MicrophoneGuidePage"):
            return "voice"
        if name.startswith("Memory"):
            return "memory"
        if name.startswith("Screen") or name.startswith("Camera"):
            return "vision"
        if name in ("ModelsGuidePage", "SandboxGuidePage"):
            return "tools"
        return "finish"

    def _page_title(self, page):
        return translate_for_language(
            self.current_language,
            page.get_title_ru(),
            page.get_title_en(),
        )

    def _section_title(self, key):
        ru, en = self._SECTION_NAMES.get(key, (key, key))
        return translate_for_language(self.current_language, ru, en)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_progress_steps(self):
        if not hasattr(self, "progress_layout"):
            return
        self._clear_layout(self.progress_layout)
        if hasattr(self, "progress_section_layout"):
            self._clear_layout(self.progress_section_layout)
        self._progress_buttons = []
        self._progress_sections = []
        self._progress_section_buttons = []
        self._progress_section_ranges = []
        page_count = len(self._filtered_pages)
        section_ranges = []
        start_index = 0
        while start_index < page_count:
            section = self._page_section_key(self._filtered_pages[start_index])
            end_index = start_index
            while end_index + 1 < page_count and self._page_section_key(self._filtered_pages[end_index + 1]) == section:
                end_index += 1
            section_ranges.append((section, start_index, end_index))
            start_index = end_index + 1

        for section, first_index, last_index in section_ranges:
            section_button = QPushButton(self._section_title(section))
            section_button.setObjectName("GuideSectionTab")
            section_button.setCursor(Qt.CursorShape.PointingHandCursor)
            section_button.setProperty("progressState", "upcoming")
            section_button.clicked.connect(lambda checked=False, i=first_index: self.show_page(i))
            section_button.setToolTip(
                f"{self._section_title(section)} · {first_index + 1}-{last_index + 1}/{page_count}\n" +
                translate_for_language(
                    self.current_language,
                    "Нажмите, чтобы перейти к разделу",
                    "Click to open this section",
                )
            )
            if hasattr(self, "progress_section_layout"):
                self.progress_section_layout.addWidget(section_button, max(1, last_index - first_index + 1))
            self._progress_section_buttons.append(section_button)
            self._progress_section_ranges.append((section, first_index, last_index, section_button))

        previous_section = None
        for index, page in enumerate(self._filtered_pages):
            section = self._page_section_key(page)
            if previous_section is not None and section != previous_section:
                self.progress_layout.addSpacing(3)
            button = QPushButton("")
            button.setObjectName("GuideProgressSegment")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setProperty("progressState", "upcoming")
            button.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            title = self._page_title(page)
            button.setToolTip(
                f"{self._section_title(section)} · {index + 1}/{page_count}\n{title}\n" +
                translate_for_language(self.current_language, "Нажмите, чтобы перейти", "Click to open")
            )
            self.progress_layout.addWidget(button, 1)
            self._progress_buttons.append(button)
            self._progress_sections.append(section)
            previous_section = section
        self._update_progress_state(self.current_page_index)

    def _update_progress_state(self, current_index):
        for index, button in enumerate(getattr(self, "_progress_buttons", [])):
            state = "done" if index < current_index else "current" if index == current_index else "upcoming"
            if button.property("progressState") != state:
                button.setProperty("progressState", state)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

        for section, first_index, last_index, button in getattr(self, "_progress_section_ranges", []):
            if current_index > last_index:
                state = "done"
            elif first_index <= current_index <= last_index:
                state = "current"
            else:
                state = "upcoming"
            if button.property("progressState") != state:
                button.setProperty("progressState", state)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def _show_contents_menu(self):
        if not self._filtered_pages:
            return
        menu = QMenu(self)
        last_section = None
        for index, page in enumerate(self._filtered_pages):
            section = self._page_section_key(page)
            if section != last_section:
                menu.addSection(self._section_title(section))
                last_section = section
            action = QAction(f"{index + 1}. {self._page_title(page)}", menu)
            action.setCheckable(True)
            action.setChecked(index == self.current_page_index)
            action.triggered.connect(lambda checked=False, i=index: self.show_page(i))
            menu.addAction(action)
        menu.exec(self.contents_button.mapToGlobal(self.contents_button.rect().bottomLeft()))

    def _on_level_changed(self, btn):
        level = btn.property("level_key")
        if not level:
            return

        current_page = None
        if 0 <= self.current_page_index < len(self._filtered_pages):
            current_page = self._filtered_pages[self.current_page_index]

        self._guide_level = level
        self._update_filtered_pages()
        self._update_level_texts()
        self._rebuild_progress_steps()

        if self._filtered_pages:
            if current_page in self._filtered_pages:
                new_index = self._filtered_pages.index(current_page)
            else:
                new_index = 0
                if current_page in self.pages:
                    master_index = self.pages.index(current_page)
                    for candidate in reversed(self.pages[:master_index]):
                        if candidate in self._filtered_pages:
                            new_index = self._filtered_pages.index(candidate)
                            break
            self.show_page(new_index)
        # Раньше здесь были: SettingsManager.set() без сохранения на диск и emit
        # несуществующего Events.Settings.GUIDE_LEVEL_CHANGED — оба под try/except,
        # то есть уровень гайда молча не сохранялся и никто о смене не узнавал.
        # SettingsService.update() сразу обновляет реестр и планирует запись на диск.
        try:
            set_setting(self, "GUIDE_LEVEL", level)
        except Exception as e:
            logger.warning(f"[GuideWidget] Не удалось сохранить GUIDE_LEVEL: {e}")

    def _update_filtered_pages(self):
        cur_rank = _LEVEL_RANK.get(self._guide_level, 0)
        self._filtered_pages = [
            p for p in self.pages
            if _LEVEL_RANK.get(getattr(p, 'min_mode', 'basic'), 0) <= cur_rank
        ]

    def _init_pages(self):
        self.pages = [
            WelcomeGuidePage(),
            PresetGuidePage(),
            VoiceoverGuidePage(),
            MicrophoneGuidePage(),
            MemoryRagGuidePage(),
            MemoryVectorGuidePage(),
            MemoryGraphGuidePage(),
            ScreenCaptureGuidePage(),
            CameraGuidePage(),
            CameraDependenciesGuidePage(),
            ModelsGuidePage(),
            SandboxGuidePage(),
            FinalGuidePage(),
        ]
        self._update_filtered_pages()
        self._rebuild_progress_steps()
    def _load_image(self, filename):
        if not filename:
            return None

        image_path = os.path.join("assets", filename)
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                return pixmap
        return None

    @staticmethod
    def _format_description(text: str) -> str:
        """Render compact text; numbered screenshot references become interactive steps."""
        blocks = []
        marker_re = re.compile(r"<b>\s*(\d+)\s*(?:[-\u2013\u2014]\s*)?([^<]*?)</b>")

        def render_markers(value):
            def repl(match):
                number = int(match.group(1))
                label = match.group(2).strip()
                number_html = (
                    f'<a href="guide-step:{number}" '
                    'style="text-decoration:none; color:#ec6ea7;">'
                    f'<b>{number}.</b></a>'
                )
                if label:
                    return f'{number_html} <b>{label}</b>'
                return number_html
            return marker_re.sub(repl, value)

        for raw_line in str(text or "").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue

            bullet = re.match(r"^(?:[\u2022-]|\u2014)\s+(.*)$", stripped)
            content = bullet.group(1) if bullet else stripped
            has_step = marker_re.search(content) is not None
            content = render_markers(content)

            # Numbered references are the primary visual marker; do not add a second
            # bullet in front of them. Ordinary bullets keep the compact bullet table.
            if bullet and not has_step:
                blocks.append(
                    '<table cellspacing="0" cellpadding="0" width="100%" style="margin:0 0 4px 0;">'
                    '<tr><td width="14" valign="top">&#8226;</td>'
                    f'<td valign="top">{content}</td></tr></table>'
                )
                continue

            if has_step:
                blocks.append(f'<p style="margin:0 0 7px 0; line-height:1.35;">{content}</p>')
                continue

            is_heading = content.startswith("<b>") and content.endswith("</b>")
            margin = "7px 0 3px 0" if is_heading else "0 0 5px 0"
            blocks.append(f'<p style="margin:{margin};">{content}</p>')

        return "".join(blocks)

    @staticmethod
    def _crop_pixmap(pixmap, crop):
        if not crop:
            return pixmap
        left, top, right, bottom = crop
        left = max(0.0, min(1.0, float(left)))
        top = max(0.0, min(1.0, float(top)))
        right = max(left, min(1.0, float(right)))
        bottom = max(top, min(1.0, float(bottom)))
        x = round(pixmap.width() * left)
        y = round(pixmap.height() * top)
        width = round(pixmap.width() * (right - left))
        height = round(pixmap.height() * (bottom - top))
        if width < 2 or height < 2:
            return pixmap
        return pixmap.copy(x, y, width, height)

    def _fitted_image(self):
        pixmap = self._current_pixmap
        if pixmap is None or pixmap.isNull() or not hasattr(self, "image_scroll"):
            return None
        viewport = self.image_scroll.viewport()
        return pixmap.scaled(
            max(100, viewport.width() - 4),
            max(100, viewport.height() - 4),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _rescale_current_image(self):
        pixmap = self._current_pixmap
        fitted = self._fitted_image()
        if pixmap is None or pixmap.isNull() or fitted is None:
            return
        target_width = max(1, round(fitted.width() * self._image_zoom))
        target_height = max(1, round(fitted.height() * self._image_zoom))
        scaled = pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setText("")
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedSize(scaled.size())
        self._update_zoom_controls(scaled)

    def _change_image_zoom(self, delta: float):
        self._image_zoom = max(1.0, min(6.0, self._image_zoom + delta))
        self._rescale_current_image()

    def _fit_image(self):
        self._image_zoom = 1.0
        self._rescale_current_image()
        if hasattr(self, "image_scroll"):
            self.image_scroll.horizontalScrollBar().setValue(0)
            self.image_scroll.verticalScrollBar().setValue(0)

    def _fit_image_width(self):
        fitted = self._fitted_image()
        if fitted is None or fitted.width() <= 0:
            return
        viewport_width = max(1, self.image_scroll.viewport().width() - 4)
        self._image_zoom = max(1.0, min(6.0, viewport_width / fitted.width()))
        self._rescale_current_image()

    def _show_image_actual_size(self):
        pixmap = self._current_pixmap
        fitted = self._fitted_image()
        if pixmap is None or pixmap.isNull() or fitted is None or fitted.width() <= 0:
            return
        self._image_zoom = max(1.0, min(6.0, pixmap.width() / fitted.width()))
        self._rescale_current_image()

    def _update_zoom_controls(self, scaled=None):
        pixmap = self._current_pixmap
        if hasattr(self, "zoom_label"):
            if pixmap is not None and not pixmap.isNull() and scaled is not None:
                actual_percent = round((scaled.width() / max(1, pixmap.width())) * 100)
                self.zoom_label.setText(f"{actual_percent}%")
            else:
                self.zoom_label.setText("—")
        if hasattr(self, "zoom_out_button"):
            self.zoom_out_button.setEnabled(self._image_zoom > 1.0)
        if hasattr(self, "zoom_in_button"):
            self.zoom_in_button.setEnabled(self._image_zoom < 6.0)

    @staticmethod
    def _step_number_from_link(link):
        match = re.fullmatch(r"guide-step:(\d+)", str(link or ""))
        return int(match.group(1)) if match else None

    def _current_step_target(self, step_number):
        if not (0 <= self.current_page_index < len(self._filtered_pages)):
            return None
        page = self._filtered_pages[self.current_page_index]
        return self._STEP_TARGETS.get(type(page).__name__, {}).get(step_number)

    def _set_image_step_focus(self, step_number):
        target = self._current_step_target(step_number) if step_number is not None else None
        if hasattr(self, "image_label") and isinstance(self.image_label, GuideImageLabel):
            self.image_label.set_focus_rect(target)
        return target

    def _on_step_link_hovered(self, link):
        number = self._step_number_from_link(link)
        if number is not None:
            self._set_image_step_focus(number)
            return
        self._set_image_step_focus(getattr(self, "_pinned_step_number", None))

    def _on_step_link_activated(self, link):
        number = self._step_number_from_link(link)
        target = self._set_image_step_focus(number)
        if number is None or target is None:
            return
        self._pinned_step_number = number
        self._image_zoom = max(self._image_zoom, 1.35)
        self._rescale_current_image()
        QTimer.singleShot(0, lambda rect=target: self._scroll_to_image_rect(rect))

    def _scroll_to_image_rect(self, rect):
        if not rect or not hasattr(self, "image_scroll"):
            return
        left, top, width, height = rect
        target_x = round(self.image_label.width() * (left + width / 2.0))
        target_y = round(self.image_label.height() * (top + height / 2.0))
        hbar = self.image_scroll.horizontalScrollBar()
        vbar = self.image_scroll.verticalScrollBar()
        hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), target_x - self.image_scroll.viewport().width() // 2)))
        vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), target_y - self.image_scroll.viewport().height() // 2)))

    def _open_help(self):
        if self._current_wiki_target and callable(self._open_wiki_callback):
            self._open_wiki_callback(self._current_wiki_target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_current_image()

    def show_page(self, index: int):
        if 0 <= index < len(self._filtered_pages):
            self.current_page_index = index
            page = self._filtered_pages[index]

            self.title_label.setText(
                translate_for_language(self.current_language, page.get_title_ru(), page.get_title_en())
            )
            description = translate_for_language(
                self.current_language,
                page.get_description_ru(),
                page.get_description_en(),
            )
            self.description_label.setText(self._format_description(description))
            self._pinned_step_number = None
            self._set_image_step_focus(None)

            image_filename = page.get_image_filename(self.current_language)
            pixmap = self._load_image(image_filename)
            self._image_zoom = 1.0
            if pixmap:
                self._current_pixmap = self._crop_pixmap(pixmap, page.get_image_crop())
                QTimer.singleShot(0, self._rescale_current_image)
            else:
                self._current_pixmap = None
                self.image_label.clear()
                no_image_text = "Изображение не загружено" if self.current_language == "ru" else "Image not loaded"
                self.image_label.setText(no_image_text)

            page_count = len(self._filtered_pages)
            self.page_indicator.setText(f"{index + 1} / {page_count}")
            self._update_progress_state(index)
            self.prev_button.setEnabled(index > 0)
            self.next_button.setVisible(index < page_count - 1)

            self._current_wiki_target = page.get_wiki_target()
            self.help_button.setVisible(
                bool(self._current_wiki_target) and callable(self._open_wiki_callback)
            )

    def start(self):
        self.show_page(0)

    def _prev_page(self):
        if self.current_page_index > 0:
            self.show_page(self.current_page_index - 1)

    def _next_page(self):
        if self.current_page_index < len(self._filtered_pages) - 1:
            self.show_page(self.current_page_index + 1)

    def _on_close(self):
        self.closed.emit()

# ----------------- СТРАНИЦЫ РУКОВОДСТВА (обновлённые) -----------------

_LEVEL_RANK = {"basic": 0, "advanced": 1, "full": 2}


class WelcomeGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Добро пожаловать в NeuroMita!"

    def get_title_en(self):
        return "Welcome to NeuroMita!"

    def get_description_ru(self):
        return """Привет! Это краткое руководство поможет вам быстро освоиться в NeuroMita.

В этом гайде мы пройдёмся по самым важным настройкам, чтобы вы могли сразу начать общение.
Нажмите 'Далее', чтобы начать, или 'Завершить', если хотите разобраться сами."""

    def get_description_en(self):
        return """Hello! This quick guide will help you get comfortable with NeuroMita.

In this guide, we’ll walk through the most important settings so you can start chatting right away.
Click 'Next' to begin, or 'Finish' if you want to figure it out on your own."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_welcome.png" if language == "ru" else "guide/guide_welcome1.png"

    def get_wiki_target(self):
        return "getting-started.md"



class PresetGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Создание своего пресета"

    def get_title_en(self):
        return "Creating Your Own Preset"

    def get_description_ru(self):
        return """Чтобы НейроМита ожила и могла с вами общаться, ей нужен доступ к языковой модели — её «мозгу». Для этого мы создадим ваш первый пресет API. Это просто!

• Откройте настройки и перейдите во вкладку <b>API</b>. Нажмите <b>1 +</b>, чтобы добавить новый пресет.
• Выберите <b>2 - Шаблон</b> провайдера — например, OpenRouter, Gemini, или KodikRouter и нажмите <b>OK</b>. Если вашего провайдера нет в списке, используйте вариант «Без шаблона».
Затем вам понадобится <b>3 - API-ключ</b>. Перейдите по ссылке <b>4 - Получить ключ</b>, зарегистрируйтесь у провайдера и вставьте ключ в соответствующее поле.
Чтобы проверить, всё ли работает, нажмите <b>5 - Тест подключения</b> и выберите модель из списка. Или оставьте ту, что предложена по умолчанию.
В конце нажмите <b>6 - Сохранить</b> — и пресет готов! Теперь Мита будет думать именно с помощью этой модели."""

    def get_description_en(self):
        return """For NeuroMita to come alive and chat with you, she needs access to a language model — her “brain”. Let’s create your first API preset. It’s easy!

Open the settings and go to the <b>API</b> tab. Click <b>1 +</b> to add a new preset.
Choose a <b>2 - Template</b> — for example, OpenRouter, Gemini, or KodikRouter — and click <b>OK</b>. If your provider isn't listed, select “No template”.
Next, you’ll need an <b>3 - API key</b>. Follow the <b>4 - Get key</b> link, sign up with the provider, and paste the key into the field.
To make sure everything works, click <b>5 - Test Connection</b> and pick a model from the list. Or keep the default one.
Finally, click <b>6 - Save</b> — and your preset is ready! Now Mita will think using this model."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_preset.png" if language == "ru" else "guide/guide_preset1.png"

    def get_wiki_target(self):
        return "getting-started.md"



class VoiceoverGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Озвучка — голосовые ответы"

    def get_title_en(self):
        return "Voiceover — Voice Responses"

    def get_description_ru(self):
        return """Хотите, чтобы Мита отвечала голосом?
• Включите <b>1 - Использовать озвучку</b>.
• В <b>2 - Методе озвучки</b> выберите <b>TG</b> для Telegram или <b>Local</b> для локального синтеза.

<b>Если выбрали Local:</b>
• Укажите <b>3 - язык озвучки</b>.
• Нажмите <b>4 - Установить</b>. Откроется <b>AI Hub</b>, где можно подобрать голосовую модель.

После установки локальная озвучка готова к работе."""

    def get_description_en(self):
        return """Want Mita to answer with a voice?
• Enable <b>1 - Use speech</b>.
• In <b>2 - Voiceover Method</b>, choose <b>TG</b> for Telegram or <b>Local</b> for local synthesis.

<b>If you choose Local:</b>
• Select <b>3 - the voice language</b>.
• Click <b>4 - Install</b>. <b>AI Hub</b> will open so you can choose a voice model.

After installation, local voiceover is ready to use."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_voice.png" if language == "ru" else "guide/guide_voice1.png"

    def get_wiki_target(self):
        return "voice-microphone-camera-and-screen.md"


    def get_image_crop(self):
        return (0.02, 0.09, 0.98, 0.70)


class MicrophoneGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Голосовой ввод (Микрофон)"

    def get_title_en(self):
        return "Voice Input (Microphone)"

    def get_description_ru(self):
        return """Вы можете не только слышать Миту, но и говорить с ней, используя ввод голосом.

Чтобы включить микрофон:
• Перейдите в настройки.
• Выберите вкладку <b>ASR</b> со значком микрофона.
• Выберите ваш микрофон из <b>1 - списка устройств</b>.
• Нажмите кнопку <b>2 - Перейти к настройкам AI Engine</b>.
• Откроется <b>AI Hub</b> — перейдите на вкладку <b>3 - Распознавание (ASR)</b>.
• Выберите подходящую модель распознавания речи и дождитесь установки.
• Установите галочку <b>4 - Микрофон активен</b>

Теперь можно общаться с Митой голосом."""

    def get_description_en(self):
        return """You can not only hear Mita, but also talk to her using voice input.

To set up the microphone:
• Go to Settings.
• Select the <b>ASR</b> tab with the microphone icon.
• Choose your microphone from <b>1 - the device list</b>.
• Click the <b>2 - Open AI Engine settings</b> button.
• The <b>AI Hub</b> will open — go to the <b>3 - ASR</b> tab.
• Select a suitable speech recognition model and wait for it to install.
• Check the box <b>4 - Microphone active</b>.

Now you can talk to Mita with your voice."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_microphone.png" if language == "ru" else "guide/guide_microphone1.png"

    def get_wiki_target(self):
        return "voice-microphone-camera-and-screen.md"



class MemoryGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Память и граф знаний (RAG)"

    def get_title_en(self):
        return "Memory & Knowledge Graph (RAG)"

    def get_description_ru(self):
        return """В NeuroMita появилась продвинутая память! Перейдите в настройки и откройте раздел <b>Модели</b>.
Здесь вы можете:
- Включить улучшенный (RAG) поиск в памяти.
- Настроить векторный поиск в истории.
- Активировать граф знаний — Мита будет понимать связи между объектами.
- И ещё сделать множество улучшений памяти Миты.

<b>Включаем пайплайн:</b>
• Разверните вкладку <b>1 - Пресет пайплайна</b>.
• Выберите один из <b>2 - предустановленных пресетов</b>.
• Нажмите <b>3 - Применить</b>.

<b>Включаем RAG:</b>
• Разверните вкладку <b>4 - RAG и память</b>.
• Включите переключатели <b>5 - Включить RAG</b>, <b>6 - Искать в памяти</b> и <b>7 - Искать в истории</b>.

<b>Включаем векторный поиск:</b>
• Разверните вкладку <b>8 - Векторный поиск и эмбеддинги</b>.
• Активируйте переключатель <b>9 - Векторный поиск</b>.
• <b>10 - Выберите пресет</b> (для начала рекомендуется выбрать пресет с не локальной моделью, например OpenRouter Embeddings или Google Gemini Embeddings).
• Введите <b>11 - API ключ</b> (можно использовать тот же ключ, что и для языковой модели).
• Нажмите <b>12 - Тест</b> — если показало <b>OK</b>, значит модель работает.
• Нажмите <b>13 - Сохранить</b>.
• Нажмите <b>14 - Обновить статус</b>.
• Если появилось сообщение о неиндексированных записях, нажмите <b>15 - Индекс нового</b> и дождитесь окончания процесса индексации.

<b>Активируем граф:</b>
• Разверните вкладку <b>16 - Граф знаний (экстракция сущностей)</b>.
• Активируйте переключатель <b>17 - Включить экстракцию сущностей</b>.
• Рекомендуется также включить <b>18 - Inline-режим</b>.

Всё это делает общение намного глубже: Мита не забывает контекст и может эффективнее рассуждать о различных деталях и ваших приключениях с ней."""

    def get_description_en(self):
        return """NeuroMita now features advanced memory! Go to Settings and open the <b>Models</b> section.
Here you can:
- Enable improved (RAG) memory search.
- Set up vector search in history.
- Activate the knowledge graph — Mita will understand relationships between objects.
- And much more to enhance Mita's memory.

<b>Enabling the pipeline:</b>
• Expand the <b>1 - Pipeline Preset</b> tab.
• Select one of <b>2 - the preset pipelines</b>.
• Click <b>3 - Apply</b>.

<b>Enabling RAG:</b>
• Expand the <b>4 - RAG & Memory</b> tab.
• Turn on the toggles: <b>5 - Enable RAG</b>, <b>6 - Search in Memory</b>, and <b>7 - Search in History</b>.

<b>Enabling vector search:</b>
• Expand the <b>8 - Vector Search and Embeddings</b> tab.
• Activate the switch <b>9 - Vector Search</b>.
• <b>10 - Choose a preset</b> (for starters, it's recommended to pick a non-local model, e.g. OpenRouter Embeddings or Google Gemini Embeddings).
• Enter your <b>11 - API key</b> (you can use the same key as for the language model).
• Click <b>12 - Test</b> — if it shows <b>OK</b>, the model is working.
• Click <b>13 - Save</b>.
• Click <b>14 - Update Status</b>.
• If a message about unindexed records appears, click <b>15 - Index New</b> and wait for the indexing process to finish.

<b>Activating the graph:</b>
• Expand the <b>16 - Knowledge Graph (Entity Extraction)</b> tab.
• Turn on the <b>17 - Enable Entity Extraction</b> toggle.
• It's also recommended to enable <b>18 - Inline Mode</b>.

All this makes conversations much deeper: Mita doesn't forget context and can reason more effectively about various details and your adventures with her."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_memory.png" if language == "ru" else "guide/guide_memory1.png"


class ScreenAnalysisGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Анализ экрана и камеры"

    def get_title_en(self):
        return "Screen & Camera Analysis"

    def get_description_ru(self):
        return """Мита может видеть происходящее на экране, скриншоты или вас через веб-камеру.

<b>Для изображений и скриншотов:</b>
• Перейдите в настройки и откройте раздел <b>Изображения</b>.
• Откройте вкладку <b>1 - Настройки анализа экрана</b>.
• Включите <b>2 - Разрешить обработку изображений</b>.
• Вы можете показывать Мите свой экран каждым сообщением или включить непрерывную отправку (например, для просмотра видео вместе с Митой).
• Можно прикреплять изображение или скриншот экрана и отправлять их Мите с помощью соответствующих кнопок в поле чата песочницы.

<b>Для захвата с камеры:</b>
• Перейдите в настройки и откройте раздел <b>Изображения</b>.
• Откройте вкладку <b>3 - Настройки захвата с камеры</b>.
• Активируйте переключатель <b>4 - Включить захват с камеры</b> (у вас должна быть подключена веб-камера).
• Если OpenCV не установлен, сначала сделайте видимым раздел <b>5 - AI Engine</b> в общих настройках.
• Откройте вкладку <b>6 - AI Engine</b> и нажмите в этой вкладке кнопку <b>AI Hub</b>.
• В AI Hub перейдите на вкладку <b>7 - Зависимости</b>.
• Установите <b>8 - OpenCV</b>.
• Вернитесь в <b>3 - Настройки захвата с камеры</b> и <b>9 - выберите камеру</b>.
Теперь Мита сможет увидеть вас через веб-камеру.

• Мита сможет анализировать изображения, только если выбранная языковая модель поддерживает обработку изображений (например: Gemini, Mistral)."""

    def get_description_en(self):
        return """Mita can see what's happening on your screen, screenshots, or you through your webcam.

<b>For images and screenshots:</b>
• Go to Settings and open the <b>Images</b> section.
• Open the <b>1 - Screen Analysis Settings</b> tab.
• Turn on <b>2 - Enable Image Analysis</b>.
• You can show Mita your screen with every message, or enable continuous capture (for example, to watch videos together with Mita).
• You can attach an image or a screenshot and send it to Mita using the corresponding buttons in the Sandbox chat field.

<b>For camera capture:</b>
• Go to Settings and open the <b>Images</b> section.
• Open the <b>3 - Camera Capture Settings</b> tab.
• Turn on <b>4 - Enable Camera Capture</b> (make sure your webcam is connected).
• If OpenCV is not installed, first make the <b>5 - AI Engine</b> section visible in the general settings.
• Open the <b>6 - AI Engine</b> tab and click the <b>AI Hub</b> button inside it.
• In AI Hub, go to the <b>7 - Dependencies</b> tab.
• Install <b>8 - OpenCV</b>.
• Return to <b>3 - Camera Capture Settings</b> and <b>9 - select your camera</b>.
Now Mita will be able to see you via the webcam.

• Mita can analyze images only if the selected language model supports image processing (e.g., Gemini, Mistral)."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_screen.png" if language == "ru" else "guide/guide_screen1.png"


class MemoryRagGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Память — включаем RAG"

    def get_title_en(self):
        return "Memory — Enable RAG"

    def get_description_ru(self):
        return """Начните с готового пресета и базового RAG-поиска.
• Раскройте <b>1 - Пресет пайплайна</b>, выберите <b>2 - пресет</b> и нажмите <b>3 - Применить</b>.
• Раскройте <b>4 - RAG и память</b>.
• Включите <b>5 - RAG</b>, <b>6 - поиск в памяти</b> и <b>7 - поиск в истории</b>.

Этого уже достаточно для полезной базовой памяти. Следующий шаг — семантический поиск."""

    def get_description_en(self):
        return """Start with a ready-made pipeline and basic RAG search.
• Expand <b>1 - Pipeline Preset</b>, choose <b>2 - a preset</b>, and click <b>3 - Apply</b>.
• Expand <b>4 - RAG & Memory</b>.
• Enable <b>5 - RAG</b>, <b>6 - memory search</b>, and <b>7 - history search</b>.

That is enough for a useful basic memory setup. Next, add semantic search."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_memory.png" if language == "ru" else "guide/guide_memory1.png"

    def get_wiki_target(self):
        return "memory-data-ai-hub-and-debugging.md"


    def get_image_crop(self):
        return (0.02, 0.08, 0.98, 0.36)


class MemoryVectorGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Память — векторный поиск"

    def get_title_en(self):
        return "Memory — Vector Search"

    def get_description_ru(self):
        return """Векторный поиск находит воспоминания, похожие по смыслу.
• Раскройте <b>8 - Векторный поиск и эмбеддинги</b> и включите <b>9 - Векторный поиск</b>.
• Выберите <b>10 - пресет</b>, введите <b>11 - API-ключ</b> и нажмите <b>12 - Тест</b>.
• Если тест успешен, нажмите <b>13 - Сохранить</b>, затем <b>14 - Обновить статус</b>.
• При наличии неиндексированных записей нажмите <b>15 - Индекс нового</b>."""

    def get_description_en(self):
        return """Vector search finds memories that are similar in meaning.
• Expand <b>8 - Vector Search and Embeddings</b> and enable <b>9 - Vector Search</b>.
• Choose <b>10 - a preset</b>, enter <b>11 - the API key</b>, and click <b>12 - Test</b>.
• If the test passes, click <b>13 - Save</b>, then <b>14 - Refresh Status</b>.
• If records are not indexed yet, click <b>15 - Index New</b>."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_memory.png" if language == "ru" else "guide/guide_memory1.png"

    def get_wiki_target(self):
        return "memory-data-ai-hub-and-debugging.md"


    def get_image_crop(self):
        return (0.02, 0.34, 0.98, 0.83)


class MemoryGraphGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Память — граф знаний"

    def get_title_en(self):
        return "Memory — Knowledge Graph"

    def get_description_ru(self):
        return """Граф знаний сохраняет сущности и связи между ними.
• Раскройте <b>16 - Граф знаний</b>.
• Включите <b>17 - экстракцию сущностей</b>.
• Для обычного использования рекомендуется также включить <b>18 - Inline-режим</b>.

RAG, векторный поиск и граф теперь можно настраивать независимо."""

    def get_description_en(self):
        return """The knowledge graph stores entities and relationships between them.
• Expand <b>16 - Knowledge Graph</b>.
• Enable <b>17 - Entity Extraction</b>.
• For normal use, also enable <b>18 - Inline Mode</b>.

RAG, vector search, and the graph can now be tuned independently."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_memory.png" if language == "ru" else "guide/guide_memory1.png"

    def get_wiki_target(self):
        return "memory-data-ai-hub-and-debugging.md"


    def get_image_crop(self):
        return (0.02, 0.82, 0.98, 0.985)


class ScreenCaptureGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Изображения — экран и скриншоты"

    def get_title_en(self):
        return "Images — Screen & Screenshots"

    def get_description_ru(self):
        return """Мита может анализировать экран и прикреплённые изображения.
• В разделе <b>Изображения</b> раскройте <b>1 - Анализ экрана</b>.
• Включите <b>2 - обработку изображений</b>.
• При необходимости включите отправку экрана с сообщениями или непрерывный захват.
• Отдельные изображения и скриншоты можно прикреплять из чата песочницы.

Выбранная языковая модель должна поддерживать изображения."""

    def get_description_en(self):
        return """Mita can analyze your screen and attached images.
• In <b>Images</b>, expand <b>1 - Screen Analysis</b>.
• Enable <b>2 - image analysis</b>.
• Optionally send the screen with messages or enable continuous capture.
• Individual images and screenshots can also be attached from the Sandbox chat.

The selected language model must support image input."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_screen.png" if language == "ru" else "guide/guide_screen1.png"

    def get_wiki_target(self):
        return "voice-microphone-camera-and-screen.md"


    def get_image_crop(self):
        return (0.0, 0.0, 1.0, 0.205)


class CameraGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Камера — включение"

    def get_title_en(self):
        return "Camera — Enable Capture"

    def get_description_ru(self):
        return """Для веб-камеры используется отдельный захват.
• Раскройте <b>3 - Настройки камеры</b>.
• Включите <b>4 - захват с камеры</b>.
• Если камера уже доступна, выберите её в <b>9 - списке устройств</b>.

Если вместо списка написано, что OpenCV не установлен, перейдите к следующему шагу."""

    def get_description_en(self):
        return """Webcam input uses a separate capture path.
• Expand <b>3 - Camera Capture Settings</b>.
• Enable <b>4 - Camera Capture</b>.
• If a camera is already available, choose it in <b>9 - the device list</b>.

If the list says OpenCV is not installed, continue to the next step."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_screen.png" if language == "ru" else "guide/guide_screen1.png"

    def get_wiki_target(self):
        return "voice-microphone-camera-and-screen.md"


    def get_image_crop(self):
        return (0.0, 0.205, 1.0, 0.405)


class CameraDependenciesGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Камера — установка OpenCV"

    def get_title_en(self):
        return "Camera — Install OpenCV"

    def get_description_ru(self):
        return """Этот шаг нужен только если камера требует OpenCV.
• В общих настройках сделайте видимым <b>5 - AI Engine</b>.
• Откройте <b>6 - AI Engine</b> и перейдите в <b>AI Hub</b>.
• В AI Hub выберите <b>7 - Зависимости</b> и установите <b>8 - OpenCV</b>.
• Вернитесь к настройкам камеры и выберите устройство в <b>9</b>."""

    def get_description_en(self):
        return """You only need this step if camera capture requires OpenCV.
• In General settings, make <b>5 - AI Engine</b> visible.
• Open <b>6 - AI Engine</b> and enter <b>AI Hub</b>.
• In AI Hub, choose <b>7 - Dependencies</b> and install <b>8 - OpenCV</b>.
• Return to Camera settings and select the device in <b>9</b>."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_screen.png" if language == "ru" else "guide/guide_screen1.png"

    def get_wiki_target(self):
        return "voice-microphone-camera-and-screen.md"


    def get_image_crop(self):
        return (0.0, 0.39, 1.0, 1.0)


class ModelsGuidePage(IGuidePage):
    min_mode = "full"


    def get_title_ru(self):
        return "Параметры генерации"

    def get_title_en(self):
        return "Generation Parameters"

    def get_description_ru(self):
        return """Вы можете тонко настроить, как именно Мита формулирует ответы.
Для большинства случаев стандартные настройки уже хороши, но если хочется больше креативности или, наоборот, строгости — эти параметры для вас.

<b>Где находятся:</b>
• Откройте настройки и перейдите во вкладку <b>Модели</b>.
• Разверните вкладку <b>1 - Настройки генерации текста</b>.

<b>Основные параметры:</b>
• <b>2 - Макс. токенов в ответе</b> — максимальная длина ответа Миты. Если ответы обрываются — увеличьте значение.
• <b>3 - Температура</b> — управляет креативностью. 0.0 — очень строгие, предсказуемые ответы; 2.0 — очень творческие и неожиданные.
• <b>4 - Top-K</b> — ограничивает выбор только K самых вероятных следующих слов. Чем ниже K (например, 10), тем суше ответ. Чем выше (например, 80), тем разнообразнее лексика.
• <b>5 - Top-P</b> — ядерная выборка: модель перебирает слова, пока их суммарная вероятность не достигнет P. Например, P=0.9 означает, что модель выберет из самого узкого набора слов, дающих 90% уверенности. Низкое P — более сфокусированный ответ, высокое P — больше экспериментов.
• <b>6 - Штраф присутствия</b> — насколько модель избегает повторения уже использованных слов. Положительное значение 0.1–2.0 заставит Миту чаще говорить о новых вещах, а не топтаться на одном.
• <b>7 - Штраф частоты</b> — снижает вероятность повторения одних и тех же слов пропорционально их частоте в ответе. Полезно, если Мита начинает «зацикливаться». Обычно хватает небольшого значения 0.1–0.5, чтобы ответы стали разнообразнее.

Не бойтесь экспериментировать: если результат не нравится, всегда можно вернуться к стандартным."""

    def get_description_en(self):
        return """You can fine-tune how Mita formulates her responses.
The default settings work well for most cases, but if you want more creativity or stricter answers — these parameters are for you.

<b>Where to find them:</b>
• Open Settings and go to the <b>Models</b> tab.
• Expand the <b>1 - Text Generation Settings</b> section.

<b>Key parameters:</b>
• <b>2 - Max tokens in response</b> — the maximum length of Mita's answer. If responses get cut off, increase this value.
• <b>3 - Temperature</b> — controls creativity. 0.0 gives very strict, predictable answers; 2.0 gives very creative, unexpected ones.
• <b>4 - Top-K</b> — limits the selection to only the K most likely next words. A low K (e.g., 10) makes answers more focused and dry; a higher K (e.g., 80) adds lexical variety.
• <b>5 - Top-P</b> — nucleus sampling: the model considers words until their total probability reaches P. For example, P=0.9 means the model picks from the smallest set of words that together have at least 90% confidence. Lower P gives more focused answers, higher P encourages more variety.
• <b>6 - Presence penalty</b> — how much the model avoids repeating words already used. A positive value of 0.1–2.0 encourages Mita to bring up new topics rather than circling around the same ones.
• <b>7 - Frequency penalty</b> — reduces the chance of repeating the same words based on how often they've appeared. Useful if Mita starts sounding repetitive. A small value of 0.1–0.5 usually makes responses more diverse.

Feel free to experiment: if you don't like the results, you can always go back to the defaults."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_models.png" if language == "ru" else "guide/guide_models1.png"


class SandboxGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Песочница: отладка и тестирование"

    def get_title_en(self):
        return "Sandbox: Debugging & Testing"

    def get_description_ru(self):
        return """Если что-то работает не так, как ожидалось, отладка поможет понять, в чём дело.
Перейдите в Песочницу и откройте вкладку <b>1 - Отладка</b> — это мощный инструмент для просмотра состояния Миты и тестирования.

<b>Основные возможности диагностики:</b>
• <b>2 - Открыть DB персонажа</b> — просмотр сохранённых воспоминаний Миты, истории и графических связей.
• <b>3 - Открыть страницу логов</b> — если какую-то ошибку не удаётся исправить, сохраните логи, они помогут разработчикам понять проблему.
• <b>4 - Structured output (дебаг)</b> — выберите <b>5 - JSON</b>, чтобы видеть структуру ответа Миты прямо в чате.
• <b>6 - Вставить system-сообщение в историю</b> — вы можете добавить своё сообщение как системное.
• <b>7 - Просмотр контекста запроса</b>:
  — <b>8 - Посмотреть последний запрос</b> — полный запрос, отправляемый нейросети.
  — <b>9 - Посмотреть последний ответ</b> — полный ответ нейросети."""

    def get_description_en(self):
        return """If something isn't working as expected, the Debug tab will help you figure out what's going on.
Go to the Sandbox and open the <b>1 - Debug</b> tab — a powerful tool for inspecting Mita's state and testing.

<b>Main diagnostic features:</b>
• <b>2 - Open Character DB</b> — view Mita's saved memories, history, and graphical connections.
• <b>3 - Open logs page</b> — if you can't fix an error, save the logs, they will help developers understand the problem.
• <b>4 - Structured output (debug)</b> — select <b>5 - JSON</b> to see the structure of Mita's response directly in the chat.
• <b>6 - Insert system message into history</b> — you can add your own message as a system message.
• <b>7 - Request context viewer</b>:
  — <b>8 - View last request</b> — the full request sent to the neural network.
  — <b>9 - View last response</b> — the full response from the neural network."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_sandbox.png" if language == "ru" else "guide/guide_sandbox1.png"

    def get_wiki_target(self):
        return "memory-data-ai-hub-and-debugging.md"



class FinalGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Готово!"

    def get_title_en(self):
        return "All Set!"

    def get_description_ru(self):
        return """В NeuroMita вы можете общаться с разными Митами, каждая со своим характером и историей.
Миты уже готовы вас принять.

<b>Игра:</b>
Скачайте игру NeuroMita (Unity-версия) и погрузитесь в мир Мит. Поставьте <b>1 - галочку</b> для скачивания Unity. Кнопка «Скачать Unity» загрузит последнюю версию игры.
Если игра уже установлена, просто нажмите «Играть» и начинайте приключение.

<b>⏳ Песочница:</b>
Если нужно общение только в чате, откройте Песочницу.
Здесь также можно:
• Выбрать понравившуюся Миту — <b>2 - Крейзи, Добрая, Сонная и другие</b>.
• Выбрать или настроить <b>3 - Набор промптов</b>, который определит характер и поведение Миты.
• Выбрать <b>4 - Пресет</b> для Миты.
• Можно сразу начать чат — Мита ответит, используя созданный вами пресет.

<b>Помните: это лишь основные настройки. Не бойтесь исследовать и другие разделы — NeuroMita умеет гораздо больше!</b>"""

    def get_description_en(self):
        return """In NeuroMita you can chat with different Mitas, each with their own personality and story.
The Mitas are ready to welcome you.

<b>Game:</b>
Download the NeuroMita game (Unity version) and dive into the world of Mitas. Check <b>1 - the checkbox</b> to download Unity. The “Download Unity” button will fetch the latest game version.
If the game is already installed, just click “Play” and begin your adventure.

<b>⏳ Sandbox:</b>
If you only need text chat, open the Sandbox.
Here you can also:
• Choose your favorite Mita — <b>2 - Crazy, Kind, Sleepy and others</b>.
• Select or customize <b>3 - a prompt set</b> that defines Mita's character and behavior.
• Choose <b>4 - a preset</b> for Mita.
• Start chatting right away — Mita will respond using the preset you created.

<b>Remember: these are just the main settings. Don't be afraid to explore other sections — NeuroMita can do a whole lot more!</b>"""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_next.png" if language == "ru" else "guide/guide_next1.png"

    def get_wiki_target(self):
        return "getting-started.md"
